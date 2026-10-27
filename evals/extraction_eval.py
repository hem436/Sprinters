"""Extraction quality check (contract 10 section 10). Writes output/extraction_quality.csv.

    cd extraction && .venv/bin/python ../evals/extraction_eval.py [--no-ocr]

The code lives in extraction/ingestion/extraction_eval.py, next to the pipeline it measures.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "extraction"))

from ingestion.extraction_eval import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
