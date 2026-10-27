"""Contract 14 section 3: financial tables in `knowledge.db` and the view Sinngam's facts tools read.

Values are integers in the base unit (rupees; percent in basis points; per-share amounts such as EPS in paise),
and the printed text is kept too.
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
  unit_percent  INTEGER NOT NULL DEFAULT 0,       -- 1 when the table is in % (from the unit line or a header)
  unit_printed  TEXT NOT NULL DEFAULT '',
  caption       TEXT NOT NULL DEFAULT '',
  source        TEXT NOT NULL DEFAULT 'text',     -- text (pdfplumber), ocr (page OCR), vision (table vision call)
  rows_json     TEXT NOT NULL DEFAULT '[]',       -- the table as read, shown beside the page image on review
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
  label_norm    TEXT NOT NULL DEFAULT '',         -- normalised, the key of metric_map (other writers may omit it)
  value_kind    TEXT NOT NULL CHECK (value_kind IN ('AMOUNT','PERCENT','COUNT','PER_SHARE')),
  value_num     INTEGER NOT NULL,                 -- base unit: rupees, basis points, count, paise per share
  value_printed TEXT NOT NULL,
  page          INTEGER NOT NULL,
  row_no        INTEGER NOT NULL,
  col_no        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fact_lookup ON fin_fact (company, metric, period, basis);
CREATE INDEX IF NOT EXISTS ix_fact_label ON fin_fact (label_norm);

CREATE TABLE IF NOT EXISTS metric_map (
  line_label    TEXT PRIMARY KEY,                 -- normalised: lower case, single spaces
  metric        TEXT NOT NULL,
  proposed_by   TEXT NOT NULL CHECK (proposed_by IN ('DICTIONARY','LLM','ADMIN')),
  approved_by   TEXT,                             -- NULL = waiting for approval
  approved_on   TEXT
);

-- Only APPROVED tables and mapped metrics. For each company, metric, period, basis and segment the newest report
-- wins. restated = 1 only when ANOTHER report gives a different value (a number printed twice in one report, in two
-- of its tables, is not a restatement: review D3); prev_* give the newest such other value, for the "was ..." text.
CREATE VIEW IF NOT EXISTS v_fact_current AS
WITH usable AS (
  SELECT f.*, r.published_on
  FROM fin_fact f
  JOIN fin_table t ON t.table_id = f.table_id
  JOIN report r ON r.report_id = f.report_id
  WHERE t.status = 'APPROVED' AND f.metric != ''
),
ranked AS (
  SELECT u.*, ROW_NUMBER() OVER (PARTITION BY company, metric, period, basis, segment
                                 ORDER BY published_on DESC, report_id DESC, table_id, row_no) AS rn
  FROM usable u
),
newest AS (SELECT * FROM ranked WHERE rn = 1)
SELECT n.fact_id, n.table_id, n.report_id, n.company, n.period, n.basis, n.metric, n.segment, n.line_label,
       n.value_kind, n.value_num, n.value_printed, n.page, n.row_no, n.col_no, n.published_on,
       CASE WHEN o.fact_id IS NULL THEN 0 ELSE 1 END AS restated,
       o.value_num AS prev_value_num, o.value_printed AS prev_value_printed,
       o.report_id AS prev_report_id, o.page AS prev_page
FROM newest n
LEFT JOIN ranked o ON o.fact_id = (
  SELECT x.fact_id FROM usable x
  WHERE x.company = n.company AND x.metric = n.metric AND x.period = n.period AND x.basis = n.basis
    AND x.segment = n.segment AND x.report_id != n.report_id AND x.value_num != n.value_num
  ORDER BY x.published_on DESC, x.report_id DESC LIMIT 1);
"""

# columns added after the first release; KnowledgeStore adds them to an older knowledge.db
MIGRATIONS = [
    ("fin_table", "unit_percent", "INTEGER NOT NULL DEFAULT 0"),
]
