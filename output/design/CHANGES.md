# Design changes

The contracts were frozen at the design review. Every later change is one entry here, newest first, written
with the `design-change` skill. The panel may ask why we changed something: this file is the answer.

| Id | Time | Contract and version | What changed | Why (evidence) | Parts affected (owners told) | Agreed by |
|---|---|---|---|---|---|---|
| C-01 | 2026-10-27 | 14 v1.0 → v1.1 | `value_kind` PER_SHARE (EPS in paise); `fin_fact.label_norm`; `fin_table` gets `unit_printed`, `caption`, `source`, `rows_json`, `checks_json` and review columns; `v_fact_current` gets `prev_*` columns | EPS ₹45.67 cannot be an integer number of rupees; the review screen needs the rows and the failed checks; the "was ₹10,000 crore" text needs the older value and page | Sinngam (facts tools read `value_kind` and `prev_*`), Hemant (table review screen) | Myank; Sinngam and Hemant to confirm |
| C-02 | 2026-10-27 | 14 v1.1, 05 | `POST /documents` takes optional `company`, `report_type`, `fiscal_year`; `company` turns on fact extraction | the `report` row needs a company and a year, and the upload form had no field for them | Sinngam (route), Hemant (upload form) | Myank; Sinngam and Hemant to confirm |
| C-03 | 2026-10-27 | 14 v1.1 F1, F7 | F7(a) uses the shortest run of rows or subtotals above a total; a total with no rows of its own is unverified, not failed; basis or unit not found, unparsable numbers, unmapped labels and vision-read tables also go to review | real statements have subtotals ("Total assets") and single total lines ("Total tax expense"); a plain sum of the rows above gave false failures | Arka (eval cases on review) | Myank |
| C-04 | 2026-10-27 | 10 X5, 09 | OCR model `gemini-3.5-flash` with thinking level `low` and a 60 s timeout, instead of `gemini-flash-latest` | the alias timed out (504 after 45 s) on a one-line page; the fixed name took 3 to 20 s; a fixed name keeps eval runs repeatable | Arka (eval timing), Sinngam (price table) | Myank |
