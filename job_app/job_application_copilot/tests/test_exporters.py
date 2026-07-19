"""Tests for one-click PDF / DOCX export of drafted documents.

Generates a real PDF and DOCX from sample cover-letter text and reads them back
to assert they are valid, non-empty, and contain the expected content.
"""
import io

from backend.pipeline.exporters import safe_filename, to_docx_bytes, to_pdf_bytes

SAMPLE = (
    "Dear Hiring Manager,\n\n"
    "I am excited to apply for the Supply Chain Analyst role at Ferrero.\n"
    "My background in logistics and SAP makes me a strong fit.\n\n"
    "Kind regards,\nAda Lovelace"
)


def test_docx_is_valid_and_contains_text():
    data = to_docx_bytes(SAMPLE, title="Cover Letter")
    assert isinstance(data, bytes) and len(data) > 500
    # A .docx is a zip archive; the PK signature proves a real Office file.
    assert data[:2] == b"PK"

    from docx import Document
    doc = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Supply Chain Analyst role at Ferrero" in text
    assert "Ada Lovelace" in text
    assert "Cover Letter" in text  # the title heading


def test_pdf_is_valid_and_contains_text():
    data = to_pdf_bytes(SAMPLE, title="Cover Letter")
    assert isinstance(data, bytes) and len(data) > 500
    assert data[:4] == b"%PDF"  # PDF magic number

    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) >= 1
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Ferrero" in extracted
    assert "Ada Lovelace" in extracted


def test_export_handles_empty_and_special_chars():
    # Empty text must still produce a valid (non-crashing) file.
    assert to_docx_bytes("", title="")[:2] == b"PK"
    assert to_pdf_bytes("", title="")[:4] == b"%PDF"
    # Reportlab markup chars must be escaped, not crash the build.
    tricky = "Cost < 5 & profit > 3 <b>bold?</b>"
    assert to_pdf_bytes(tricky, title="T")[:4] == b"%PDF"


def test_safe_filename_sanitises():
    assert safe_filename("Cover Letter", "Ferrero UK/Ltd") == "Cover_Letter_Ferrero_UK_Ltd"
    assert safe_filename("") == "document"
