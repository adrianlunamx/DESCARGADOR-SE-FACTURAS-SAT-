"""Pruebas del generador de PDF (representación impresa del CFDI).

Ejecutar desde la carpeta app/:  pytest tests/ -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from parser import parse_cfdi  # noqa: E402
from pdf_gen import generar_pdf, numero_a_letras  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _usar_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "XML_DIR", str(tmp_path / "xml"))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "facturas.db"))
    db.init_db()


def _leer(nombre):
    with open(os.path.join(FIXTURES, nombre), "rb") as f:
        return f.read()


def test_pdf_nomina_con_detalle_completo(tmp_path, monkeypatch):
    _usar_tmp(tmp_path, monkeypatch)
    xml = _leer("recibo_nomina.xml")
    datos = parse_cfdi(xml)
    db.guardar_factura(datos, "recibida", xml)
    f = db.obtener_factura(datos["uuid"])
    assert f["nomina_detalle"] is not None

    pdf = generar_pdf(f)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 4000  # recibo con tablas de detalle, no un PDF vacío


def test_numero_a_letras():
    assert numero_a_letras(14300.00) == "Catorce mil trescientos pesos 00/100 M.N."
    assert numero_a_letras(11600.50) == "Once mil seiscientos pesos 50/100 M.N."
    assert numero_a_letras(100.00) == "Cien pesos 00/100 M.N."
    assert numero_a_letras(1000000.00) == "Un millón pesos 00/100 M.N."
    assert numero_a_letras(None) == "—"


def test_pdf_factura_general(tmp_path, monkeypatch):
    _usar_tmp(tmp_path, monkeypatch)
    xml = _leer("factura_ingreso.xml")
    datos = parse_cfdi(xml)
    db.guardar_factura(datos, "recibida", xml)
    f = db.obtener_factura(datos["uuid"])

    pdf = generar_pdf(f)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 3000
