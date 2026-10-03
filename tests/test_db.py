"""Pruebas de la capa de persistencia (SQLite local, sin red ni SAT).

Ejecutar desde la carpeta app/:  pytest tests/ -v
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from parser import parse_cfdi  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _usar_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "XML_DIR", str(tmp_path / "xml"))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "facturas.db"))
    db.init_db()


def _leer(nombre):
    with open(os.path.join(FIXTURES, nombre), "rb") as f:
        return f.read()


def test_nomina_guarda_percepciones_y_deducciones(tmp_path, monkeypatch):
    _usar_tmp(tmp_path, monkeypatch)
    xml = _leer("recibo_nomina.xml")
    datos = parse_cfdi(xml)
    fid, nuevo = db.guardar_factura(datos, "recibida", xml)
    assert nuevo

    f = db.obtener_factura(datos["uuid"])
    assert f is not None
    assert len(f["nomina_percepciones"]) == 2
    assert f["nomina_percepciones"][0]["concepto"] == "Sueldos, Salarios Rayas y Jornales"
    assert len(f["nomina_deducciones"]) == 2
    assert f["nomina_neto"] == 14300.00
    # Nuevas tablas v3
    assert len(f["nomina_otros_pagos"]) == 1
    assert f["nomina_otros_pagos"][0]["subsidio_causado"] == 300.00
    assert len(f["nomina_incapacidades"]) == 1
    # Detalle completo como JSON
    det = f["nomina_detalle"]
    assert det is not None
    assert det["empleado"]["puesto"] == "DESARROLLADOR"
    assert det["emisor_patron"]["registro_patronal"] == "R1234567890"
    assert det["percepciones"][1]["horas_extra"]["horas_extra"] == 10.0
    assert det["otros_pagos"][0]["subsidio_causado"] == 300.00


def test_factura_sin_nomina_no_crea_detalle(tmp_path, monkeypatch):
    _usar_tmp(tmp_path, monkeypatch)
    xml = _leer("factura_ingreso.xml")
    datos = parse_cfdi(xml)
    db.guardar_factura(datos, "recibida", xml)
    f = db.obtener_factura(datos["uuid"])
    assert f["nomina_percepciones"] == []
    assert f["nomina_deducciones"] == []


def test_no_duplica_uuid(tmp_path, monkeypatch):
    _usar_tmp(tmp_path, monkeypatch)
    xml = _leer("factura_ingreso.xml")
    datos = parse_cfdi(xml)
    _, n1 = db.guardar_factura(datos, "recibida", xml)
    _, n2 = db.guardar_factura(datos, "recibida", xml)
    assert n1 is True and n2 is False


def test_migracion_solicitudes_desde_esquema_viejo(tmp_path, monkeypatch):
    """Una BD creada con el esquema v1 debe migrar a las columnas v2."""
    _usar_tmp(tmp_path, monkeypatch)
    # Simular esquema viejo: borrar columnas nuevas si existen y recrear tabla vieja
    with db.get_conn() as conn:
        conn.execute("DROP TABLE IF EXISTS solicitudes")
        conn.execute("""
            CREATE TABLE solicitudes (
                id INTEGER PRIMARY KEY,
                rfc TEXT NOT NULL,
                tipo TEXT NOT NULL,
                fecha_inicio TEXT NOT NULL,
                fecha_fin TEXT NOT NULL,
                estado TEXT NOT NULL,
                detalle TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO solicitudes (rfc, tipo, fecha_inicio, fecha_fin, estado, detalle, created_at)"
            " VALUES ('AAA010101AAA','recibidas','2026-01-01','2026-01-31','en_proceso','abc-123','x')")
    # init_db debe agregar las columnas sin romper la fila existente
    db.init_db()
    with db.get_conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(solicitudes)")}
        fila = conn.execute("SELECT * FROM solicitudes").fetchone()
    for col in ["mensaje", "codigo_sat", "tipo_descarga", "folio", "archivo"]:
        assert col in cols, f"falta columna migrada: {col}"
    assert fila["tipo_descarga"] == "CFDI"  # default aplicado
    assert fila["detalle"] == "abc-123"     # dato viejo intacto


def test_buscar_facturas_filtros(tmp_path, monkeypatch):
    _usar_tmp(tmp_path, monkeypatch)
    db.guardar_factura(parse_cfdi(_leer("factura_ingreso.xml")), "recibida", _leer("factura_ingreso.xml"))
    db.guardar_factura(parse_cfdi(_leer("recibo_nomina.xml")), "recibida", _leer("recibo_nomina.xml"))

    filas, total = db.buscar_facturas(tipo_comprobante="N")
    assert total == 1
    filas, total = db.buscar_facturas(texto="consultoria")
    assert total == 1
    filas, total = db.buscar_facturas(min_total=12000)
    assert total == 1  # solo la nómina (total 14300)
    r = db.resumen()
    assert r["total"] == 2 and r["nominas"] == 1
