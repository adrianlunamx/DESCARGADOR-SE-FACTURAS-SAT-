"""Mis Facturas SAT — backend FastAPI (app 100% local).

Endpoints:
  GET  /                          -> UI web
  POST /api/sesion                 -> cargar e.firma (.cer/.key + contraseña) [solo memoria]
  DELETE /api/sesion               -> cerrar sesión (borra la e.firma de memoria)
  POST /api/descarga               -> solicitar descarga masiva al SAT (emitidas/recibidas)
  GET  /api/solicitudes            -> estado de las solicitudes de descarga
  POST /api/importar-xmls          -> importar XMLs manualmente (útil sin e.firma)
  GET  /api/facturas               -> listar con filtros (tipo, fechas, RFC, texto, montos, nómina)
  GET  /api/facturas/{uuid}        -> detalle (conceptos, impuestos, nómina)
  GET  /api/facturas/{uuid}/xml    -> descargar XML individual
  GET  /api/facturas/{uuid}/pdf    -> representación impresa en PDF (con QR)
  GET  /api/exportar-zip           -> ZIP con los XML filtrados
  GET  /api/resumen                -> conteos rápidos
"""
from __future__ import annotations

import io
import os
import zipfile
from datetime import date
from typing import Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import db
import parser as parser_cfdi
import sesion
from pdf_gen import generar_pdf

app = FastAPI(title="Mis Facturas SAT", version="0.1.0")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------- Sesión de e.firma (solo memoria) ----------

@app.post("/api/sesion")
async def crear_sesion(
    cer: UploadFile = File(..., description="Archivo .cer de la e.firma"),
    key: UploadFile = File(..., description="Archivo .key de la e.firma"),
    password: str = Form(..., description="Contraseña de la e.firma"),
    rfc: str = Form(..., description="RFC del contribuyente"),
):
    cer_bytes = await cer.read()
    key_bytes = await key.read()
    if not cer_bytes or not key_bytes:
        raise HTTPException(400, "El .cer y el .key no pueden estar vacíos")
    if not password or not rfc:
        raise HTTPException(400, "La contraseña y el RFC son obligatorios")
    token = sesion.crear_sesion(cer_bytes, key_bytes, password, rfc)
    return {
        "token": token,
        "rfc": rfc.upper().strip(),
        "aviso": "Tu e.firma vive solo en la memoria de esta app y se borra a los 30 min sin uso o al cerrar sesión. Nunca se guarda en disco.",
    }


@app.delete("/api/sesion")
def cerrar_sesion(authorization: Optional[str] = Header(None)):
    token = _token(authorization)
    sesion.cerrar_sesion(token or "")
    return {"ok": True, "mensaje": "Sesión cerrada: la e.firma se eliminó de la memoria"}


def _token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    partes = authorization.split()
    return partes[-1] if partes else None


def _sesion_requerida(authorization: Optional[str]) -> sesion.SesionEFirma:
    token = _token(authorization)
    s = sesion.obtener_sesion(token or "") if token else None
    if s is None:
        raise HTTPException(
            401,
            "No hay sesión de e.firma activa (o expiró). Carga tu .cer/.key de nuevo.",
        )
    return s


# ---------- Descarga masiva (SAT) ----------

@app.post("/api/descarga")
async def solicitar_descarga(
    tipo: str = Form(..., description="emitidas | recibidas | ambas"),
    fecha_inicio: str = Form(...),
    fecha_fin: str = Form(...),
    authorization: Optional[str] = Header(None),
):
    s = _sesion_requerida(authorization)
    if tipo not in ("emitidas", "recibidas", "ambas"):
        raise HTTPException(400, "tipo debe ser 'emitidas', 'recibidas' o 'ambas'")
    try:
        fi = date.fromisoformat(fecha_inicio)
        ff = date.fromisoformat(fecha_fin)
    except ValueError:
        raise HTTPException(400, "Las fechas deben tener formato aaaa-mm-dd")
    if fi > ff:
        raise HTTPException(400, "La fecha de inicio no puede ser posterior a la final")

    # La integración real con el SAT vive en sat_client.py (librería elegida).
    # Se importa aquí para no romper el arranque si falta la dependencia.
    try:
        import sat_client
    except ImportError as exc:
        raise HTTPException(
            501,
            "La integración con el SAT aún no está instalada en este equipo "
            f"(falta la librería de descarga masiva: {exc}). "
            "Mientras tanto puedes importar XMLs manualmente en la pestaña 'Importar'.",
        )

    tipos = ["emitidas", "recibidas"] if tipo == "ambas" else [tipo]
    resultados = []
    for t in tipos:
        try:
            sol_id = sat_client.solicitar_descarga(
                cer_bytes=s.cer_bytes, key_bytes=s.key_bytes,
                password=s.password, rfc=s.rfc, tipo=t,
                fecha_inicio=fi, fecha_fin=ff,
            )
            with db.get_conn() as conn:
                conn.execute(
                    """INSERT INTO solicitudes
                       (rfc, tipo, fecha_inicio, fecha_fin, estado, detalle, created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (s.rfc, t, fecha_inicio, fecha_fin, "en_proceso",
                     sol_id, db._utcnow()),
                )
            resultados.append({"tipo": t, "estado": "en_proceso",
                               "id_solicitud": sol_id})
        except Exception as exc:  # noqa: BLE001 - se traduce a mensaje en español
            resultados.append({"tipo": t, "estado": "error",
                               "detalle": sat_client.traducir_error(exc)})
    return {"resultados": resultados,
            "nota": "El SAT tarda de minutos a horas en preparar los paquetes. "
                    "Consulta el estado en 'Solicitudes'."}


@app.get("/api/solicitudes")
def listar_solicitudes():
    with db.get_conn() as conn:
        filas = conn.execute(
            "SELECT * FROM solicitudes ORDER BY id DESC LIMIT 50").fetchall()
    return [dict(f) for f in filas]


@app.post("/api/solicitudes/{sol_id}/revisar")
def revisar_solicitud(sol_id: int, authorization: Optional[str] = Header(None)):
    """Consulta el estado de una solicitud en el SAT y, si ya está terminada,
    descarga los paquetes e importa los XML a la base local.

    Requiere la sesión de e.firma activa (las credenciales siguen en memoria).
    El SAT tarda de minutos a horas: si aún está en proceso, solo se actualiza
    el estado y se puede reintentar más tarde.
    """
    s = _sesion_requerida(authorization)
    try:
        import sat_client
    except ImportError as exc:
        raise HTTPException(
            501, f"Falta la librería de descarga masiva del SAT ({exc}).")

    with db.get_conn() as conn:
        sol = conn.execute(
            "SELECT * FROM solicitudes WHERE id = ?", (sol_id,)).fetchone()
    if not sol:
        raise HTTPException(404, "No existe esa solicitud")
    sol = dict(sol)
    id_sat = sol["detalle"]  # aquí guardamos el IdSolicitud del SAT

    try:
        estado = sat_client.consultar_estado(
            s.cer_bytes, s.key_bytes, s.password, id_sat)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, sat_client.traducir_error(exc))

    with db.get_conn() as conn:
        conn.execute(
            "UPDATE solicitudes SET estado = ?, detalle = ? WHERE id = ?",
            (estado["estado"], id_sat, sol_id))

    if estado["estado"] != "terminada":
        return {
            "estado": estado["estado"],
            "mensaje": estado["mensaje"],
            "numero_cfdis": estado["numero_cfdis"],
            "nota": ("El SAT aún no termina de preparar los paquetes. "
                     "Vuelve a revisar en unos minutos."),
        }

    # Terminada: descargar paquetes e importar XMLs
    try:
        xmls = sat_client.descargar_xmls(
            s.cer_bytes, s.key_bytes, s.password, estado["ids_paquetes"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, sat_client.traducir_error(exc))

    tipo_flujo = "emitida" if sol["tipo"] == "emitidas" else "recibida"
    nuevos, duplicados, errores = 0, 0, []
    for xml_bytes in xmls:
        try:
            datos = parser_cfdi.parse_cfdi(xml_bytes)
            _, es_nuevo = db.guardar_factura(datos, tipo_flujo, xml_bytes)
            if es_nuevo:
                nuevos += 1
            else:
                duplicados += 1
        except Exception as exc:  # noqa: BLE001
            errores.append(str(exc))

    with db.get_conn() as conn:
        conn.execute(
            "UPDATE solicitudes SET estado = 'lista' WHERE id = ?", (sol_id,))

    return {
        "estado": "lista",
        "paquetes": len(estado["ids_paquetes"]),
        "nuevos": nuevos,
        "duplicados": duplicados,
        "errores": errores[:5],
        "nota": f"Se importaron {nuevos} CFDI nuevos a tu base local.",
    }


# ---------- Importación manual de XML (sin e.firma) ----------

@app.post("/api/importar-xmls")
async def importar_xmls(
    archivos: list[UploadFile] = File(...),
    tipo_flujo: str = Form("recibida", description="emitida | recibida"),
):
    """Importa XMLs de CFDI subidos manualmente.

    Útil para probar la app sin e.firma, o para cargar XMLs descargados
    a mano desde el portal del SAT.
    """
    if tipo_flujo not in ("emitida", "recibida"):
        raise HTTPException(400, "tipo_flujo debe ser 'emitida' o 'recibida'")
    nuevos, duplicados, errores = 0, 0, []
    for archivo in archivos:
        contenido = await archivo.read()
        try:
            datos = parser_cfdi.parse_cfdi(contenido)
            _, es_nuevo = db.guardar_factura(datos, tipo_flujo, contenido)
            if es_nuevo:
                nuevos += 1
            else:
                duplicados += 1
        except Exception as exc:  # noqa: BLE001
            errores.append({"archivo": archivo.filename, "error": str(exc)})
    return {"nuevos": nuevos, "duplicados": duplicados, "errores": errores}


# ---------- Consulta ----------

@app.get("/api/facturas")
def listar_facturas(
    tipo_flujo: Optional[str] = Query(None, description="emitida | recibida"),
    tipo_comprobante: Optional[str] = Query(None, description="I, E, N (nómina), P, T"),
    solo_nominas: bool = Query(False, description="atajo: solo comprobantes de nómina"),
    fecha_inicio: Optional[str] = Query(None),
    fecha_fin: Optional[str] = Query(None),
    rfc: Optional[str] = Query(None, description="filtra por RFC emisor o receptor"),
    texto: Optional[str] = Query(None, description="búsqueda libre"),
    min_total: Optional[float] = Query(None),
    max_total: Optional[float] = Query(None),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
):
    if solo_nominas:
        tipo_comprobante = "N"
    filas, total = db.buscar_facturas(
        tipo_flujo=tipo_flujo, tipo_comprobante=tipo_comprobante,
        fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, rfc=rfc, texto=texto,
        min_total=min_total, max_total=max_total, limit=limit, offset=offset,
    )
    return {"total": total, "limit": limit, "offset": offset, "facturas": filas}


@app.get("/api/facturas/{uuid}")
def detalle_factura(uuid: str):
    datos = db.obtener_factura(uuid)
    if not datos:
        raise HTTPException(404, "No se encontró la factura con ese UUID")
    return datos


@app.get("/api/facturas/{uuid}/xml")
def descargar_xml(uuid: str):
    datos = db.obtener_factura(uuid)
    if not datos or not datos.get("xml_nombre"):
        raise HTTPException(404, "No se encontró el XML de esa factura")
    ruta = os.path.join(db.XML_DIR, datos["xml_nombre"])
    return FileResponse(ruta, media_type="application/xml",
                        filename=f"{uuid}.xml")


@app.get("/api/facturas/{uuid}/pdf")
def descargar_pdf(uuid: str):
    datos = db.obtener_factura(uuid)
    if not datos:
        raise HTTPException(404, "No se encontró la factura con ese UUID")
    pdf = generar_pdf(datos)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename={uuid}.pdf"})


@app.get("/api/exportar-zip")
def exportar_zip(
    tipo_flujo: Optional[str] = Query(None),
    tipo_comprobante: Optional[str] = Query(None),
    solo_nominas: bool = Query(False),
    fecha_inicio: Optional[str] = Query(None),
    fecha_fin: Optional[str] = Query(None),
):
    """Descarga en un ZIP los XML de las facturas que coincidan con los filtros."""
    if solo_nominas:
        tipo_comprobante = "N"
    filas, _ = db.buscar_facturas(
        tipo_flujo=tipo_flujo, tipo_comprobante=tipo_comprobante,
        fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, limit=100000)
    if not filas:
        raise HTTPException(404, "No hay facturas que coincidan con esos filtros")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in filas:
            ruta = os.path.join(db.XML_DIR, f["xml_nombre"])
            if os.path.exists(ruta):
                zf.write(ruta, f"{f['uuid']}.xml")
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=facturas_sat.zip"},
    )


@app.get("/api/resumen")
def resumen():
    return db.resumen()


# ---------- Manejo de errores en español ----------

@app.exception_handler(HTTPException)
async def _http_error(_request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
