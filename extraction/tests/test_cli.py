"""The command line (`python -m ingestion`) with the fake parts."""
import yaml

from ingestion import __main__ as cli
from tests import files


def test_cli_ingest_manifest_list_search(tmp_path, k, monkeypatch, capsys):
    monkeypatch.setattr("ingestion.service.build", lambda inline=False: k)
    files.table_pdf(tmp_path / "report.pdf")
    files.docx_file(tmp_path / "sop.docx")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.safe_dump([
        {"file": "report.pdf", "title": "Company A Annual Report", "category": "Finance", "version": "FY2024-25",
         "effective_date": "2025-06-01"},
        {"file": "sop.docx", "title": "IT Security SOP", "category": "IT", "version": "1.0",
         "effective_date": "2026-01-01", "doc_key": "it-sop"},
        {"file": "sop.docx", "title": "IT Security SOP copy", "category": "IT", "version": "1.0",
         "effective_date": "2026-01-01"},
    ]))
    assert cli.main(["ingest", str(manifest)]) == 0          # a duplicate is reported, not a failure
    out = capsys.readouterr().out
    assert out.count("INDEXED") == 2 and "DUPLICATE_DOCUMENT" in out

    assert cli.main(["list"]) == 0
    assert "IT Security SOP" in capsys.readouterr().out
    assert cli.main(["search", "POL-HR-014", "--bm25"]) == 0
    assert "2.1 Encryption" in capsys.readouterr().out
