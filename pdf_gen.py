"""Genera la representación impresa (PDF) de un CFDI.

Incluye QR de verificación con el formato oficial del SAT:
https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?id=UUID&re=RFC_EMISOR&rr=RFC_RECEPTOR&tt=TOTAL&fe=SELLO8

Nota honesta: el PDF es solo la representación visual; el documento con
validez fiscal es el XML.
"""
from __future__ import annotations

import io
from typing import Any, Optional

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from parser import etiqueta_tipo_comprobante

AZUL = colors.HexColor("#16324F")
GRIS = colors.HexColor("#6B7280")
FONDO = colors.HexColor("#F3F4F6")

# Impuestos del SAT: código -> nombre
IMPUESTOS = {"001": "ISR", "002": "IVA", "003": "IEPS"}


def _qr_verificacion(uuid: str, rfc_emisor: str, rfc_receptor: str,
                     total: Optional[float], sello_cfd: Optional[str]) -> str:
    """Arma la URL de verificación del SAT para el código QR.

    tt: total con 6 decimales, rellenado con ceros a la izquierda (17 posiciones).
    fe: últimos 8 caracteres del sello digital del emisor.
    """
    tt = f"{(total or 0.0):017.6f}"
    fe = (sello_cfd or "")[-8:]
    base = "https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx"
    return f"{base}?id={uuid}&re={rfc_emisor or ''}&rr={rfc_receptor or ''}&tt={tt}&fe={fe}"


def _moneda(valor: Optional[float]) -> str:
    if valor is None:
        return "—"
    return f"${valor:,.2f}"


def generar_pdf(factura: dict[str, Any]) -> bytes:
    """Genera el PDF de representación impresa. Devuelve los bytes del PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm)

    titulo = ParagraphStyle("titulo", fontSize=16, textColor=AZUL,
                            fontName="Helvetica-Bold", spaceAfter=2 * mm)
    subt = ParagraphStyle("subt", fontSize=9, textColor=GRIS, spaceAfter=4 * mm)
    normal = ParagraphStyle("normal", fontSize=9, leading=12)
    chico = ParagraphStyle("chico", fontSize=8, textColor=GRIS, leading=10)
    negrita = ParagraphStyle("negrita", fontSize=9, fontName="Helvetica-Bold")

    tipo = etiqueta_tipo_comprobante(factura.get("tipo_comprobante"))
    folio = f"{factura.get('serie') or ''}{factura.get('folio') or ''}".strip() or "—"

    elementos: list = [
        Paragraph(f"CFDI — {tipo}", titulo),
        Paragraph(f"Folio {folio} &nbsp;|&nbsp; UUID {factura.get('uuid') or '—'}", subt),
    ]

    # Emisor / Receptor
    datos_fiscales = [
        [Paragraph("<b>Emisor</b>", negrita), Paragraph("<b>Receptor</b>", negrita)],
        [Paragraph(f"{factura.get('emisor_nombre') or '—'}<br/>"
                   f"RFC: {factura.get('emisor_rfc') or '—'}", normal),
         Paragraph(f"{factura.get('receptor_nombre') or '—'}<br/>"
                   f"RFC: {factura.get('receptor_rfc') or '—'}", normal)],
        [Paragraph(f"Fecha: {(factura.get('fecha') or '—')[:19]}", chico),
         Paragraph(f"Timbrado: {(factura.get('fecha_timbrado') or '—')[:19]}", chico)],
    ]
    t = Table(datos_fiscales, colWidths=[85 * mm, 85 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), FONDO),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, GRIS),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    elementos += [t, Spacer(1, 5 * mm)]

    # Sección de nómina (si aplica)
    if factura.get("tipo_comprobante") == "N":
        elementos.append(Paragraph("<b>Datos de nómina</b>", negrita))
        nom_datos = [
            ["Fecha de pago", factura.get("nomina_fecha_pago") or "—"],
            ["Días pagados", str(factura.get("nomina_dias_pagados") or "—")],
            ["Total percepciones", _moneda(factura.get("nomina_total_percepciones"))],
            ["Total deducciones", _moneda(factura.get("nomina_total_deducciones"))],
            ["Neto pagado", _moneda(factura.get("nomina_neto"))],
        ]
        tn = Table(nom_datos, colWidths=[60 * mm, 110 * mm])
        tn.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), FONDO),
            ("BOX", (0, 0), (-1, -1), 0.5, GRIS),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ]))
        elementos += [tn, Spacer(1, 5 * mm)]

    # Conceptos
    elementos.append(Paragraph("<b>Conceptos</b>", negrita))
    filas = [[Paragraph("<b>Descripción</b>", chico),
              Paragraph("<b>Cant.</b>", chico),
              Paragraph("<b>P. unitario</b>", chico),
              Paragraph("<b>Importe</b>", chico)]]
    for c in factura.get("conceptos", []):
        filas.append([
            Paragraph(c.get("descripcion") or "—", normal),
            Paragraph(str(c.get("cantidad") or "—"), normal),
            Paragraph(_moneda(c.get("valor_unitario")), normal),
            Paragraph(_moneda(c.get("importe")), normal),
        ])
    if len(filas) == 1:
        filas.append([Paragraph("Sin conceptos registrados", chico), "", "", ""])
    tc = Table(filas, colWidths=[90 * mm, 20 * mm, 30 * mm, 30 * mm])
    tc.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), FONDO),
        ("BOX", (0, 0), (-1, -1), 0.5, GRIS),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    elementos += [tc, Spacer(1, 5 * mm)]

    # Totales
    tot_datos = [
        ["Subtotal", _moneda(factura.get("subtotal"))],
    ]
    if factura.get("total_trasladados"):
        tot_datos.append(["Impuestos trasladados", _moneda(factura.get("total_trasladados"))])
    if factura.get("total_retenidos"):
        tot_datos.append(["Impuestos retenidos", _moneda(factura.get("total_retenidos"))])
    tot_datos.append(["Total", _moneda(factura.get("total"))])
    tt = Table(tot_datos, colWidths=[60 * mm, 40 * mm])
    tt.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, -1), (-1, -1), AZUL),
        ("LINEABOVE", (0, -1), (-1, -1), 1, AZUL),
    ]))
    elementos += [tt, Spacer(1, 6 * mm)]

    # QR de verificación
    url_qr = _qr_verificacion(
        factura.get("uuid") or "", factura.get("emisor_rfc") or "",
        factura.get("receptor_rfc") or "", factura.get("total"),
        factura.get("sello_cfd"),
    )
    img_qr = qrcode.make(url_qr, box_size=6, border=2)
    img_buf = io.BytesIO()
    img_qr.save(img_buf, format="PNG")
    img_buf.seek(0)
    elementos += [
        Image(img_buf, width=35 * mm, height=35 * mm),
        Paragraph("Verifica este comprobante en el portal del SAT con el código QR.", chico),
        Spacer(1, 3 * mm),
        Paragraph("Representación impresa del CFDI. El documento con validez fiscal es el XML.",
                  chico),
    ]

    doc.build(elementos)
    return buf.getvalue()
