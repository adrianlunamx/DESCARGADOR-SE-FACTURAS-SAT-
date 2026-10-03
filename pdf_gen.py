"""Genera la representación impresa (PDF) de un CFDI.

Para nóminas produce un recibo de pago con el detalle completo del XML:
percepciones (con horas extra), deducciones, otros pagos, incapacidades
y datos del empleado y del patrón.

Incluye QR de verificación con el formato oficial del SAT:
https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?id=UUID&re=RFC_EMISOR&rr=RFC_RECEPTOR&tt=TOTAL&fe=SELLO8

Nota honesta: el PDF es solo la representación visual; el documento con
validez fiscal es el XML. El SAT no emite PDFs.
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
AZUL_CLARO = colors.HexColor("#E8EEF4")
DORADO = colors.HexColor("#B45309")
DORADO_FONDO = colors.HexColor("#FFFBEB")
GRIS = colors.HexColor("#6B7280")
GRIS_OSCURO = colors.HexColor("#374151")
FONDO = colors.HexColor("#F3F4F6")
ROJO = colors.HexColor("#B91C1C")
VERDE = colors.HexColor("#047857")

# Impuestos del SAT: código -> nombre
IMPUESTOS = {"001": "ISR", "002": "IVA", "003": "IEPS"}


# ---------- Número a letra (español, formato mexicano) ----------
_UNI = ["", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete",
        "ocho", "nueve", "diez", "once", "doce", "trece", "catorce",
        "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve",
        "veinte"]
_DEC = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta",
        "setenta", "ochenta", "noventa"]
_CEN = ["", "ciento", "doscientos", "trescientos", "cuatrocientos",
        "quinientos", "seiscientos", "setecientos", "ochocientos",
        "novecientos"]


def _tres_cifras(n: int) -> str:
    c, r = divmod(n, 100)
    d, u = divmod(r, 10)
    partes: list[str] = []
    if c:
        partes.append("cien" if n == 100 else _CEN[c])
    if r:
        if r <= 20:
            partes.append(_UNI[r])
        elif r < 30:
            partes.append("veinti" + _UNI[u])
        else:
            base = _DEC[d]
            partes.append(f"{base} y {_UNI[u]}" if u else base)
    return " ".join(p for p in partes if p)


def _entero_a_letras(n: int) -> str:
    if n == 0:
        return "cero"
    if n == 100:
        return "cien"
    partes: list[str] = []
    millones, r = divmod(n, 1_000_000)
    miles, resto = divmod(r, 1_000)
    if millones:
        partes.append("un millón" if millones == 1
                      else f"{_entero_a_letras(millones)} millones")
    if miles:
        partes.append("mil" if miles == 1 else f"{_tres_cifras(miles)} mil")
    if resto:
        partes.append(_tres_cifras(resto))
    return " ".join(partes)


def numero_a_letras(valor: Optional[float]) -> str:
    """Convierte un monto a letra estilo 'mil doscientos pesos 34/100 M.N.'."""
    if valor is None:
        return "—"
    entero = int(valor)
    centavos = int(round((valor - entero) * 100))
    letras = _entero_a_letras(entero)
    texto = f"{letras} pesos {centavos:02d}/100 M.N."
    return texto[0].upper() + texto[1:]


def _pie(canvas, doc) -> None:
    """Pie de página: numeración y fecha de generación."""
    from datetime import datetime
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(GRIS)
    canvas.drawCentredString(
        letter[0] / 2, 11 * mm,
        f"Página {doc.page}  ·  Generado el "
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')}")
    # Línea dorada sutil sobre el pie
    canvas.setStrokeColor(DORADO)
    canvas.setLineWidth(0.6)
    canvas.line(15 * mm, 14 * mm, letter[0] - 15 * mm, 14 * mm)
    canvas.restoreState()


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


def _estilos() -> dict[str, ParagraphStyle]:
    return {
        "titulo": ParagraphStyle("titulo", fontSize=17, textColor=colors.white,
                                 fontName="Helvetica-Bold", leading=20),
        "subtitulo": ParagraphStyle("subtitulo", fontSize=9, textColor=colors.white,
                                    leading=11),
        "seccion": ParagraphStyle("seccion", fontSize=11, textColor=AZUL,
                                  fontName="Helvetica-Bold", leading=14,
                                  spaceBefore=6, spaceAfter=4),
        "normal": ParagraphStyle("normal", fontSize=9, leading=12,
                                 textColor=GRIS_OSCURO),
        "chico": ParagraphStyle("chico", fontSize=8, textColor=GRIS, leading=10),
        "negrita": ParagraphStyle("negrita", fontSize=9, leading=12,
                                  fontName="Helvetica-Bold", textColor=GRIS_OSCURO),
        "etiqueta": ParagraphStyle("etiqueta", fontSize=8, textColor=GRIS,
                                   leading=10, fontName="Helvetica-Bold"),
        "num": ParagraphStyle("num", fontSize=9, leading=12, alignment=2,
                              textColor=GRIS_OSCURO),
        "num_b": ParagraphStyle("num_b", fontSize=9, leading=12, alignment=2,
                                fontName="Helvetica-Bold", textColor=GRIS_OSCURO),
    }


def _encabezado(factura: dict[str, Any], e: dict[str, ParagraphStyle]) -> Table:
    tipo = etiqueta_tipo_comprobante(factura.get("tipo_comprobante"))
    folio = f"{factura.get('serie') or ''}{factura.get('folio') or ''}".strip() or "—"
    titulo = "RECIBO DE NÓMINA" if factura.get("tipo_comprobante") == "N" else f"CFDI — {tipo}"
    datos = [
        [Paragraph(titulo, e["titulo"])],
        [Paragraph("COMPROBANTE FISCAL DIGITAL POR INTERNET", ParagraphStyle(
            "cfdi", parent=e["subtitulo"], fontSize=7.5, textColor=colors.HexColor("#FBBF24"),
            fontName="Helvetica-Bold", leading=10))],
        [Paragraph(f"Folio {folio} &nbsp;·&nbsp; UUID {factura.get('uuid') or '—'}",
                   e["subtitulo"])],
    ]
    t = Table(datos, colWidths=[180 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), AZUL),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, DORADO),
        ("LEFTPADDING", (0, 0), (-1, -1), 6 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6 * mm),
        ("TOPPADDING", (0, 0), (-1, 0), 5 * mm),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 5 * mm),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
        ("TOPPADDING", (0, 2), (-1, 2), 1 * mm),
        ("ROUNDEDCORNERS", [3 * mm, 3 * mm, 3 * mm, 3 * mm]),
    ]))
    return t


def _bloque_fiscal(factura: dict[str, Any], e: dict[str, ParagraphStyle]) -> Table:
    def persona(titulo: str, nombre: str, rfc: str) -> list:
        return [Paragraph(f"<b>{titulo}</b>", e["negrita"]),
                Paragraph(nombre or "—", e["normal"]),
                Paragraph(f"RFC: {rfc or '—'}", e["chico"])]
    filas = [
        persona("Emisor", factura.get("emisor_nombre"), factura.get("emisor_rfc")),
        persona("Receptor", factura.get("receptor_nombre"), factura.get("receptor_rfc")),
        [Paragraph(f"Emitido: {(factura.get('fecha') or '—')[:19]}", e["chico"]),
         Paragraph(f"Timbrado: {(factura.get('fecha_timbrado') or '—')[:19]}", e["chico"])],
    ]
    t = Table([[filas[0], filas[1]], [filas[2][0], filas[2][1]]],
              colWidths=[85 * mm, 85 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), AZUL_CLARO),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, GRIS),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ("ROUNDEDCORNERS", [2 * mm, 2 * mm, 2 * mm, 2 * mm]),
    ]))
    return t


def _tabla_detalle(encabezados: list[str], filas: list[list],
                  total_fila: Optional[list] = None,
                  anchos: Optional[list] = None) -> Table:
    datos = [encabezados] + filas
    if total_fila:
        datos.append(total_fila)
    t = Table(datos, colWidths=anchos, repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2 if total_fila else -1),
         [colors.white, colors.HexColor("#F8FAFC")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if total_fila:
        estilo += [
            ("BACKGROUND", (0, -1), (-1, -1), AZUL_CLARO),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ]
    t.setStyle(TableStyle(estilo))
    return t


def _par(texto: Any, e: ParagraphStyle, negrita: bool = False) -> Paragraph:
    txt = "" if texto is None else str(texto)
    if negrita:
        txt = f"<b>{txt}</b>"
    return Paragraph(txt or "—", e)


def _seccion_nomina(factura: dict[str, Any], e: dict[str, ParagraphStyle]) -> list:
    """Recibo de nómina con el detalle completo del XML."""
    n = factura.get("nomina_detalle") or {}
    emp = n.get("empleado") or {}
    pat = n.get("emisor_patron") or {}
    el: list = []

    # Datos del periodo
    tipo_nom = {"O": "Ordinaria", "E": "Extraordinaria"}.get(n.get("tipo_nomina"), "—")
    periodo = [Paragraph("<b>Periodo de pago</b>", e["etiqueta"]),
               Paragraph("<b>Fecha de pago</b>", e["etiqueta"]),
               Paragraph("<b>Días pagados</b>", e["etiqueta"]),
               Paragraph("<b>Tipo de nómina</b>", e["etiqueta"])]
    valores = [_par(f"{n.get('fecha_inicial_pago') or '—'} al {n.get('fecha_final_pago') or '—'}", e["normal"]),
               _par(n.get("fecha_pago") or factura.get("nomina_fecha_pago"), e["normal"]),
               _par(n.get("dias_pagados") if n.get("dias_pagados") is not None
                    else factura.get("nomina_dias_pagados"), e["normal"]),
               _par(tipo_nom, e["normal"])]
    tp = Table([periodo, valores], colWidths=[45 * mm, 45 * mm, 40 * mm, 40 * mm])
    tp.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DORADO_FONDO),
        ("BOX", (0, 0), (-1, -1), 0.5, DORADO),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    el += [tp, Spacer(1, 4 * mm)]

    # Empleado y patrón
    def campo(etiqueta: str, valor: Any) -> Optional[list]:
        if valor in (None, ""):
            return None
        return [Paragraph(f"<b>{etiqueta}</b>", e["etiqueta"]),
                Paragraph(str(valor), e["normal"])]
    filas_emp = [
        campo("Empleado", factura.get("receptor_nombre")),
        campo("No. empleado", emp.get("num_empleado")),
        campo("Puesto", emp.get("puesto")),
        campo("Departamento", emp.get("departamento")),
        campo("CURP", emp.get("curp")),
        campo("NSS", emp.get("num_seguridad_social")),
        campo("Antigüedad", emp.get("antiguedad")),
        campo("Inicio relación laboral", emp.get("fecha_inicio_rel_laboral")),
        campo("Salario diario integrado", _moneda(emp.get("salario_diario_integrado"))
              if emp.get("salario_diario_integrado") else None),
        campo("Salario base de cotización", _moneda(emp.get("salario_base_cot_apor"))
              if emp.get("salario_base_cot_apor") else None),
        campo("Periodicidad de pago", emp.get("periodicidad_pago")),
        campo("Tipo de contrato", emp.get("tipo_contrato")),
        campo("Tipo de jornada", emp.get("tipo_jornada")),
        campo("Banco / cuenta", f"{emp.get('banco')} {emp.get('cuenta_bancaria') or ''}".strip()
              if emp.get("banco") else None),
        campo("Patrón", factura.get("emisor_nombre")),
        campo("Registro patronal", pat.get("registro_patronal")),
    ]
    filas_emp = [r for r in filas_emp if r]
    if filas_emp:
        el.append(Paragraph("Datos del empleado y del patrón", e["seccion"]))
        te = Table(filas_emp, colWidths=[55 * mm, 115 * mm])
        te.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.lightgrey),
        ]))
        el += [te, Spacer(1, 3 * mm)]

    percepciones = n.get("percepciones") or factura.get("nomina_percepciones") or []
    deducciones = n.get("deducciones") or factura.get("nomina_deducciones") or []
    otros_pagos = n.get("otros_pagos") or factura.get("nomina_otros_pagos") or []
    incaps = n.get("incapacidades") or factura.get("nomina_incapacidades") or []

    # Percepciones
    if percepciones:
        el.append(Paragraph(f"Percepciones ({len(percepciones)})", e["seccion"]))
        filas = []
        for p in percepciones:
            total_p = (p.get("gravado") or 0) + (p.get("exento") or 0)
            concepto = f"<b>{p.get('clave') or ''}</b> {p.get('concepto') or '—'}".strip()
            he = p.get("horas_extra")
            if he:
                concepto += (f"<br/><font color=\"#B45309\" size=\"7\">Horas extra: "
                             f"{he.get('dias') or '—'} días · tipo {he.get('tipo_horas') or '—'} · "
                             f"{he.get('horas_extra') or '—'} h · {_moneda(he.get('importe_pagado'))}</font>")
            filas.append([Paragraph(concepto, e["normal"]),
                          Paragraph(_moneda(p.get("gravado")), e["num"]),
                          Paragraph(_moneda(p.get("exento")), e["num"]),
                          Paragraph(_moneda(total_p), e["num_b"])])
        tot = n.get("total_percepciones") if n.get("total_percepciones") is not None \
            else factura.get("nomina_total_percepciones")
        el.append(_tabla_detalle(
            ["Concepto", "Gravado", "Exento", "Total"], filas,
            total_fila=["Total percepciones", "", "", _moneda(tot)],
            anchos=[80 * mm, 30 * mm, 30 * mm, 30 * mm]))
        el.append(Spacer(1, 3 * mm))

    # Deducciones
    if deducciones:
        el.append(Paragraph(f"Deducciones ({len(deducciones)})", e["seccion"]))
        filas = [[Paragraph(f"<b>{d.get('clave') or ''}</b> {d.get('concepto') or '—'}".strip(), e["normal"]),
                  Paragraph(_moneda(d.get("importe")), e["num"])] for d in deducciones]
        tot = n.get("total_deducciones") if n.get("total_deducciones") is not None \
            else factura.get("nomina_total_deducciones")
        el.append(_tabla_detalle(
            ["Concepto", "Importe"], filas,
            total_fila=["Total deducciones", _moneda(tot)],
            anchos=[120 * mm, 50 * mm]))
        el.append(Spacer(1, 3 * mm))

    # Otros pagos
    if otros_pagos:
        el.append(Paragraph(f"Otros pagos ({len(otros_pagos)})", e["seccion"]))
        filas = []
        for o in otros_pagos:
            concepto = f"<b>{o.get('clave') or ''}</b> {o.get('concepto') or '—'}".strip()
            if o.get("subsidio_causado"):
                concepto += f"<br/><font size=\"7\">Subsidio causado: {_moneda(o.get('subsidio_causado'))}</font>"
            filas.append([Paragraph(concepto, e["normal"]),
                          Paragraph(_moneda(o.get("importe")), e["num"])])
        tot = n.get("total_otros_pagos")
        if tot is None:
            tot = sum((o.get("importe") or 0) for o in otros_pagos)
        el.append(_tabla_detalle(
            ["Concepto", "Importe"], filas,
            total_fila=["Total otros pagos", _moneda(tot)],
            anchos=[120 * mm, 50 * mm]))
        el.append(Spacer(1, 3 * mm))

    # Incapacidades
    if incaps:
        el.append(Paragraph(f"Incapacidades ({len(incaps)})", e["seccion"]))
        filas = [[Paragraph(f"Días: {i.get('dias') or '—'} · Tipo {i.get('tipo') or '—'}", e["normal"]),
                  Paragraph(_moneda(i.get("importe")), e["num"])] for i in incaps]
        el.append(_tabla_detalle(["Detalle", "Importe"], filas,
                                 anchos=[120 * mm, 50 * mm]))
        el.append(Spacer(1, 3 * mm))

    # Resumen: percepciones + otros pagos − deducciones = neto
    tot_p = n.get("total_percepciones") if n.get("total_percepciones") is not None \
        else factura.get("nomina_total_percepciones")
    tot_d = n.get("total_deducciones") if n.get("total_deducciones") is not None \
        else factura.get("nomina_total_deducciones")
    tot_o = n.get("total_otros_pagos")
    if tot_o is None:
        tot_o = sum((o.get("importe") or 0) for o in otros_pagos)
    neto = n.get("neto") if n.get("neto") is not None else factura.get("nomina_neto")

    filas_res = [
        [Paragraph("Total percepciones", e["normal"]), Paragraph(_moneda(tot_p), e["num"])],
    ]
    if tot_o:
        filas_res.append([Paragraph("Total otros pagos", e["normal"]),
                          Paragraph(_moneda(tot_o), e["num"])])
    filas_res.append([Paragraph("(−) Total deducciones", e["normal"]),
                      Paragraph(_moneda(tot_d), e["num"])])
    tr = Table(filas_res, colWidths=[110 * mm, 60 * mm])
    tr.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.lightgrey),
    ]))
    el += [tr, Spacer(1, 2 * mm)]

    neto_tabla = Table(
        [[Paragraph("<b>NETO PAGADO</b>", ParagraphStyle(
            "neto_t", parent=e["titulo"], fontSize=13)),
          Paragraph(f"<b>{_moneda(neto)}</b>", ParagraphStyle(
              "neto_v", parent=e["titulo"], fontSize=15, alignment=2))]],
        colWidths=[90 * mm, 80 * mm])
    neto_tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), AZUL),
        ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ("ROUNDEDCORNERS", [2 * mm, 2 * mm, 2 * mm, 2 * mm]),
    ]))
    el += [neto_tabla, Spacer(1, 2 * mm)]
    el.append(Paragraph(f"<i>({numero_a_letras(neto)})</i>",
                        ParagraphStyle("letras", parent=e["chico"], alignment=1,
                                       spaceAfter=2 * mm)))
    el.append(Spacer(1, 2 * mm))
    return el


def _seccion_factura_general(factura: dict[str, Any], e: dict[str, ParagraphStyle]) -> list:
    """Conceptos, impuestos y totales para comprobantes no-nómina."""
    el = [Paragraph("Conceptos", e["seccion"])]
    filas = []
    for c in factura.get("conceptos", []):
        filas.append([
            Paragraph(c.get("descripcion") or "—", e["normal"]),
            Paragraph(str(c.get("cantidad") if c.get("cantidad") is not None else "—"), e["num"]),
            Paragraph(_moneda(c.get("valor_unitario")), e["num"]),
            Paragraph(_moneda(c.get("importe")), e["num_b"]),
        ])
    if not filas:
        filas.append([Paragraph("Sin conceptos registrados", e["chico"]), "", "", ""])
    el.append(_tabla_detalle(["Descripción", "Cant.", "P. unitario", "Importe"], filas,
                             anchos=[90 * mm, 20 * mm, 30 * mm, 30 * mm]))
    el.append(Spacer(1, 3 * mm))

    impuestos = factura.get("impuestos") or []
    if impuestos:
        el.append(Paragraph("Impuestos", e["seccion"]))
        filas = []
        for i in impuestos:
            nombre = IMPUESTOS.get(str(i.get("impuesto")), str(i.get("impuesto") or "—"))
            filas.append([
                Paragraph("Traslado" if i.get("tipo") == "traslado" else "Retención", e["normal"]),
                Paragraph(nombre, e["normal"]),
                Paragraph(str(i.get("tasa") if i.get("tasa") is not None else "—"), e["num"]),
                Paragraph(_moneda(i.get("importe")), e["num"]),
            ])
        el.append(_tabla_detalle(["Tipo", "Impuesto", "Tasa", "Importe"], filas,
                                 anchos=[50 * mm, 40 * mm, 40 * mm, 40 * mm]))
        el.append(Spacer(1, 3 * mm))

    tot_datos = [[Paragraph("Subtotal", e["normal"]), Paragraph(_moneda(factura.get("subtotal")), e["num"])]]
    if factura.get("total_trasladados"):
        tot_datos.append([Paragraph("Impuestos trasladados", e["normal"]),
                          Paragraph(_moneda(factura.get("total_trasladados")), e["num"])])
    if factura.get("total_retenidos"):
        tot_datos.append([Paragraph("(−) Impuestos retenidos", e["normal"]),
                          Paragraph(_moneda(factura.get("total_retenidos")), e["num"])])
    tot_datos.append([Paragraph("<b>Total</b>", e["negrita"]),
                      Paragraph(f"<b>{_moneda(factura.get('total'))}</b>",
                                ParagraphStyle("tot", parent=e["num_b"], fontSize=12, textColor=AZUL))])
    tt = Table(tot_datos, colWidths=[110 * mm, 60 * mm])
    tt.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, AZUL),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    el.append(tt)
    el.append(Paragraph(f"<i>({numero_a_letras(factura.get('total'))})</i>",
                        ParagraphStyle("letras", parent=e["chico"], alignment=2,
                                       spaceBefore=1 * mm, spaceAfter=4 * mm)))
    return el


def generar_pdf(factura: dict[str, Any]) -> bytes:
    """Genera el PDF de representación impresa. Devuelve los bytes del PDF."""
    e = _estilos()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=10 * mm, bottomMargin=12 * mm)

    elementos: list = [
        _encabezado(factura, e),
        Spacer(1, 4 * mm),
        _bloque_fiscal(factura, e),
        Spacer(1, 3 * mm),
    ]

    if factura.get("tipo_comprobante") == "N":
        elementos += _seccion_nomina(factura, e)
    else:
        elementos += _seccion_factura_general(factura, e)

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
        Table([
            [Image(img_buf, width=32 * mm, height=32 * mm),
             [Paragraph("Verifica este comprobante en el portal del SAT "
                        "escaneando el código QR.", e["normal"]),
              Spacer(1, 2 * mm),
              Paragraph("Representación impresa del CFDI. El documento con "
                        "validez fiscal es el XML. El SAT no emite PDFs.", e["chico"])]]
        ], colWidths=[40 * mm, 130 * mm]),
    ]

    doc.build(elementos, onFirstPage=_pie, onLaterPages=_pie)
    return buf.getvalue()
