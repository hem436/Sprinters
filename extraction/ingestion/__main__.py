"""Command line for the extraction part.

    python -m ingestion ingest demo/documents/manifest.yaml     # every file in the manifest (WP-EX8)
    python -m ingestion ingest policy.pdf --title "Travel Policy" --category "HR policy" --version 2.0 \
        --effective-date 2026-04-01
    python -m ingestion list
    python -m ingestion report doc_7f3a1c2d
    python -m ingestion search "POL-HR-014" --bm25
    python -m ingestion approve doc_7f3a1c2d 4 --admin myank

The manifest is a YAML list; each item has `file` (relative to the manifest) and the upload metadata
(title, category, version, effective_date, optional doc_key).
"""
import argparse
import json
import sys
from pathlib import Path

from ingestion.errors import IngestError

_built = []


def _knowledge():
    from ingestion.service import build
    k = build(inline=True)
    _built.append(k)
    return k


def _ingest(args) -> int:
    k = _knowledge()
    target = Path(args.target)
    if target.suffix in (".yaml", ".yml"):
        import yaml
        items = yaml.safe_load(target.read_text(encoding="utf-8")) or []
        jobs = [(target.parent / it.pop("file"), it) for it in items]
    else:
        meta = {"title": args.title, "category": args.category, "version": args.version,
                "effective_date": args.effective_date, "doc_key": args.doc_key}
        jobs = [(target, meta)]
    failed = 0
    for path, meta in jobs:
        try:
            out = k.submit_document(path, meta, uploaded_by="cli")
            report = k.get_report(out["document_id"]) or {}
            print(f"{out['document_id']}  {report.get('status', out['status']):15} chunks={report.get('chunks')} "
                  f"ocr_cost={report.get('ocr_cost_usd')}  {path.name}")
        except IngestError as e:
            failed += e.code != "DUPLICATE_DOCUMENT"
            print(f"{'-':13}  {e.code:15} {e.message}  {path.name}")
        except Exception as e:  # keep going: one bad file must not stop the corpus
            failed += 1
            print(f"{'-':13}  {'FAILED':15} {str(e)[:160]}  {path.name}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ingestion")
    sub = p.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest")
    ing.add_argument("target", help="a file, or a manifest .yaml")
    for opt in ("--title", "--category", "--version", "--effective-date", "--doc-key"):
        ing.add_argument(opt)
    sub.add_parser("list")
    rep = sub.add_parser("report")
    rep.add_argument("document_id")
    se = sub.add_parser("search")
    se.add_argument("query")
    se.add_argument("-k", type=int, default=5)
    se.add_argument("--bm25", action="store_true")
    for name in ("approve", "reject"):
        r = sub.add_parser(name)
        r.add_argument("document_id")
        r.add_argument("page", type=int)
        r.add_argument("--admin", default="cli")
    args = p.parse_args(argv)

    try:
        return _run(args)
    finally:
        for k in _built:                       # close local Qdrant before Python shuts down
            k.vector.client.close()


def _run(args) -> int:
    try:
        if args.cmd == "ingest":
            return _ingest(args)
        k = _knowledge()
        if args.cmd == "list":
            for d in k.list_documents():
                print(f"{d['document_id']}  {d['status']:15} v{d['version']:5} pages={d['page_count']} "
                      f"chunks={d['chunk_count']} review={d['pages_need_review']}  {d['title']}")
        elif args.cmd == "report":
            print(json.dumps(k.get_report(args.document_id), indent=2, ensure_ascii=False))
        elif args.cmd == "search":
            from ingestion.search import SearchService
            s = SearchService(k)
            hits = s.bm25_search(args.query, args.k) if args.bm25 else s.vector_search(args.query, args.k)
            chunks = {c.chunk_id: c for c in s.get_chunks([h.chunk_id for h in hits])}
            for h in hits:
                c = chunks[h.chunk_id]
                print(f"{h.rank}. {h.score:.3f}  {c.title} v{c.version} p.{c.page} | {c.section}\n   {c.text[:160]!r}")
        else:
            page = k.review_page(args.document_id, args.page, args.cmd.upper(), admin=args.admin)
            print(f"page {args.page}: {page['status']}")
        return 0
    except IngestError as e:
        print(f"{e.code}: {e.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
