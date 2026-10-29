"""Text extraction from DOCX and PDF files."""
import io
import re

REF_HEADING = re.compile(r"^\s*(references|bibliography|works cited)\s*:?\s*$", re.I | re.M)


def _docx_text(data: bytes) -> str:
    import docx
    d = docx.Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            for c in row.cells:
                parts.append(c.text)
    return "\n".join(parts)


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    return "\n".join((pg.extract_text() or "") for pg in r.pages)


def extract_text(filename: str, data: bytes) -> str:
    """Return plain text for a .docx or .pdf upload."""
    low = filename.lower()
    if low.endswith(".docx"):
        return _docx_text(data)
    if low.endswith(".pdf"):
        return _pdf_text(data)
    raise ValueError(f"Unsupported file type: {filename} (use .docx or .pdf)")


def strip_references(text: str) -> str:
    """Cut the text at the last 'References' style heading (if it is in the back half)."""
    matches = list(REF_HEADING.finditer(text))
    if matches:
        m = matches[-1]
        if m.start() > len(text) * 0.4:
            return text[: m.start()]
    return text
