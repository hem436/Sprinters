"""Build business.db, the synthetic company data the SQL tools read (contract 13 sections 2 and 3).

    python scripts/make_business_data.py            # writes data/business.db (path from config/app.yaml)

Anchor facts below are written exactly, so documents, tools and the eval set agree (contract 12 WP-0).
Everything else is random with a fixed seed, so every run builds the same file. Money is INTEGER paise.
"""

from __future__ import annotations

import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

# Anchor facts (contract 12 section 2). Change a number here and every tool and test follows.
SEED = 20261027
DATA_DATE = date(2026, 10, 27)                       # "today" for the generated dates
P104_BUDGET_TRAVEL_FY2026_27 = 4_00_000              # rupees
P104_TRAVEL_CLAIMS_FY2026_27 = [                     # (rupees, status); approved + paid = ₹4,35,500
    (62_000, "PAID"), (48_500, "PAID"), (75_000, "APPROVED"),
    (91_000, "PAID"), (55_000, "APPROVED"), (1_04_000, "APPROVED"),
    (18_000, "SUBMITTED"), (27_500, "SUBMITTED"), (12_000, "REJECTED"),   # pending and rejected: not "spent"
]
FINANCE_LAPTOPS_NOT_ENCRYPTED = 3                    # for POL-HR-014 questions

DEPARTMENTS = [("D-ENG", "Engineering", "CC-100"), ("D-FIN", "Finance", "CC-200"),
               ("D-HR", "Human Resources", "CC-300"), ("D-OPS", "Operations", "CC-400")]
PROJECTS = [
    ("P-101", "Payments gateway upgrade", "D-ENG", "ACTIVE"),
    ("P-102", "Quarterly close automation", "D-FIN", "ACTIVE"),
    ("P-103", "Campus hiring drive", "D-HR", "CLOSED"),
    ("P-104", "Vendor onboarding portal", "D-OPS", "ACTIVE"),
    ("P-105", "Data centre migration", "D-ENG", "ON_HOLD"),
    ("P-106", "Audit readiness", "D-FIN", "ACTIVE"),
    ("P-107", "Branch network rollout", "D-OPS", "ACTIVE"),
    ("P-108", "Learning platform", "D-HR", "ACTIVE"),
]
CATEGORIES = ["TRAVEL", "MEALS", "LODGING", "SOFTWARE", "HARDWARE", "TRAINING"]
CITIES = ["Mumbai", "Delhi", "Bengaluru", "Pune", "Hyderabad", "Chennai"]
FISCAL_YEARS = ["FY2025-26", "FY2026-27"]

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE department (
    dept_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    cost_centre TEXT NOT NULL
);
CREATE TABLE employee (
    employee_code TEXT PRIMARY KEY,
    dept_id       TEXT NOT NULL REFERENCES department (dept_id),
    grade         TEXT NOT NULL CHECK (grade IN ('G1','G2','G3','G4','G5','G6')),
    location      TEXT NOT NULL,
    join_date     TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('ACTIVE','EXITED'))
);
CREATE TABLE project (
    project_id TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    dept_id    TEXT NOT NULL REFERENCES department (dept_id),
    status     TEXT NOT NULL CHECK (status IN ('ACTIVE','ON_HOLD','CLOSED')),
    start_date TEXT NOT NULL,
    end_date   TEXT
);
CREATE TABLE budget (
    project_id   TEXT NOT NULL REFERENCES project (project_id),
    fiscal_year  TEXT NOT NULL,
    category     TEXT NOT NULL CHECK (category IN ('TRAVEL','MEALS','LODGING','SOFTWARE','HARDWARE','TRAINING')),
    amount_paise INTEGER NOT NULL CHECK (amount_paise >= 0),
    PRIMARY KEY (project_id, fiscal_year, category)
);
CREATE TABLE expense_claim (
    claim_id       TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES project (project_id),
    employee_code  TEXT NOT NULL REFERENCES employee (employee_code),
    category       TEXT NOT NULL CHECK (category IN ('TRAVEL','MEALS','LODGING','SOFTWARE','HARDWARE','TRAINING')),
    city           TEXT NOT NULL,
    claim_date     TEXT NOT NULL,
    fiscal_year    TEXT NOT NULL,
    amount_paise   INTEGER NOT NULL CHECK (amount_paise > 0),
    status         TEXT NOT NULL CHECK (status IN ('SUBMITTED','APPROVED','REJECTED','PAID')),
    policy_version TEXT NOT NULL
);
CREATE TABLE it_asset (
    asset_id        TEXT PRIMARY KEY,
    asset_type      TEXT NOT NULL CHECK (asset_type IN ('LAPTOP','DESKTOP','PHONE')),
    employee_code   TEXT REFERENCES employee (employee_code),
    dept_id         TEXT NOT NULL REFERENCES department (dept_id),
    encrypted       INTEGER NOT NULL CHECK (encrypted IN (0, 1)),
    last_patch_date TEXT NOT NULL,
    os              TEXT NOT NULL
);
CREATE INDEX ix_claim_project_year_cat ON expense_claim (project_id, fiscal_year, category);
CREATE INDEX ix_claim_status ON expense_claim (status);
CREATE INDEX ix_asset_dept_type ON it_asset (dept_id, asset_type);

-- "Spent" means APPROVED or PAID, in every tool (contract 13 section 3).
CREATE VIEW v_spend AS
    SELECT * FROM expense_claim WHERE status IN ('APPROVED', 'PAID');

CREATE VIEW v_budget_status AS
    SELECT b.project_id, b.fiscal_year, b.category, b.amount_paise AS budget_paise,
           COALESCE((SELECT SUM(s.amount_paise) FROM v_spend s
                     WHERE s.project_id = b.project_id AND s.fiscal_year = b.fiscal_year
                       AND s.category = b.category), 0) AS spent_paise
    FROM budget b;
"""


def fiscal_year(d: date) -> str:
    """Indian fiscal year, April to March: 2026-05-10 is FY2026-27."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"FY{start}-{(start + 1) % 100:02d}"


def build(path: Path) -> None:
    rnd = random.Random(SEED)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)                     # drop and recreate (contract 02)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO department VALUES (?, ?, ?)", DEPARTMENTS)

        dept_ids = [d[0] for d in DEPARTMENTS]
        employees = []
        for n in range(1001, 1043):                  # E1001 to E1042
            join = DATA_DATE - timedelta(days=rnd.randint(60, 3000))
            status = "EXITED" if rnd.random() < 0.1 else "ACTIVE"
            employees.append((f"E{n}", rnd.choice(dept_ids), f"G{rnd.randint(1, 6)}", rnd.choice(CITIES[:4]),
                              join.isoformat(), status))
        conn.executemany("INSERT INTO employee VALUES (?, ?, ?, ?, ?, ?)", employees)
        codes = [e[0] for e in employees]

        conn.executemany(
            "INSERT INTO project VALUES (?, ?, ?, ?, ?, ?)",
            [(pid, name, dept, status, "2025-04-01", None if status == "ACTIVE" else "2026-09-30")
             for pid, name, dept, status in PROJECTS],
        )

        budgets = []
        for pid, *_ in PROJECTS:
            for fy in FISCAL_YEARS:
                for cat in CATEGORIES:
                    rupees = P104_BUDGET_TRAVEL_FY2026_27 if (pid, fy, cat) == ("P-104", "FY2026-27", "TRAVEL") \
                        else rnd.randrange(50_000, 6_00_000, 5_000)
                    budgets.append((pid, fy, cat, rupees * 100))
        conn.executemany("INSERT INTO budget VALUES (?, ?, ?, ?)", budgets)

        claims, n = [], 20001
        first_day = date(2025, 4, 1)
        while len(claims) < 291:
            d = first_day + timedelta(days=rnd.randint(0, (DATA_DATE - first_day).days - 1))
            pid, cat = rnd.choice(PROJECTS)[0], rnd.choice(CATEGORIES)
            if (pid, fiscal_year(d), cat) == ("P-104", "FY2026-27", "TRAVEL"):
                continue                             # that line holds only the anchor claims
            status = rnd.choices(["PAID", "APPROVED", "SUBMITTED", "REJECTED"], [50, 25, 15, 10])[0]
            claims.append((f"EXP-{n}", pid, rnd.choice(codes), cat, rnd.choice(CITIES), d.isoformat(),
                           fiscal_year(d), rnd.randrange(1_500, 90_000, 50) * 100, status,
                           "2.0" if d >= date(2026, 4, 1) else "1.0"))
            n += 1
        for i, (rupees, status) in enumerate(P104_TRAVEL_CLAIMS_FY2026_27):
            d = date(2026, 4, 15) + timedelta(days=17 * i)
            claims.append((f"EXP-{20860 + i}", "P-104", rnd.choice(codes), "TRAVEL", rnd.choice(CITIES[:3]),
                           d.isoformat(), fiscal_year(d), rupees * 100, status, "2.0"))
        conn.executemany("INSERT INTO expense_claim VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", claims)

        assets = []
        for i in range(60):
            asset_type = rnd.choices(["LAPTOP", "DESKTOP", "PHONE"], [60, 15, 25])[0]
            prefix = {"LAPTOP": "LT", "DESKTOP": "DT", "PHONE": "PH"}[asset_type]
            owner = rnd.choice(employees)
            patched = DATA_DATE - timedelta(days=rnd.randint(0, 75))
            assets.append([f"{prefix}-{401 + i:04d}", asset_type, owner[0], owner[1], int(rnd.random() > 0.15),
                           patched.isoformat(), rnd.choice(["Windows 11", "macOS 15", "Ubuntu 24.04"])])
        finance_laptops = [a for a in assets if a[3] == "D-FIN" and a[1] == "LAPTOP"]
        for k, a in enumerate(finance_laptops):
            a[4] = 0 if k < FINANCE_LAPTOPS_NOT_ENCRYPTED else 1
        conn.executemany("INSERT INTO it_asset VALUES (?, ?, ?, ?, ?, ?, ?)", [tuple(a) for a in assets])
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.config import get_config

    paths = get_config().paths
    target = paths.resolve(paths.business_db)
    build(target)
    print(f"wrote {target}")
