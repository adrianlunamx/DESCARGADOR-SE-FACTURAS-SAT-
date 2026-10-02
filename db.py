"""Capa de persistencia: SQLite local para los CFDI descargados.

Todo queda en el disco del usuario (data/facturas.db y data/xml/). No hay
ningún servicio externo: la app es 100% local.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

# La BD vive junto a la app, en data/
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
XML_DIR = os.path.join(DATA_DIR, "xml")
DB_PATH = os.path.join(DATA_DIR, "facturas.db")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    os.makedirs(XML_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Crea las tablas si no existen (idempotente)."""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS facturas (
            id INTEGER PRIMARY KEY,
            uuid TEXT UNIQUE NOT NULL,
            tipo_flujo TEXT NOT NULL,           -- 'emitida' | 'recibida'
            fecha TEXT,                        -- Fecha del comprobante (ISO)
            fecha_timbrado TEXT,               -- Fecha del timbre fiscal
            tipo_comprobante TEXT,             -- I, E, T, N (nómina), P
            serie TEXT,
            folio TEXT,
            emisor_rfc TEXT,
            emisor_nombre TEXT,
            emisor_regimen TEXT,
            receptor_rfc TEXT,
            receptor_nombre TEXT,
            receptor_uso_cfdi TEXT,
            moneda TEXT,
            forma_pago TEXT,
            metodo_pago TEXT,
            lugar_expedicion TEXT,
            subtotal REAL,
            total REAL,
            total_trasladados REAL,
            total_retenidos REAL,
            -- Complemento de nómina (solo TipoDeComprobante 'N')
            nomina_fecha_pago TEXT,
            nomina_dias_pagados REAL,
            nomina_total_percepciones REAL,
            nomina_total_deducciones REAL,
            nomina_neto REAL,
            estatus TEXT NOT NULL DEFAULT 'sin_verificar',
            sello_cfd TEXT,                    -- sello del emisor (para el QR)
            xml_nombre TEXT,                   -- nombre del XML guardado en data/xml/
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_facturas_uuid ON facturas(uuid);
        CREATE INDEX IF NOT EXISTS idx_facturas_flujo ON facturas(tipo_flujo);
        CREATE INDEX IF NOT EXISTS idx_facturas_tipo ON facturas(tipo_comprobante);
        CREATE INDEX IF NOT EXISTS idx_facturas_fecha ON facturas(fecha);

        CREATE TABLE IF NOT EXISTS impuestos (
            id INTEGER PRIMARY KEY,
            factura_id INTEGER NOT NULL REFERENCES facturas(id) ON DELETE CASCADE,
            tipo TEXT NOT NULL,                -- 'traslado' | 'retencion'
            impuesto TEXT,                     -- 002 = IVA, 001 = ISR, 003 = IEPS
            tipo_factor TEXT,
            tasa REAL,
            importe REAL
        );

        CREATE TABLE IF NOT EXISTS conceptos (
            id INTEGER PRIMARY KEY,
            factura_id INTEGER NOT NULL REFERENCES facturas(id) ON DELETE CASCADE,
            clave_prod_serv TEXT,
            descripcion TEXT,
            cantidad REAL,
            valor_unitario REAL,
            importe REAL
        );

        CREATE TABLE IF NOT EXISTS nomina_percepciones (
            id INTEGER PRIMARY KEY,
            factura_id INTEGER NOT NULL REFERENCES facturas(id) ON DELETE CASCADE,
            tipo TEXT,
            clave TEXT,
            concepto TEXT,
            gravado REAL,
            exento REAL
        );

        CREATE TABLE IF NOT EXISTS nomina_deducciones (
            id INTEGER PRIMARY KEY,
            factura_id INTEGER NOT NULL REFERENCES facturas(id) ON DELETE CASCADE,
            tipo TEXT,
            clave TEXT,
            concepto TEXT,
            importe REAL
        );

        CREATE TABLE IF NOT EXISTS solicitudes (
            id INTEGER PRIMARY KEY,
            rfc TEXT NOT NULL,
            tipo TEXT NOT NULL,                -- 'emitidas' | 'recibidas' | 'folio'
            fecha_inicio TEXT NOT NULL,
            fecha_fin TEXT NOT NULL,
            estado TEXT NOT NULL,              -- 'en_proceso' | 'lista' | 'error'
            detalle TEXT,                      -- mensaje o id de solicitud del SAT
            mensaje TEXT,                      -- motivo del SAT (verificación)
            codigo_sat TEXT,                   -- CodigoEstadoSolicitud del SAT
            tipo_descarga TEXT DEFAULT 'CFDI', -- 'CFDI' | 'Metadata'
            folio TEXT,                        -- UUID buscado (solo tipo 'folio')
            archivo TEXT,                      -- archivo de metadata guardado
            created_at TEXT NOT NULL
        );
        """)
        # Migración ligera: columnas agregadas en v2 (solicitudes)
        cols_sol = {r["name"] for r in conn.execute("PRAGMA table_info(solicitudes)")}
        for col, tipo, default in [
            ("mensaje", "TEXT", None),
            ("codigo_sat", "TEXT", None),
            ("tipo_descarga", "TEXT", "'CFDI'"),
            ("folio", "TEXT", None),
            ("archivo", "TEXT", None),
        ]:
            if col not in cols_sol:
                if default is not None:
                    conn.execute(
                        f"ALTER TABLE solicitudes ADD COLUMN {col} {tipo} DEFAULT {default}")
                else:
                    conn.execute(
                        f"ALTER TABLE solicitudes ADD COLUMN {col} {tipo}")
        # Migración ligera: por si la BD ya existía sin columnas de nómina
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(facturas)")}
        for col, tipo in [
            ("nomina_fecha_pago", "TEXT"),
            ("nomina_dias_pagados", "REAL"),
            ("nomina_total_percepciones", "REAL"),
            ("nomina_total_deducciones", "REAL"),
            ("nomina_neto", "REAL"),
            ("sello_cfd", "TEXT"),
        ]:
            if col not in cols:
                conn.execute(f"ALTER TABLE facturas ADD COLUMN {col} {tipo}")


def guardar_factura(datos: dict[str, Any], tipo_flujo: str, xml_bytes: bytes) -> tuple[int, bool]:
    """Guarda un CFDI parseado. Devuelve (id, es_nuevo).

    Si el UUID ya existía, no se duplica: devuelve el id existente y es_nuevo=False.
    El XML se guarda en data/xml/<uuid>.xml.
    """
    nomina = datos.get("nomina") or {}
    with get_conn() as conn:
        existente = conn.execute(
            "SELECT id FROM facturas WHERE uuid = ?", (datos["uuid"],)
        ).fetchone()
        if existente:
            return existente["id"], False

        xml_nombre = f"{datos['uuid']}.xml"
        with open(os.path.join(XML_DIR, xml_nombre), "wb") as f:
            f.write(xml_bytes)

        cur = conn.execute("""
            INSERT INTO facturas (
                uuid, tipo_flujo, fecha, fecha_timbrado, tipo_comprobante,
                serie, folio, emisor_rfc, emisor_nombre, emisor_regimen,
                receptor_rfc, receptor_nombre, receptor_uso_cfdi,
                moneda, forma_pago, metodo_pago, lugar_expedicion,
                subtotal, total, total_trasladados, total_retenidos,
                nomina_fecha_pago, nomina_dias_pagados,
                nomina_total_percepciones, nomina_total_deducciones, nomina_neto,
                sello_cfd, xml_nombre, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            datos["uuid"], tipo_flujo, datos.get("fecha"), datos.get("fecha_timbrado"),
            datos.get("tipo_comprobante"), datos.get("serie"), datos.get("folio"),
            datos["emisor"]["rfc"], datos["emisor"]["nombre"], datos["emisor"]["regimen"],
            datos["receptor"]["rfc"], datos["receptor"]["nombre"], datos["receptor"]["uso_cfdi"],
            datos.get("moneda"), datos.get("forma_pago"), datos.get("metodo_pago"),
            datos.get("lugar_expedicion"), datos.get("subtotal"), datos.get("total"),
            datos.get("total_trasladados"), datos.get("total_retenidos"),
            nomina.get("fecha_pago"), nomina.get("dias_pagados"),
            nomina.get("total_percepciones"), nomina.get("total_deducciones"),
            nomina.get("neto"), datos.get("sello_cfd"), xml_nombre, _utcnow(),
        ))
        factura_id = cur.lastrowid

        for imp in datos.get("impuestos", []):
            conn.execute("""
                INSERT INTO impuestos (factura_id, tipo, impuesto, tipo_factor, tasa, importe)
                VALUES (?,?,?,?,?,?)
            """, (factura_id, imp["tipo"], imp.get("impuesto"), imp.get("tipo_factor"),
                  imp.get("tasa"), imp.get("importe")))

        for c in datos.get("conceptos", []):
            conn.execute("""
                INSERT INTO conceptos (factura_id, clave_prod_serv, descripcion,
                                       cantidad, valor_unitario, importe)
                VALUES (?,?,?,?,?,?)
            """, (factura_id, c.get("clave_prod_serv"), c.get("descripcion"),
                  c.get("cantidad"), c.get("valor_unitario"), c.get("importe")))

        # Detalle de percepciones/deducciones (solo nóminas)
        for p in nomina.get("percepciones", []):
            conn.execute("""
                INSERT INTO nomina_percepciones
                    (factura_id, tipo, clave, concepto, gravado, exento)
                VALUES (?,?,?,?,?,?)
            """, (factura_id, p.get("tipo"), p.get("clave"), p.get("concepto"),
                  p.get("gravado"), p.get("exento")))
        for d in nomina.get("deducciones", []):
            conn.execute("""
                INSERT INTO nomina_deducciones
                    (factura_id, tipo, clave, concepto, importe)
                VALUES (?,?,?,?,?)
            """, (factura_id, d.get("tipo"), d.get("clave"), d.get("concepto"),
                  d.get("importe")))
        return factura_id, True


def buscar_facturas(
    tipo_flujo: Optional[str] = None,
    tipo_comprobante: Optional[str] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    rfc: Optional[str] = None,
    texto: Optional[str] = None,
    min_total: Optional[float] = None,
    max_total: Optional[float] = None,
    estatus: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Busca facturas con filtros. Devuelve (filas, total_sin_paginar)."""
    conds: list[str] = []
    params: list[Any] = []

    if tipo_flujo in ("emitida", "recibida"):
        conds.append("tipo_flujo = ?")
        params.append(tipo_flujo)
    if tipo_comprobante:
        conds.append("tipo_comprobante = ?")
        params.append(tipo_comprobante)
    if fecha_inicio:
        conds.append("date(fecha) >= date(?)")
        params.append(fecha_inicio)
    if fecha_fin:
        conds.append("date(fecha) <= date(?)")
        params.append(fecha_fin)
    if rfc:
        conds.append("(emisor_rfc LIKE ? OR receptor_rfc LIKE ?)")
        params += [f"%{rfc}%", f"%{rfc}%"]
    if texto:
        like = f"%{texto}%"
        conds.append("""(uuid LIKE ? OR emisor_nombre LIKE ? OR receptor_nombre LIKE ?
                        OR folio LIKE ? OR serie LIKE ?
                        OR EXISTS (SELECT 1 FROM conceptos
                                   WHERE conceptos.factura_id = facturas.id
                                   AND conceptos.descripcion LIKE ?))""")
        params += [like] * 6
    if min_total is not None:
        conds.append("total >= ?")
        params.append(min_total)
    if max_total is not None:
        conds.append("total <= ?")
        params.append(max_total)
    if estatus:
        conds.append("estatus = ?")
        params.append(estatus)

    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) c FROM facturas {where}", params).fetchone()["c"]
        filas = conn.execute(
            f"""SELECT * FROM facturas {where}
                ORDER BY fecha DESC, id DESC LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
    return [dict(f) for f in filas], total


def obtener_factura(uuid: str) -> Optional[dict[str, Any]]:
    """Devuelve una factura con sus impuestos y conceptos."""
    with get_conn() as conn:
        fila = conn.execute("SELECT * FROM facturas WHERE uuid = ?", (uuid,)).fetchone()
        if not fila:
            return None
        datos = dict(fila)
        datos["impuestos"] = [dict(r) for r in conn.execute(
            "SELECT * FROM impuestos WHERE factura_id = ?", (fila["id"],))]
        datos["conceptos"] = [dict(r) for r in conn.execute(
            "SELECT * FROM conceptos WHERE factura_id = ?", (fila["id"],))]
        datos["nomina_percepciones"] = [dict(r) for r in conn.execute(
            "SELECT * FROM nomina_percepciones WHERE factura_id = ?", (fila["id"],))]
        datos["nomina_deducciones"] = [dict(r) for r in conn.execute(
            "SELECT * FROM nomina_deducciones WHERE factura_id = ?", (fila["id"],))]
    return datos


def resumen() -> dict[str, Any]:
    """Totales rápidos para el encabezado del dashboard."""
    with get_conn() as conn:
        r = conn.execute("""
            SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM facturas
        """).fetchone()
        emitidas = conn.execute(
            "SELECT COUNT(*) n FROM facturas WHERE tipo_flujo='emitida'").fetchone()["n"]
        recibidas = conn.execute(
            "SELECT COUNT(*) n FROM facturas WHERE tipo_flujo='recibida'").fetchone()["n"]
        nominas = conn.execute(
            "SELECT COUNT(*) n FROM facturas WHERE tipo_comprobante='N'").fetchone()["n"]
    return {"total": r["n"], "monto_total": r["t"],
            "emitidas": emitidas, "recibidas": recibidas, "nominas": nominas}
