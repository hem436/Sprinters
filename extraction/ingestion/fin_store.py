"""Contract 14 section 3: financial tables in `knowledge.db` and the view Sinngam's facts tools read.

Values are integers in the base unit (rupees; percent in basis points), and the printed text is kept too.
"""

FIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS report (
  report_id     TEXT PRIMARY KEY,                 -- e.g. R-A-25
  company       TEXT NOT NULL,
  report_type   TEXT NOT NULL CHECK (report_type IN ('ANNUAL','QUARTERLY')),
  fiscal_year   TEXT NOT NULL,                    -- FY2024-25
  published_on  TEXT NOT NULL,                    -- ISO date; the newest report wins
  document_id   TEXT REFERENCES document (document_id)
);

CREATE TABLE IF NOT EXISTS fin_table (
  table_id      TEXT PRIMARY KEY,
  report_id     TEXT NOT NULL REFERENCES report (report_id),
  pages         TEXT NOT NULL,                    -- JSON list, two pages when a table continues (F2)
  statement     TEXT NOT NULL CHECK (statement IN ('PL','BS','CF','SEGMENT','OTHER')),
  basis         TEXT NOT NULL CHECK (basis IN ('CONSOLIDATED','STANDALONE')),
  currency      TEXT NOT NULL DEFAULT 'INR',
  scale         INTEGER NOT NULL,                 -- 1, 1000, 100000, 1000000, 10000000
  unit_printed  TEXT NOT NULL DEFAULT '',
  caption       TEXT NOT NULL DEFAULT '',
  checks_passed INTEGER NOT NULL DEFAULT 0,
  checks_json   TEXT NOT NULL DEFAULT '[]',       -- which F7 checks failed and why
  status        TEXT NOT NULL CHECK (status IN ('NEEDS_REVIEW','APPROVED','REJECTED')),
  reviewed_by   TEXT,
  reviewed_at   TEXT,
  review_comment TEXT
);

CREATE TABLE IF NOT EXISTS fin_fact (
  fact_id       TEXT PRIMARY KEY,
  table_id      TEXT NOT NULL REFERENCES fin_table (table_id),
  report_id     TEXT NOT NULL REFERENCES report (report_id),
  company       TEXT NOT NULL,
  period        TEXT NOT NULL,                    -- FY2024-25, FY2024-25 Q2
  basis         TEXT NOT NULL,
  metric        TEXT NOT NULL DEFAULT '',         -- empty until mapped (F6); no tool uses an empty metric
  segment       TEXT NOT NULL DEFAULT '',
  line_label    TEXT NOT NULL,                    -- as printed
  value_kind    TEXT NOT NULL CHECK (value_kind IN ('AMOUNT','PERCENT','COUNT')),
  value_num     INTEGER NOT NULL,                 -- base unit
  value_printed TEXT NOT NULL,
  page          INTEGER NOT NULL,
  row_no        INTEGER NOT NULL,
  col_no        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fact_lookup ON fin_fact (company, metric, period, basis);

CREATE TABLE IF NOT EXISTS metric_map (
  line_label    TEXT PRIMARY KEY,                 -- normalised: lower case, single spaces
  metric        TEXT NOT NULL,
  proposed_by   TEXT NOT NULL CHECK (proposed_by IN ('DICTIONARY','LLM','ADMIN')),
  approved_by   TEXT,                             -- NULL = waiting for approval
  approved_on   TEXT
);

-- Only APPROVED tables and mapped metrics. For each company, metric, period, basis and segment the newest report
-- wins; restated = 1 when reports disagree, with the older value for the "was ..." text and its citation.
CREATE VIEW IF NOT EXISTS v_fact_current AS
WITH usable AS (
  SELECT f.*, r.published_on
  FROM fin_fact f
  JOIN fin_table t ON t.table_id = f.table_id
  JOIN report r ON r.report_id = f.report_id
  WHERE t.status = 'APPROVED' AND f.metric != ''
),
ranked AS (
  SELECT u.*,
    ROW_NUMBER() OVER w AS rn,
    MIN(value_num) OVER p AS min_value,
    MAX(value_num) OVER p AS max_value,
    LEAD(value_num) OVER w AS prev_value_num,
    LEAD(value_printed) OVER w AS prev_value_printed,
    LEAD(report_id) OVER w AS prev_report_id,
    LEAD(page) OVER w AS prev_page
  FROM usable u
  WINDOW p AS (PARTITION BY company, metric, period, basis, segment),
         w AS (PARTITION BY company, metric, period, basis, segment ORDER BY published_on DESC, report_id DESC)
)
SELECT fact_id, table_id, report_id, company, period, basis, metric, segment, line_label, value_kind, value_num,
       value_printed, page, row_no, col_no, published_on,
       CASE WHEN min_value != max_value THEN 1 ELSE 0 END AS restated,
       CASE WHEN min_value != max_value THEN prev_value_num END AS prev_value_num,
       CASE WHEN min_value != max_value THEN prev_value_printed END AS prev_value_printed,
       CASE WHEN min_value != max_value THEN prev_report_id END AS prev_report_id,
       CASE WHEN min_value != max_value THEN prev_page END AS prev_page
FROM ranked
WHERE rn = 1;
"""
