"""X1 Validate (contract 10 section 3, FR-01): type by extension and first bytes, size, opens, not encrypted,
not a duplicate, metadata present, page limits. Every refusal is an IngestError with the contract's code.
"""
import hashlib
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ingestion import errors
from ingestion.config import ExtractConfig

IMAGE_TYPES = {"png", "jpg", "jpeg", "tif", "tiff", "webp"}
REQUIRED_META = ("title", "category", "version", "effective_date")


@dataclass(frozen=True)
class ValidFile:
    file_type: str           # normalised: pdf, docx, txt, png, jpg, tif, webp
    size_bytes: int
    content_hash: str        # SHA-256 of the bytes
    page_count: int          # PDF pages; 1 for an image; 0 for DOCX/TXT (sections are counted at extraction)
    meta: dict               # title, category, version, effective_date, doc_key


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "document"


def check_metadata(meta: dict) -> dict:
    """Required fields present; effective_date is an ISO date; doc_key defaults to a slug of the title."""
    problems: dict[str, str] = {}
    clean = {k: (str(meta.get(k) or "").strip()) for k in (*REQUIRED_META, "doc_key")}
    for key in REQUIRED_META:
        if not clean[key]:
            problems[key] = "required"
    if clean["effective_date"]:
        try:
            clean["effective_date"] = date.fromisoformat(clean["effective_date"]).isoformat()
        except ValueError:
            problems["effective_date"] = "must be an ISO date, e.g. 2026-04-01"
    extra = check_report_fields(meta, problems)
    if problems:
        raise errors.invalid_metadata(problems)
    clean["doc_key"] = slug(clean["doc_key"] or clean["title"])
    if extra:
        clean["extra"] = extra
    return clean


def check_report_fields(meta: dict, problems: dict[str, str]) -> dict:
    """Optional fields for a financial report (contract 14): `company` turns on fact extraction; `report_type`
    ANNUAL (default) or QUARTERLY; `fiscal_year` like FY2024-25 (default: the year before the effective date)."""
    company = str(meta.get("company") or "").strip()
    report_type = str(meta.get("report_type") or "").strip().upper()
    fiscal_year = str(meta.get("fiscal_year") or "").strip().upper()
    if not company:
        if report_type or fiscal_year:
            problems["company"] = "required when report_type or fiscal_year is given"
        return {}
    if report_type and report_type not in ("ANNUAL", "QUARTERLY"):
        problems["report_type"] = "must be ANNUAL or QUARTERLY"
    if fiscal_year and not re.fullmatch(r"FY\d{4}-\d{2}", fiscal_year):
        problems["fiscal_year"] = "must look like FY2024-25"
    return {"company": company, "report_type": report_type or "ANNUAL", "fiscal_year": fiscal_year or None}


def sniff_type(path: Path, ext: str) -> str:
    """The extension must be allowed AND the first bytes must match it. Returns the normalised type."""
    with open(path, "rb") as f:
        head = f.read(16)
    ok = {
        "pdf": head.startswith(b"%PDF"),
        "png": head.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": head.startswith(b"\xff\xd8"),
        "tif": head[:4] in (b"II*\x00", b"MM\x00*"),
        "webp": head[:4] == b"RIFF" and head[8:12] == b"WEBP",
        "docx": head.startswith(b"PK\x03\x04") and _is_docx(path),
        "txt": _looks_like_text(path),
    }
    norm = {"jpeg": "jpg", "tiff": "tif"}.get(ext, ext)
    if not ok.get(norm, False):
        raise errors.unsupported_type(f"The file content is not a valid .{ext} file.")
    return norm


def _is_docx(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as z:
            return "word/document.xml" in z.namelist()
    except zipfile.BadZipFile:
        return False


def _looks_like_text(path: Path) -> bool:
    """Plain text: no NUL bytes in the first 64 KB, and it decodes as UTF-8 or cp1252."""
    with open(path, "rb") as f:
        sample = f.read(65536)
    if b"\x00" in sample:
        return False
    import codecs
    for enc in ("utf-8", "cp1252"):
        try:
            # incremental: a character cut in two at the 64 KB boundary is not an error (review B7)
            codecs.getincrementaldecoder(enc)().decode(sample, final=False)
            return True
        except UnicodeDecodeError:
            continue
    return False


def _pdf_pages(path: Path, cfg: ExtractConfig) -> int:
    """Opens, not encrypted, at least 1 page, within the page and OCR-page limits."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            # an empty user password is common for "protected" PDFs that open without asking; still refuse
            raise errors.encrypted_pdf()
        pages = len(reader.pages)
    except errors.IngestError:
        raise
    except (PdfReadError, Exception) as e:  # pypdf raises several types on a broken file
        raise errors.corrupt_file(f"The PDF could not be opened: {str(e)[:120]}") from e
    if pages < 1:
        raise errors.corrupt_file("The PDF has no pages.")
    if pages > cfg.max_pages:
        raise errors.too_many_pages(f"The PDF has {pages} pages; the limit is {cfg.max_pages}.")
    needs_ocr = _pages_without_text(path)
    if needs_ocr > cfg.max_ocr_pages:
        raise errors.too_many_pages(
            f"{needs_ocr} pages have no text layer and need OCR; the limit is {cfg.max_ocr_pages}.")
    return pages


def _pages_without_text(path: Path, min_chars: int = 80) -> int:
    """A cheap count of pages that will need OCR (fewer than 80 text characters), with pdfium."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    try:
        count = 0
        for i in range(len(doc)):
            page = doc[i]
            text_page = page.get_textpage()
            try:
                if len(text_page.get_text_range().strip()) < min_chars:
                    count += 1
            finally:
                text_page.close()
                page.close()
        return count
    finally:
        doc.close()


def _image_opens(path: Path) -> None:
    from PIL import Image

    try:
        with Image.open(path) as img:
            img.verify()
    except Exception as e:
        raise errors.corrupt_file(f"The image could not be opened: {str(e)[:120]}") from e


def _docx_opens(path: Path) -> None:
    try:
        import docx
        docx.Document(str(path))
    except Exception as e:
        raise errors.corrupt_file(f"The Word file could not be opened: {str(e)[:120]}") from e


def validate_file(path: Path | str, file_name: str, meta: dict, cfg: ExtractConfig) -> ValidFile:
    """All X1 checks except the duplicate check, which needs the store (service.submit_document does it)."""
    path = Path(path)
    ext = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""
    if ext not in cfg.allowed_types:
        raise errors.unsupported_type(f"Files of type '.{ext}' are not accepted. "
                                      f"Accepted: {', '.join(cfg.allowed_types)}.")
    size = path.stat().st_size
    if size > cfg.max_mb * 1024 * 1024:
        raise errors.file_too_large(size / 1024 / 1024, cfg.max_mb)
    if size == 0:
        raise errors.corrupt_file("The file is empty.")
    file_type = sniff_type(path, ext)
    clean_meta = check_metadata(meta)

    if file_type == "pdf":
        pages = _pdf_pages(path, cfg)
    elif file_type in {"png", "jpg", "tif", "webp"}:
        _image_opens(path)
        pages = 1
    elif file_type == "docx":
        _docx_opens(path)
        pages = 0
    else:
        pages = 0
    return ValidFile(file_type, size, sha256_file(path), pages, clean_meta)
