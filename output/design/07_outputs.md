<!-- Contract 07. Owner: P3. Status: DRAFT until the design review, then FROZEN v1.0.
     After freezing, change only through the design-change skill: an entry in CHANGES.md and a version bump. -->
# 07 Output files

Version: 1.0 · Status: DRAFT · Owner: P3 (P1 for extraction quality) · Case section(s): 9, 10, 12

All files are written by scripts, never by hand, and are committed at the end of the day.

### evals/eval_set.jsonl (input, hand-written)

One JSON object per line, schema in contract 11 section 7. About 25 cases.

### output/eval_results_A.csv and output/eval_results_B.csv

| # | Column | Type / format | Rule |
|---|---|---|---|
| 1 | case_id | text | from the eval set |
| 2 | scenario | text | |
| 3 | query_id | text | opens the drill-down |
| 4 | route / expected_route | text | |
| 5 | outcome, reason_code | text | contract 11 section 5 |
| 6 | behavior_match | 0 or 1 | |
| 7 | hit_at_5 | 0 or 1, empty if no expected evidence | |
| 8 | recall_at_5 | 2 decimals | |
| 9 | reciprocal_rank | 3 decimals | |
| 10 | answer_criteria_pass | 0 or 1 | |
| 11 | citations_valid_ratio | 2 decimals | |
| 12 | grounding_score | 2 decimals | |
| 13 | faithfulness, answer_correctness | 2 decimals, empty if the judge failed | |
| 14 | latency_ms | integer | |
| 15 | tokens_in, tokens_out | integer | |
| 16 | cost_usd | 6 decimals | empty if price not set |

Row order: case_id ascending.

### output/eval_comparison.csv

One row per measure: `measure, config_A, config_B, difference, better`. Measures: hit@5, recall@5, MRR,
route accuracy, behaviour match, answer criteria, citation validity, grounding, faithfulness, answer correctness,
latency p50, latency p95, tokens per query, cost per query.

### output/extraction_quality.csv (P1)

| # | Column | Rule |
|---|---|---|
| 1 | gold_page | file name in `evals/extraction_gold/` |
| 2 | kind | financial_text, financial_scanned, scanned, handwriting, garbled |
| 3 | expected_class / actual_class | X3 |
| 4 | method | |
| 5 | cer, wer | 3 decimals |
| 6 | numeric_recall | 3 decimals, empty if no numbers |
| 7 | table_cell_accuracy | 3 decimals, empty if no table |
| 8 | quality_score, needs_review | from X6 / X7 |
| 9 | ocr_tokens_in, ocr_tokens_out, ocr_cost_usd | |

### output/evaluation_report.md

What changed between A and B, the comparison table, latency and cost impact, 3 failure cases with query ids,
extraction quality summary, and our recommended configuration (case section 10).

### output/design/

These contracts, the architecture diagram, and `design_document.md` built by `team/build_design_doc.py`.
