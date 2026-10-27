"""WP-EX1: X1 validation (contract 10 section 3) and the upload service."""
import pytest

from ingestion.config import ExtractConfig
from ingestion.errors import IngestError
from ingestion.validate import validate_file
from tests import files
from tests.conftest import META


def _code(exc_info) -> tuple[str, int]:
    return exc_info.value.code, exc_info.value.http_status


def test_reject_exe_renamed_pdf(tmp_path, k):
    fake = tmp_path / "a.pdf"
    fake.write_bytes(b"MZ\x90\x00" + b"\x00" * 200)          # a Windows executable header
    with pytest.raises(IngestError) as e:
        k.submit_document(fake, META)
    assert _code(e) == ("UNSUPPORTED_TYPE", 422)


def test_duplicate_is_409(tmp_path, k):
    pdf = files.text_pdf(tmp_path / "p.pdf", [["Per diem rules for Mumbai and other cities in the policy."]])
    first = k.submit_document(pdf, META)
    with pytest.raises(IngestError) as e:
        k.submit_document(pdf, META)
    assert _code(e) == ("DUPLICATE_DOCUMENT", 409)
    assert e.value.detail["document_id"] == first["document_id"]


def test_extension_not_allowed(tmp_path, cfg):
    f = tmp_path / "a.exe"
    f.write_bytes(b"MZ")
    with pytest.raises(IngestError) as e:
        validate_file(f, "a.exe", META, cfg)
    assert _code(e) == ("UNSUPPORTED_TYPE", 422)


def test_file_too_large(tmp_path, cfg):
    pdf = files.text_pdf(tmp_path / "p.pdf", [["text"]])
    small = ExtractConfig(data_dir=cfg.data_dir, max_mb=0)
    with pytest.raises(IngestError) as e:
        validate_file(pdf, "p.pdf", META, small)
    assert _code(e) == ("FILE_TOO_LARGE", 422)


def test_invalid_metadata_lists_fields(tmp_path, cfg):
    pdf = files.text_pdf(tmp_path / "p.pdf", [["text"]])
    with pytest.raises(IngestError) as e:
        validate_file(pdf, "p.pdf", {"title": "T", "version": "1.0", "effective_date": "01/04/2026"}, cfg)
    assert _code(e) == ("INVALID_METADATA", 422)
    assert set(e.value.detail["fields"]) == {"category", "effective_date"}


def test_doc_key_defaults_to_title_slug(tmp_path, cfg):
    pdf = files.text_pdf(tmp_path / "p.pdf", [["text"]])
    valid = validate_file(pdf, "p.pdf", META, cfg)
    assert valid.meta["doc_key"] == "travel-and-expense-policy"


def test_encrypted_pdf_refused(tmp_path, cfg):
    plain = files.text_pdf(tmp_path / "p.pdf", [["secret text"]])
    enc = files.encrypted_pdf(tmp_path / "e.pdf", plain)
    with pytest.raises(IngestError) as e:
        validate_file(enc, "e.pdf", META, cfg)
    assert _code(e) == ("ENCRYPTED_PDF", 422)


def test_corrupt_pdf(tmp_path, cfg):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.7\n this is not a real pdf body")
    with pytest.raises(IngestError) as e:
        validate_file(bad, "bad.pdf", META, cfg)
    assert _code(e) == ("CORRUPT_FILE", 422)


def test_too_many_ocr_pages(tmp_path, cfg):
    scan = files.scanned_pdf(tmp_path / "s.pdf", pages=3)
    limited = ExtractConfig(data_dir=cfg.data_dir, max_ocr_pages=2)
    with pytest.raises(IngestError) as e:
        validate_file(scan, "s.pdf", META, limited)
    assert _code(e) == ("TOO_MANY_PAGES", 422)


def test_docx_and_images_accepted(tmp_path, cfg):
    assert validate_file(files.docx_file(tmp_path / "a.docx"), "a.docx", META, cfg).file_type == "docx"
    assert validate_file(files.png_photo(tmp_path / "n.png"), "n.png", META, cfg).file_type == "png"
    jpg = files.png_photo(tmp_path / "n.png", rotate_exif=True)
    assert validate_file(jpg, "n.jpeg", META, cfg).file_type == "jpg"


def test_zip_named_docx_refused(tmp_path, cfg):
    import zipfile
    z = tmp_path / "a.docx"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("hello.txt", "not a word file")
    with pytest.raises(IngestError) as e:
        validate_file(z, "a.docx", META, cfg)
    assert _code(e) == ("UNSUPPORTED_TYPE", 422)


def test_deleted_document_can_be_uploaded_again(tmp_path, k):
    pdf = files.text_pdf(tmp_path / "p.pdf", [["Per diem rules for Mumbai and other cities in the policy."]])
    first = k.submit_document(pdf, META)
    k.delete_document(first["document_id"])
    again = k.submit_document(pdf, META)
    assert again["document_id"] == first["document_id"]
    assert k.store.get_document(first["document_id"])["status"] == "INDEXED"
