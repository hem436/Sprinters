"""Extraction quality check (contract 10 section 10, contract 07): how good is the text we extract?

    cd extraction && .venv/bin/python ../evals/extraction_eval.py            # real OCR (needs GEMINI_API_KEY)
    cd extraction && .venv/bin/python ../evals/extraction_eval.py --no-ocr   # text-layer pages only, free

Reads evals/extraction_gold/gold.yaml, extracts each gold page with the real pipeline (X3 class, X4 text and tables,
X5 OCR, X6 quality), compares it with the hand-typed gold, and writes output/extraction_quality.csv.

| Measure             | Definition                                                                                |
| cer                 | character edit distance / gold length, after collapsing whitespace and Markdown marks     |
| wer                 | word edit distance / gold words                                                           |
| numeric_recall      | gold numbers (as printed) found exactly in the output / all gold numbers                  |
| table_cell_accuracy | cells equal to the gold .csv, matched by row and column / gold cells                       |
| route correct       | actual_class == expected_class                                                            |

We report the real numbers, also when handwriting scores badly: the review gate (X7) is what keeps a bad page out.
"""
import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[2]
GOLD_DIR = ROOT / "evals" / "extraction_gold"
DOCS_DIR = ROOT / "demo" / "documents"
OUT = ROOT / "output" / "extraction_quality.csv"

COLUMNS = ["gold_page", "kind", "expected_class", "actual_class", "method", "cer", "wer", "numeric_recall",
           "table_cell_accuracy", "quality_score", "needs_review", "ocr_tokens_in", "ocr_tokens_out", "ocr_cost_usd",
           "stand_in"]

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}.*$")


# ---- measures ----------------------------------------------------------------------------------------------------------

def normalise(text: str) -> str:
    """The same view of gold and output: no Markdown table bars, separator rows, heading marks or bullets; NFKC;
    single spaces. Numbers and words are not changed."""
    lines = []
    for line in unicodedata.normalize("NFKC", text or "").splitlines():
        if _SEPARATOR.match(line):
            continue
        line = line.replace("|", " ")
        line = re.sub(r"^\s*(#{1,6}|[•▪●*-])\s+", "", line)
        lines.append(line)
    return " ".join(" ".join(lines).split())


def edit_distance(a: list | str, b: list | str) -> int:
    """Levenshtein distance, one row at a time."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(gold: str, out: str) -> float:
    g, o = normalise(gold), normalise(out)
    return edit_distance(g, o) / max(len(g), 1)


def wer(gold: str, out: str) -> float:
    g, o = normalise(gold).split(), normalise(out).split()
    return edit_distance(g, o) / max(len(g), 1)


def numbers(text: str) -> list[str]:
    return [m.group(0).rstrip(",.") for m in _NUMBER.finditer(unicodedata.normalize("NFKC", text or ""))]


def numeric_recall(gold: str, out: str) -> float | None:
    """Each gold number counts once per time it is printed; it is found when the output prints it the same way."""
    wanted = numbers(gold)
    if not wanted:
        return None
    have: dict[str, int] = {}
    for n in numbers(out):
        have[n] = have.get(n, 0) + 1
    found = 0
    for n in wanted:
        if have.get(n, 0) > 0:
            have[n] -= 1
            found += 1
    return found / len(wanted)


def _cell(c: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(c or "")).replace("\\|", "|").split())


def table_cell_accuracy(gold_rows: list[list[str]], tables: list[list[list[str]]]) -> float | None:
    """Cells equal to the gold, by row and column, in the best-matching extracted table / all gold cells."""
    total = sum(len(r) for r in gold_rows)
    if not total:
        return None
    best = 0
    for rows in tables:
        hits = sum(1 for i, grow in enumerate(gold_rows) for j, g in enumerate(grow)
                   if i < len(rows) and j < len(rows[i]) and _cell(rows[i][j]) == _cell(g))
        best = max(best, hits)
    return best / total


# ---- the run -----------------------------------------------------------------------------------------------------------

def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def evaluate(gold_dir: Path, docs_dir: Path, cfg, ocr, use_ocr: bool = True) -> list[dict]:
    from ingestion.pipeline import extract_pages
    from ingestion.quality import score_page

    entries = yaml.safe_load((gold_dir / "gold.yaml").read_text(encoding="utf-8"))
    k = SimpleNamespace(cfg=cfg, ocr=ocr)
    cache: dict[str, list] = {}
    rows = []
    for e in entries:
        path = docs_dir / e["file"]
        ext = path.suffix.lower().lstrip(".")
        file_type = {"jpeg": "jpg", "tiff": "tif"}.get(ext, ext)
        if not use_ocr and (file_type in ("png", "jpg", "tif", "webp") or e["expected_class"] in ("SCANNED", "GARBLED")):
            continue
        if e["file"] not in cache:
            cache[e["file"]] = extract_pages(path, file_type, k)
            for p in cache[e["file"]]:
                score_page(p, cfg)
        page = next((p for p in cache[e["file"]] if p.page == e["page"]), None)
        gold_text = (gold_dir / f"{e['name']}.txt").read_text(encoding="utf-8")
        gold_csv = gold_dir / f"{e['name']}.csv"
        gold_table = list(csv.reader(gold_csv.open(encoding="utf-8"))) if gold_csv.exists() else None
        out = page.text if page else ""
        tables = [b.rows for b in page.blocks if b.type == "table"] if page else []
        usage = page.ocr if page else None
        rows.append({
            "gold_page": f"{e['name']}.txt", "kind": e["kind"], "expected_class": e["expected_class"],
            "actual_class": page.page_class if page else "MISSING", "method": page.method if page else "",
            "cer": cer(gold_text, out), "wer": wer(gold_text, out), "numeric_recall": numeric_recall(gold_text, out),
            "table_cell_accuracy": table_cell_accuracy(gold_table, tables) if gold_table else None,
            "quality_score": page.quality if page else None,
            "needs_review": (page.status == "NEEDS_REVIEW") if page else None,
            "ocr_tokens_in": usage.input_tokens if usage else None,
            "ocr_tokens_out": usage.output_tokens if usage else None,
            "ocr_cost_usd": usage.cost_usd if usage else None,
            "stand_in": bool(e.get("stand_in", False)),
        })
    return rows


def write_csv(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([_fmt(r[c]) for c in COLUMNS])


def summary(rows: list[dict]) -> str:
    lines = [f"{'gold page':28} {'class':16} {'cer':>6} {'wer':>6} {'num':>6} {'cells':>6} {'qual':>5}  review"]
    for r in rows:
        route = r["actual_class"] + ("" if r["actual_class"] == r["expected_class"] else f" (want {r['expected_class']})")
        lines.append(f"{r['gold_page']:28} {route:16} {_fmt(r['cer']):>6} {_fmt(r['wer']):>6} "
                     f"{_fmt(r['numeric_recall']):>6} {_fmt(r['table_cell_accuracy']):>6} "
                     f"{_fmt(r['quality_score']):>5}  {r['needs_review']}{'  (stand-in)' if r['stand_in'] else ''}")
    nums = [r["numeric_recall"] for r in rows if r["numeric_recall"] is not None]
    routes = sum(r["actual_class"] == r["expected_class"] for r in rows)
    lines.append(f"route correct {routes}/{len(rows)}; numeric recall (mean) "
                 f"{sum(nums) / len(nums):.3f}" if nums else f"route correct {routes}/{len(rows)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Extraction quality check against the gold set")
    p.add_argument("--no-ocr", action="store_true", help="skip pages that need OCR (no model calls, no cost)")
    p.add_argument("--gold", type=Path, default=GOLD_DIR)
    p.add_argument("--docs", type=Path, default=DOCS_DIR)
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args(argv)

    from ingestion.config import load_config
    cfg = load_config()
    ocr = None
    if not args.no_ocr:
        from ingestion.ocr import GeminiOCR
        ocr = GeminiOCR(cfg)
    rows = evaluate(args.gold, args.docs, cfg, ocr, use_ocr=not args.no_ocr)
    write_csv(rows, args.out)
    print(summary(rows))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
