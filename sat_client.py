"""Integración con el web service de descarga masiva del SAT.

Implementado con la librería open source `satcfdi` (MIT), cuya API se verificó
leyendo su código fuente instalado (versión 26.8.0). No se inventó ningún
endpoint: las URLs SOAP salen de la propia librería.

ESTADO: pendiente de verificación con una e.firma real. El flujo está
implementado según la documentación/código de satcfdi, pero no se ha probado
contra el SAT de verdad porque no hay credenciales disponibles.

Flujo del SAT (asíncrono):
  1. SolicitaDescarga -> devuelve IdSolicitud (no trae datos todavía)
  2. VerificaSolicitudDescarga (polling cada ~60 s): estados 1=Aceptada,
     2=En proceso, 3=Terminada, 4=Error, 5=Rechazada, 6=Vencida
  3. Cuando está Terminada, DescargaMasiva por cada IdPaquete -> ZIP (base64)
     con los XML individuales. Los paquetes vencen a las 72 horas.

Quirks reales documentados:
  - La descarga masiva EXIGE e.firma (.cer/.key + contraseña); la contraseña
    del portal (CIEC) no sirve para el web service.
  - El SAT tarda de minutos a horas en preparar los paquetes.
  - Límite aprox. de 200 mil CFDI por solicitud: si se excede, el SAT responde
    código 5003 y hay que dividir el rango de fechas.
  - Código 5004 = no hay CFDIs en el periodo solicitado.
  - SAT v1.5: el atributo EstadoComprobante es OBLIGATORIO aunque la doc diga
    que es opcional. Omitirlo causa rechazo 301 ("No se permite la descarga
    de xml que se encuentren cancelados"). Se envía siempre "Vigente": solo
    trae comprobantes vigentes; los cancelados no vienen en la descarga CFDI.
"""
from __future__ import annotations

import base64
import io
import zipfile
from datetime import date
from typing import Optional

# Estados de la solicitud según el SAT
ESTADOS_SOLICITUD = {
    1: "aceptada",
    2: "en_proceso",
    3: "terminada",
    4: "error",
    5: "rechazada",
    6: "vencida",
}

# Códigos de respuesta documentados del SAT -> mensaje en español
CODIGOS_SAT = {
    "5000": "Solicitud recibida correctamente.",
    "5002": "Ya existe una solicitud igual en proceso (solicitud duplicada).",
    "5003": "Demasiados comprobantes para una sola solicitud: divide el rango en periodos más cortos.",
    "5004": "El SAT no encontró CFDIs en ese periodo.",
    "5005": "Ya existe una solicitud igual (duplicada).",
    "5011": "Se alcanzó el límite diario de folios descargados. Intenta mañana.",
}


def _sat(cer_bytes: bytes, key_bytes: bytes, password: str):
    """Crea el cliente SAT autenticado con la e.firma (todo en memoria)."""
    from satcfdi.models import Signer
    from satcfdi.pacs.sat import SAT

    signer = Signer.load(certificate=cer_bytes, key=key_bytes, password=password)
    return SAT(signer=signer)


def solicitar_descarga(
    cer_bytes: bytes,
    key_bytes: bytes,
    password: str,
    rfc: str,
    tipo: str,
    fecha_inicio: date,
    fecha_fin: date,
) -> str:
    """Solicita la descarga masiva al SAT. Devuelve el IdSolicitud.

    tipo: 'emitidas' | 'recibidas'. Las nóminas (TipoDeComprobante 'N') vienen
    incluidas en la misma descarga; no requieren una solicitud aparte.
    """
    from satcfdi.pacs.sat import TipoDescargaMasivaTerceros, EstadoComprobante

    sat = _sat(cer_bytes, key_bytes, password)
    # NOTA (quirk real del SAT v1.5, verificado 2026-10-02): el atributo
    # EstadoComprobante es obligatorio aunque la documentación diga que es
    # opcional. Si se omite, el SAT rechaza con código 301 ("No se permite la
    # descarga de xml que se encuentren cancelados"). Se fuerza "Vigente":
    # solo trae comprobantes vigentes (los cancelados no vienen en CFDI).
    if tipo == "emitidas":
        resp = sat.recover_comprobante_emitted_request(
            fecha_inicial=fecha_inicio,
            fecha_final=fecha_fin,
            rfc_emisor=rfc,
            tipo_solicitud=TipoDescargaMasivaTerceros.CFDI,
            estado_comprobante=EstadoComprobante.VIGENTE,
        )
    elif tipo == "recibidas":
        resp = sat.recover_comprobante_received_request(
            fecha_inicial=fecha_inicio,
            fecha_final=fecha_fin,
            rfc_receptor=rfc,
            tipo_solicitud=TipoDescargaMasivaTerceros.CFDI,
            estado_comprobante=EstadoComprobante.VIGENTE,
        )
    else:
        raise ValueError("tipo debe ser 'emitidas' o 'recibidas'")

    codigo = str(resp.get("CodEstatus") or resp.get("CodigoEstadoSolicitud") or "")
    if codigo and codigo not in ("5000",):
        raise RuntimeError(traducir_codigo(codigo, resp.get("Mensaje")))

    id_solicitud = resp.get("IdSolicitud")
    if not id_solicitud:
        raise RuntimeError(
            "El SAT no devolvió un IdSolicitud. Respuesta recibida: "
            f"{dict(resp)}"
        )
    return str(id_solicitud)


def consultar_estado(
    cer_bytes: bytes,
    key_bytes: bytes,
    password: str,
    id_solicitud: str,
) -> dict:
    """Consulta el estado de una solicitud en el SAT."""
    sat = _sat(cer_bytes, key_bytes, password)
    resp = sat.recover_comprobante_status(id_solicitud)
    estado_num = int(resp.get("EstadoSolicitud", 0))
    codigo = str(resp.get("CodigoEstadoSolicitud") or "")
    return {
        "estado_codigo": estado_num,
        "estado": ESTADOS_SOLICITUD.get(estado_num, "desconocido"),
        "ids_paquetes": list(resp.get("IdsPaquetes") or []),
        "numero_cfdis": int(resp.get("NumeroCFDIs") or 0),
        "codigo_sat": codigo,
        "mensaje": resp.get("Mensaje") or traducir_codigo(codigo, None),
    }


def descargar_xmls(
    cer_bytes: bytes,
    key_bytes: bytes,
    password: str,
    ids_paquetes: list[str],
) -> list[bytes]:
    """Descarga cada paquete del SAT y devuelve los XML individuales.

    Cada paquete del SAT es un ZIP (en base64) con los XML adentro.
    """
    sat = _sat(cer_bytes, key_bytes, password)
    xmls: list[bytes] = []
    for id_paquete in ids_paquetes:
        _respuesta, paquete_b64 = sat.recover_comprobante_download(id_paquete)
        zip_bytes = base64.b64decode(paquete_b64)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for nombre in zf.namelist():
                if nombre.lower().endswith(".xml"):
                    xmls.append(zf.read(nombre))
    return xmls


def traducir_codigo(codigo: Optional[str], mensaje_sat: Optional[str]) -> str:
    """Traduce un código de respuesta del SAT a un mensaje claro en español."""
    if codigo in CODIGOS_SAT:
        return CODIGOS_SAT[codigo]
    if mensaje_sat:
        return f"El SAT respondió: {mensaje_sat} (código {codigo})"
    if codigo:
        return f"El SAT devolvió el código {codigo}."
    return "El SAT no dio más detalles."


def traducir_error(exc: Exception) -> str:
    """Convierte una excepción de la librería/SAT en un mensaje en español."""
    texto = f"{type(exc).__name__}: {exc}".lower()

    if any(p in texto for p in ("password", "contraseña", "bad decrypt", "decrypt")):
        return ("La contraseña de la e.firma no es correcta o el .key está dañado. "
                "Verifica los archivos e inténtalo de nuevo.")
    if any(p in texto for p in ("certificate", "certificado", "signer", "firma")):
        return ("La e.firma no es válida (el .cer o el .key no corresponden). "
                "Asegúrate de usar los archivos vigentes de tu e.firma del SAT.")
    if any(p in texto for p in ("timeout", "connection", "conect", "nodename", "name resolution",
                                "max retries", "newconnection")):
        return ("No se pudo contactar al SAT (falla de red o el servicio está caído). "
                "Inténtalo de nuevo en unos minutos.")
    if "5004" in texto:
        return CODIGOS_SAT["5004"]
    if "5003" in texto:
        return CODIGOS_SAT["5003"]
    if "5002" in texto or "5005" in texto:
        return "Ya hay una solicitud igual en proceso en el SAT. Espera a que termine."
    return f"Ocurrió un error al hablar con el SAT: {exc}"
