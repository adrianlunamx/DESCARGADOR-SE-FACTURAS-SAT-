"""Parseo de XML CFDI (SAT, México) a diccionarios Python.

Soporta CFDI 3.3 y 4.0. Extrae los datos fiscales principales y, cuando el
comprobante trae complemento de nómina (TipoDeComprobante "N", nómina 1.2),
también extrae percepciones totales, deducciones totales y neto pagado.

Todo el código, mensajes y comentarios están en español.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Optional

# Namespaces oficiales del SAT
NS_CFDI_40 = "http://www.sat.gob.mx/cfd/4"
NS_CFDI_33 = "http://www.sat.gob.mx/cfd/3"
NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"
NS_NOMINA12 = "http://www.sat.gob.mx/nomina12"


def _num(valor: Optional[str]) -> Optional[float]:
    """Convierte un atributo numérico del XML a float (None si no existe)."""
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _tag(ns: str, nombre: str) -> str:
    return f"{{{ns}}}{nombre}"


def _detectar_ns(raiz: ET.Element) -> str:
    """Detecta si el comprobante es CFDI 3.3 o 4.0 por su namespace."""
    if raiz.tag.startswith("{" + NS_CFDI_40 + "}"):
        return NS_CFDI_40
    if raiz.tag.startswith("{" + NS_CFDI_33 + "}"):
        return NS_CFDI_33
    raise ValueError("El XML no parece un CFDI válido (namespace desconocido)")


def _extraer_nomina(complemento: Optional[ET.Element]) -> Optional[dict[str, Any]]:
    """Extrae el detalle completo del complemento de nómina 1.2, si existe.

    Cubre: atributos del nodo Nomina, Emisor (registro patronal), Receptor
    (datos del empleado), Percepciones (con horas extra y acciones/títulos),
    Deducciones, OtrosPagos (con subsidio) e Incapacidades.
    """
    if complemento is None:
        return None
    nomina = complemento.find(_tag(NS_NOMINA12, "Nomina"))
    if nomina is None:
        return None

    total_percepciones = _num(nomina.get("TotalPercepciones")) or 0.0
    total_deducciones = _num(nomina.get("TotalDeducciones")) or 0.0
    total_otros_pagos = _num(nomina.get("TotalOtrosPagos")) or 0.0
    neto = total_percepciones + total_otros_pagos - total_deducciones

    # Emisor del complemento (patrón)
    emisor_patron: dict[str, Any] = {}
    nodo_emi = nomina.find(_tag(NS_NOMINA12, "Emisor"))
    if nodo_emi is not None:
        emisor_patron = {
            "curp": nodo_emi.get("Curp"),
            "registro_patronal": nodo_emi.get("RegistroPatronal"),
            "rfc_patron_origen": nodo_emi.get("RfcPatronOrigen"),
        }

    # Receptor del complemento (empleado)
    empleado: dict[str, Any] = {}
    nodo_rec = nomina.find(_tag(NS_NOMINA12, "Receptor"))
    if nodo_rec is not None:
        empleado = {
            "curp": nodo_rec.get("Curp"),
            "num_seguridad_social": nodo_rec.get("NumSeguridadSocial"),
            "fecha_inicio_rel_laboral": nodo_rec.get("FechaInicioRelLaboral"),
            "antiguedad": nodo_rec.get("Antiguedad"),
            "tipo_contrato": nodo_rec.get("TipoContrato"),
            "sindicalizado": nodo_rec.get("Sindicalizado"),
            "tipo_jornada": nodo_rec.get("TipoJornada"),
            "tipo_regimen": nodo_rec.get("TipoRegimen"),
            "num_empleado": nodo_rec.get("NumEmpleado"),
            "departamento": nodo_rec.get("Departamento"),
            "puesto": nodo_rec.get("Puesto"),
            "riesgo_puesto": nodo_rec.get("RiesgoPuesto"),
            "periodicidad_pago": nodo_rec.get("PeriodicidadPago"),
            "banco": nodo_rec.get("Banco"),
            "cuenta_bancaria": nodo_rec.get("CuentaBancaria"),
            "salario_base_cot_apor": _num(nodo_rec.get("SalarioBaseCotApor")),
            "salario_diario_integrado": _num(nodo_rec.get("SalarioDiarioIntegrado")),
            "clave_ent_fed": nodo_rec.get("ClaveEntFed"),
        }

    percepciones: list[dict[str, Any]] = []
    nodo_perc = nomina.find(_tag(NS_NOMINA12, "Percepciones"))
    total_sueldos = total_gravado = total_exento = None
    if nodo_perc is not None:
        total_sueldos = _num(nodo_perc.get("TotalSueldos"))
        total_gravado = _num(nodo_perc.get("TotalGravado"))
        total_exento = _num(nodo_perc.get("TotalExento"))
        for p in nodo_perc.findall(_tag(NS_NOMINA12, "Percepcion")):
            item: dict[str, Any] = {
                "tipo": p.get("TipoPercepcion"),
                "clave": p.get("Clave"),
                "concepto": p.get("Concepto"),
                "gravado": _num(p.get("ImporteGravado")) or 0.0,
                "exento": _num(p.get("ImporteExento")) or 0.0,
            }
            he = p.find(_tag(NS_NOMINA12, "HorasExtra"))
            if he is not None:
                item["horas_extra"] = {
                    "dias": _num(he.get("Dias")),
                    "tipo_horas": he.get("TipoHoras"),
                    "horas_extra": _num(he.get("HorasExtra")),
                    "importe_pagado": _num(he.get("ImportePagado")),
                }
            at = p.find(_tag(NS_NOMINA12, "AccionesOTitulos"))
            if at is not None:
                item["acciones_o_titulos"] = {
                    "valor_mercado": _num(at.get("ValorMercado")),
                    "precio_al_otorgarse": _num(at.get("PrecioAlOtorgarse")),
                }
            percepciones.append(item)

    deducciones: list[dict[str, Any]] = []
    nodo_ded = nomina.find(_tag(NS_NOMINA12, "Deducciones"))
    total_otras_deducciones = total_impuestos_retenidos = None
    if nodo_ded is not None:
        total_otras_deducciones = _num(nodo_ded.get("TotalOtrasDeducciones"))
        total_impuestos_retenidos = _num(nodo_ded.get("TotalImpuestosRetenidos"))
        for d in nodo_ded.findall(_tag(NS_NOMINA12, "Deduccion")):
            deducciones.append({
                "tipo": d.get("TipoDeduccion"),
                "clave": d.get("Clave"),
                "concepto": d.get("Concepto"),
                "importe": _num(d.get("Importe")) or 0.0,
            })

    otros_pagos: list[dict[str, Any]] = []
    nodo_op = nomina.find(_tag(NS_NOMINA12, "OtrosPagos"))
    if nodo_op is not None:
        for o in nodo_op.findall(_tag(NS_NOMINA12, "OtroPago")):
            item_op: dict[str, Any] = {
                "tipo": o.get("TipoOtroPago"),
                "clave": o.get("Clave"),
                "concepto": o.get("Concepto"),
                "importe": _num(o.get("Importe")) or 0.0,
            }
            sub = o.find(_tag(NS_NOMINA12, "SubsidioAlEmpleo"))
            if sub is not None:
                item_op["subsidio_causado"] = _num(sub.get("SubsidioCausado"))
            comp = o.find(_tag(NS_NOMINA12, "CompensacionSaldosAFavor"))
            if comp is not None:
                item_op["compensacion"] = {
                    "saldo_a_favor": _num(comp.get("SaldoAFavor")),
                    "anio": comp.get("Anio"),
                    "remanente": _num(comp.get("RemanenteSalFav")),
                }
            otros_pagos.append(item_op)

    incapacidades: list[dict[str, Any]] = []
    nodo_inc = nomina.find(_tag(NS_NOMINA12, "Incapacidades"))
    if nodo_inc is not None:
        for i in nodo_inc.findall(_tag(NS_NOMINA12, "Incapacidad")):
            incapacidades.append({
                "dias": _num(i.get("DiasIncapacidad")),
                "tipo": i.get("TipoIncapacidad"),
                "importe": _num(i.get("ImporteMonetario")) or 0.0,
            })

    return {
        "tipo_nomina": nomina.get("TipoNomina"),
        "fecha_pago": nomina.get("FechaPago"),
        "fecha_inicial_pago": nomina.get("FechaInicialPago"),
        "fecha_final_pago": nomina.get("FechaFinalPago"),
        "dias_pagados": _num(nomina.get("NumDiasPagados")),
        "total_percepciones": total_percepciones,
        "total_deducciones": total_deducciones,
        "total_otros_pagos": total_otros_pagos,
        "neto": neto,
        "emisor_patron": emisor_patron,
        "empleado": empleado,
        "total_sueldos": total_sueldos,
        "total_gravado": total_gravado,
        "total_exento": total_exento,
        "total_otras_deducciones": total_otras_deducciones,
        "total_impuestos_retenidos": total_impuestos_retenidos,
        "percepciones": percepciones,
        "deducciones": deducciones,
        "otros_pagos": otros_pagos,
        "incapacidades": incapacidades,
    }


def parse_cfdi(xml_bytes: bytes) -> dict[str, Any]:
    """Parsea un XML CFDI y devuelve un dict con los datos relevantes.

    Lanza ValueError si el XML no es un CFDI válido o no trae timbre fiscal.
    """
    try:
        raiz = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"El archivo no es un XML válido: {exc}") from exc

    ns = _detectar_ns(raiz)
    a = raiz.attrib

    emisor = raiz.find(_tag(ns, "Emisor"))
    receptor = raiz.find(_tag(ns, "Receptor"))
    impuestos_nodo = raiz.find(_tag(ns, "Impuestos"))
    complemento = raiz.find(_tag(ns, "Complemento"))

    # Timbre fiscal digital: de aquí sale el UUID (folio fiscal)
    tfd = None
    if complemento is not None:
        tfd = complemento.find(_tag(NS_TFD, "TimbreFiscalDigital"))
    if tfd is None:
        raise ValueError("El CFDI no trae Timbre Fiscal Digital (UUID no encontrado)")

    # Impuestos trasladados y retenidos (atributos del nodo Impuestos)
    traslados: list[dict[str, Any]] = []
    retenciones: list[dict[str, Any]] = []
    imp_attr = impuestos_nodo.attrib if impuestos_nodo is not None else {}
    total_trasladados = _num(imp_attr.get("TotalImpuestosTrasladados"))
    total_retenidos = _num(imp_attr.get("TotalImpuestosRetenidos"))
    if impuestos_nodo is not None:
        nodo_tras = impuestos_nodo.find(_tag(ns, "Traslados"))
        if nodo_tras is not None:
            for t in nodo_tras.findall(_tag(ns, "Traslado")):
                traslados.append({
                    "tipo": "traslado",
                    "impuesto": t.get("Impuesto"),
                    "tipo_factor": t.get("TipoFactor"),
                    "tasa": _num(t.get("TasaOCuota")),
                    "importe": _num(t.get("Importe")) or 0.0,
                })
        nodo_ret = impuestos_nodo.find(_tag(ns, "Retenciones"))
        if nodo_ret is not None:
            for r in nodo_ret.findall(_tag(ns, "Retencion")):
                retenciones.append({
                    "tipo": "retencion",
                    "impuesto": r.get("Impuesto"),
                    "tipo_factor": r.get("TipoFactor"),
                    "tasa": _num(r.get("TasaOCuota")),
                    "importe": _num(r.get("Importe")) or 0.0,
                })

    # Conceptos
    conceptos: list[dict[str, Any]] = []
    nodo_conceptos = raiz.find(_tag(ns, "Conceptos"))
    if nodo_conceptos is not None:
        for c in nodo_conceptos.findall(_tag(ns, "Concepto")):
            conceptos.append({
                "clave_prod_serv": c.get("ClaveProdServ"),
                "descripcion": c.get("Descripcion"),
                "cantidad": _num(c.get("Cantidad")),
                "valor_unitario": _num(c.get("ValorUnitario")),
                "importe": _num(c.get("Importe")),
            })

    return {
        "uuid": tfd.get("UUID"),
        "sello_cfd": tfd.get("SelloCFD"),  # se usa para el QR de verificación
        "fecha": a.get("Fecha"),
        "fecha_timbrado": tfd.get("FechaTimbrado"),
        "tipo_comprobante": a.get("TipoDeComprobante"),
        "serie": a.get("Serie"),
        "folio": a.get("Folio"),
        "emisor": {
            "rfc": emisor.get("Rfc") if emisor is not None else None,
            "nombre": emisor.get("Nombre") if emisor is not None else None,
            "regimen": emisor.get("RegimenFiscal") if emisor is not None else None,
        },
        "receptor": {
            "rfc": receptor.get("Rfc") if receptor is not None else None,
            "nombre": receptor.get("Nombre") if receptor is not None else None,
            "uso_cfdi": receptor.get("UsoCFDI") if receptor is not None else None,
            "regimen": receptor.get("RegimenFiscalReceptor") if receptor is not None else None,
        },
        "moneda": a.get("Moneda"),
        "forma_pago": a.get("FormaPago"),
        "metodo_pago": a.get("MetodoPago"),
        "lugar_expedicion": a.get("LugarExpedicion"),
        "subtotal": _num(a.get("SubTotal")),
        "total": _num(a.get("Total")),
        "total_trasladados": total_trasladados,
        "total_retenidos": total_retenidos,
        "impuestos": traslados + retenciones,
        "conceptos": conceptos,
        # Complemento de nómina (solo presente en TipoDeComprobante "N")
        "nomina": _extraer_nomina(complemento),
    }


# Etiquetas legibles para los tipos de comprobante del SAT
TIPOS_COMPROBANTE = {
    "I": "Ingreso",
    "E": "Egreso",
    "T": "Traslado",
    "N": "Nómina",
    "P": "Pago",
}


def etiqueta_tipo_comprobante(codigo: Optional[str]) -> str:
    """Devuelve la etiqueta legible de un TipoDeComprobante ('N' -> 'Nómina')."""
    return TIPOS_COMPROBANTE.get(codigo or "", codigo or "—")
