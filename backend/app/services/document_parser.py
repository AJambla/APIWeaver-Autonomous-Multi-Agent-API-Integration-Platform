"""Text extraction from PDF, HTML, and Markdown documents."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_text(content: bytes, filename: str, content_type: str | None = None) -> str:
    """Extract text from document content based on file type.

    Args:
        content: Raw document bytes
        filename: Original filename (used to determine format)
        content_type: Optional MIME type

    Returns:
        Extracted text content, or UTF-8 decode fallback on failure
    """
    suffix = Path(filename).suffix.lower()

    try:
        if suffix == ".pdf":
            return _extract_pdf(content)
        elif suffix in {".html", ".htm"}:
            return _extract_html(content)
        elif suffix in {".md", ".markdown"}:
            return _extract_markdown(content)
        elif suffix in {".txt", ".text"}:
            return content.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning(
            "text_extraction_failed, filename=%s, suffix=%s, error=%s",
            filename,
            suffix,
            str(exc),
        )

    # Fallback: try UTF-8 decode
    try:
        return content.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_pdf(content: bytes) -> str:
    """Extract text from PDF using pypdf."""
    from io import BytesIO

    try:
        import pypdf

        pdf_file = BytesIO(content)
        reader = pypdf.PdfReader(pdf_file)
        text_parts = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        return "\n".join(text_parts)
    except Exception as exc:
        logger.warning("pdf_extraction_failed, error=%s", str(exc))
        raise


def _extract_html(content: bytes) -> str:
    """Extract text from HTML using BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup

        html = content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")

        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()

        text = soup.get_text(separator="\n", strip=True)
        return text
    except Exception as exc:
        logger.warning("html_extraction_failed, error=%s", str(exc))
        raise


def _extract_markdown(content: bytes) -> str:
    """Extract text from Markdown (returns raw content as text)."""
    try:
        return content.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("markdown_extraction_failed, error=%s", str(exc))
        raise