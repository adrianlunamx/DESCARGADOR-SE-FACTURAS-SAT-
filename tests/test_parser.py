"""Pruebas del parser de CFDI con XML de ejemplo (datos ficticios).

Ejecutar desde la carpeta app/:  pytest tests/ -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser import parse_cfdi, etiqueta_tipo_comprobante  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _leer(nombre: str) -> bytes:
    with open(os.path.join(FIXTURES, nombre), "rb") as f:
        return f.read()


def test_factura_ingreso():
    d = parse_cfdi(_leer("factura_ingreso.xml"))

    assert d["uuid"] == "ad662d33-6934-4c34-a5b2-8c3e5f7a9b01"
    assert d["tipo_comprobante"] == "I"
    assert d["folio"] == "1234"
    assert d["emisor"]["rfc"] == "AAA010101AAA"
    assert d["emisor"]["nombre"] == "EMPRESA DEMO SA DE CV"
    assert d["receptor"]["rfc"] == "XAXX010101000"
    assert d["subtotal"] == 10000.00
    assert d["total"] == 11600.00
    assert d["total_trasladados"] == 1600.00
    assert d["moneda"] == "MXN"
    assert len(d["conceptos"]) == 1
    assert d["conceptos"][0]["descripcion"] == "Servicio profesional de consultoria"
    # IVA 16% trasladado
    traslados = [i for i in d["impuestos"] if i["tipo"] == "traslado"]
    assert len(traslados) == 1
    assert traslados[0]["impuesto"] == "002"  # 002 = IVA
    assert traslados[0]["importe"] == 1600.00
    # No es nómina
    assert d["nomina"] is None


def test_recibo_nomina():
    d = parse_cfdi(_leer("recibo_nomina.xml"))

    assert d["uuid"] == "b5e7c123-4567-4a89-bcde-f0123456789a"
    assert d["tipo_comprobante"] == "N"
    assert etiqueta_tipo_comprobante("N") == "Nómina"
    assert d["total"] == 14300.00

    nom = d["nomina"]
    assert nom is not None, "Debe detectar el complemento de nómina 1.2"
    assert nom["tipo_nomina"] == "O"
    assert nom["fecha_pago"] == "2026-09-30"
    assert nom["fecha_inicial_pago"] == "2026-09-16"
    assert nom["fecha_final_pago"] == "2026-09-30"
    assert nom["dias_pagados"] == 15.0
    assert nom["total_percepciones"] == 16500.00
    assert nom["total_deducciones"] == 2500.00
    assert nom["total_otros_pagos"] == 300.00
    # Neto = percepciones + otros pagos - deducciones
    assert nom["neto"] == 14300.00

    # Patrón y empleado
    assert nom["emisor_patron"]["registro_patronal"] == "R1234567890"
    assert nom["emisor_patron"]["curp"] == "AAA010101HDFXXX00"
    emp = nom["empleado"]
    assert emp["curp"] == "XAXX010101HDFXXX00"
    assert emp["num_seguridad_social"] == "12345678901"
    assert emp["num_empleado"] == "0042"
    assert emp["puesto"] == "DESARROLLADOR"
    assert emp["departamento"] == "SISTEMAS"
    assert emp["antiguedad"] == "P6A"
    assert emp["salario_diario_integrado"] == 520.83
    assert emp["banco"] == "002"

    # Percepciones con horas extra
    assert len(nom["percepciones"]) == 2
    assert nom["percepciones"][0]["concepto"] == "Sueldos, Salarios Rayas y Jornales"
    he = nom["percepciones"][1]
    assert he["concepto"] == "Horas extra"
    assert he["horas_extra"]["dias"] == 2.0
    assert he["horas_extra"]["tipo_horas"] == "Dobles"
    assert he["horas_extra"]["horas_extra"] == 10.0
    assert he["horas_extra"]["importe_pagado"] == 1500.00

    assert len(nom["deducciones"]) == 2
    assert nom["total_impuestos_retenidos"] == 2000.00

    # Otros pagos con subsidio
    assert len(nom["otros_pagos"]) == 1
    op = nom["otros_pagos"][0]
    assert op["concepto"] == "Subsidio para el empleo"
    assert op["importe"] == 300.00
    assert op["subsidio_causado"] == 300.00

    # Incapacidades
    assert len(nom["incapacidades"]) == 1
    assert nom["incapacidades"][0]["dias"] == 1.0
    assert nom["incapacidades"][0]["tipo"] == "02"


def test_xml_invalido():
    import pytest
    with pytest.raises(ValueError):
        parse_cfdi(b"<esto>no es un cfdi</esto>")
    with pytest.raises(ValueError):
        parse_cfdi(b"ni siquiera xml {{{")


def test_etiquetas_tipos():
    assert etiqueta_tipo_comprobante("I") == "Ingreso"
    assert etiqueta_tipo_comprobante("E") == "Egreso"
    assert etiqueta_tipo_comprobante("N") == "Nómina"
    assert etiqueta_tipo_comprobante("P") == "Pago"
    assert etiqueta_tipo_comprobante("T") == "Traslado"
