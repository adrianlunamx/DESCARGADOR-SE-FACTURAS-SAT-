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
    """Extrae los datos del complemento de nómina 1.2, si existe."""
    if complemento is None:
        return None
    nomina = complemento.find(_tag(NS_NOMINA12, "Nomina"))
    if nomina is None:
        return None

    total_percepciones = _num(nomina.get("TotalPercepciones")) or 0.0
    total_deducciones = _num(nomina.get("TotalDeducciones")) or 0.0
    total_otros_pagos = _num(nomina.get("TotalOtrosPagos")) or 0.0
    neto = total_percepciones + total_otros_pagos - total_deducciones

    percepciones: list[dict[str, Any]] = []
    nodo_perc = nomina.find(_tag(NS_NOMINA12, "Percepciones"))
    if nodo_perc is not None:
        for p in nodo_perc.findall(_tag(NS_NOMINA12, "Percepcion")):
            percepciones.append({
                "tipo": p.get("TipoPercepcion"),
                "clave": p.get("Clave"),
                "concepto": p.get("Concepto"),
                "gravado": _num(p.get("ImporteGravado")) or 0.0,
                "exento": _num(p.get("ImporteExento")) or 0.0,
            })

    deducciones: list[dict[str, Any]] = []
    nodo_ded = nomina.find(_tag(NS_NOMINA12, "Deducciones"))
    if nodo_ded is not None:
        for d in nodo_ded.findall(_tag(NS_NOMINA12, "Deduccion")):
            deducciones.append({
                "tipo": d.get("TipoDeduccion"),
                "clave": d.get("Clave"),
                "concepto": d.get("Concepto"),
                "importe": _num(d.get("Importe")) or 0.0,
            })

    return {
        "fecha_pago": nomina.get("FechaPago"),
        "fecha_inicial_pago": nomina.get("FechaInicialPago"),
        "fecha_final_pago": nomina.get("FechaFinalPago"),
        "dias_pagados": _num(nomina.get("NumDiasPagados")),
        "total_percepciones": total_percepciones,
        "total_deducciones": total_deducciones,
        "total_otros_pagos": total_otros_pagos,
        "neto": neto,
        "percepciones": percepciones,
        "deducciones": deducciones,
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
