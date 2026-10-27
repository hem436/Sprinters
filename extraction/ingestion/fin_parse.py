"""Contract 14 F3 to F6: pure rules, no I/O. Numbers, units and scale, periods and basis, statement type, labels.

All amounts are exact `Decimal`s. A value is stored as an integer in its base unit:
- AMOUNT: rupees (the printed value x the table scale)
- PERCENT: basis points (12.5 % = 1250)
- PER_SHARE: paise (EPS ₹45.67 = 4567); per-share values are printed in rupees whatever the table scale
- COUNT: as printed
"""
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

# ---- F5 numbers ------------------------------------------------------------------------------------------------------

ZERO_WORDS = {"-", "–", "—", "nil", "—-", "--"}
_GROUPED = re.compile(r"^(\d{1,3}(,\d{3})+|\d{1,2}(,\d{2})+,\d{3}|\d+)(\.\d+)?$")     # western, Indian, or plain
_STRIP = re.compile(r"[₹$€£]|\b(rs\.?|inr|usd)\b|\*+|\s+", re.IGNORECASE)


def parse_number(text: str | None) -> Decimal | None:
    """`(1,234.50)` = -1234.50; `1,23,456` = 123456; `-`, a long dash, `nil` = 0; `12.5%` = 12.5.
    Returns None for a cell that is not a number, or whose digit grouping is wrong (a misread such as `1,2345`)."""
    if text is None:
        return None
    s = _STRIP.sub("", str(text)).strip()
    if not s:
        return None
    if s.lower() in ZERO_WORDS:
        return Decimal(0)
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.startswith(("-", "−", "–")):
        negative, s = True, s[1:]
    s = s.rstrip("%")
    if not _GROUPED.match(s):
        return None
    try:
        value = Decimal(s.replace(",", ""))
    except InvalidOperation:
        return None
    return -value if negative else value


def decimals_printed(text: str) -> int:
    m = re.search(r"\.(\d+)", text or "")
    return len(m.group(1)) if m else 0


def looks_numeric(text: str) -> bool:
    """A cell that is meant to be a number (mostly digits), whether or not it parses. Used for NUMBER_SUSPECT."""
    s = _STRIP.sub("", text or "")
    digits = sum(ch.isdigit() for ch in s)
    return digits >= 2 and digits / max(len(s), 1) >= 0.5


# ---- F4 unit and scale -----------------------------------------------------------------------------------------------

SCALES = [  # order matters: "crore" before "core"-like words is not an issue, but "lakh" must not match "lakhs" twice
    (re.compile(r"\bcrores?\b|\bcr\b", re.I), 10_000_000),
    (re.compile(r"\blakhs?\b|\blacs?\b", re.I), 100_000),
    (re.compile(r"\bbillions?\b|\bbn\b", re.I), 1_000_000_000),
    (re.compile(r"\bmillions?\b|\bmn\b", re.I), 1_000_000),
    (re.compile(r"\bthousands?\b|'000", re.I), 1_000),
]


@dataclass(frozen=True)
class Unit:
    scale: int                 # 1, 1000, 100000, 1000000, 10000000, 1000000000
    currency: str              # INR, USD
    percent: bool              # the whole table is in %
    known: bool                # a unit phrase was found


def parse_unit(*texts: str) -> Unit:
    joined = " ".join(t for t in texts if t)
    currency = "USD" if re.search(r"\bus\$|\busd\b|\$", joined, re.I) else "INR"
    for pattern, scale in SCALES:
        if pattern.search(joined):
            return Unit(scale, currency, False, True)
    if re.search(r"\(\s*%\s*\)|\bin\s+%|\bper\s*cent\b|\bpercentage\b", joined, re.I):
        return Unit(1, currency, True, True)
    if re.search(r"₹|\brs\.?\b|\binr\b|\busd\b|\$", joined, re.I):
        return Unit(1, currency, False, True)          # "(₹)" or "Amount in ₹": rupees, scale 1
    return Unit(1, currency, False, False)


# ---- F3 periods ------------------------------------------------------------------------------------------------------

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"


def fy_label(end_year: int) -> str:
    """The Indian fiscal year that ends in March of `end_year`: 2025 -> FY2024-25."""
    return f"FY{end_year - 1}-{end_year % 100:02d}"


def fy_of(d: date) -> str:
    """The fiscal year that contains the date (April to March)."""
    return fy_label(d.year + 1 if d.month >= 4 else d.year)


def _quarter_of(month: int) -> int:
    return {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[month]


def _year(text: str) -> int:
    y = int(text)
    return y + 2000 if y < 100 else y


def parse_period(header: str) -> str | None:
    """A column header to a period label, or None when the column is not a period column.

    "FY2024-25", "FY 2024-25", "2024-25", "FY25", "FY2025"              -> FY2024-25
    "Year ended 31 March 2025", "31.03.2025", "March 31, 2025", "31-Mar-25" -> FY2024-25
    "Q2 FY25", "Q2 FY2024-25", "Quarter ended 30 September 2024"         -> FY2024-25 Q2
    "Year ended 31 December 2024"                                         -> CY2024
    "Nine months ended ...", "Half year ended ..."                        -> None (not supported, stays text)
    """
    h = " ".join((header or "").split())
    low = h.lower()
    if not low or re.search(r"\b(nine|six|half|9m|h1|h2)\b", low):
        return None
    quarter = None
    m = re.search(r"\bq([1-4])\b", low)
    if m:
        quarter = int(m.group(1))

    fy = None
    m = re.search(r"\bfy\s?'?(\d{4})\s?[-–/]\s?(\d{2,4})\b", low) or re.search(r"\b(\d{4})\s?[-–/]\s?(\d{2})\b", low)
    if m:
        start, end = int(m.group(1)), _year(m.group(2)[-2:])
        if end == start + 1:
            fy = fy_label(end)
    if fy is None:
        m = re.search(r"\bfy\s?'?(\d{2}|\d{4})\b", low)
        if m:
            fy = fy_label(_year(m.group(1)))
    if fy and quarter:
        return f"{fy} Q{quarter}"
    if fy:
        return fy

    d = _find_date(low)
    if d is None:
        m = re.search(r"\b(19|20)\d{2}\b", low)
        if m and re.fullmatch(r"(19|20)\d{2}", low.strip()):
            return fy_label(int(m.group(0)))     # a bare year under "Year ended 31 March"
        return None
    if "quarter" in low or quarter:
        return f"{fy_of(d)} Q{_quarter_of(d.month)}"
    if d.month == 3:
        return fy_label(d.year)
    if d.month == 12:
        return f"CY{d.year}"
    return None


def _find_date(low: str) -> date | None:
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s.\-/]+" + _MONTH + r"[\s,.\-/]+(\d{2,4})\b", low)
    if m:
        return _safe_date(_year(m.group(3)), MONTHS[m.group(2)[:3]], int(m.group(1)))
    m = re.search(_MONTH + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", low)
    if m:
        return _safe_date(int(m.group(3)), MONTHS[m.group(1)[:3]], int(m.group(2)))
    m = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b", low)
    if m:
        return _safe_date(_year(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.search(_MONTH + r"\s+(\d{4})\b", low)
    if m:
        return _safe_date(int(m.group(2)), MONTHS[m.group(1)[:3]], 28)
    return None


def _safe_date(y: int, mth: int, d: int) -> date | None:
    try:
        return date(y, mth, d)
    except ValueError:
        return None


# ---- F3 basis and statement --------------------------------------------------------------------------------------------

def parse_basis(*texts: str) -> str | None:
    joined = " ".join(t for t in texts if t).lower()
    has_s, has_c = "standalone" in joined, "consolidated" in joined
    if has_s and not has_c:
        return "STANDALONE"
    if has_c and not has_s:
        return "CONSOLIDATED"
    if has_s and has_c:                      # both words: the nearest one to the table (the caption) wins
        return "STANDALONE" if joined.rfind("standalone") > joined.rfind("consolidated") else "CONSOLIDATED"
    return None


def parse_statement(*texts: str) -> str:
    joined = " ".join(t for t in texts if t).lower()
    rules = [("SEGMENT", r"segment"), ("CF", r"cash\s*flow"), ("BS", r"balance\s*sheet|financial\s*position"),
             ("PL", r"profit\s*(and|&)\s*loss|income\s*statement|statement\s*of\s*operations")]
    # the text nearest the table is last in `texts`; search from the end
    best, at = "OTHER", -1
    for name, pattern in rules:
        for m in re.finditer(pattern, joined):
            if m.start() > at:
                best, at = name, m.start()
    return best


# ---- F6 labels and standard metrics ------------------------------------------------------------------------------------

STANDARD_METRICS = {
    "revenue": "AMOUNT", "other_income": "AMOUNT", "total_income": "AMOUNT", "employee_cost": "AMOUNT",
    "ebitda": "AMOUNT", "depreciation": "AMOUNT", "finance_cost": "AMOUNT", "pbt": "AMOUNT", "tax": "AMOUNT",
    "pat": "AMOUNT", "eps_basic": "PER_SHARE", "total_assets": "AMOUNT", "total_equity": "AMOUNT",
    "borrowings": "AMOUNT", "cash": "AMOUNT", "operating_cash_flow": "AMOUNT", "operating_margin": "PERCENT",
    "headcount": "COUNT", "segment_revenue": "AMOUNT",
}

# Contract 14 section 4. Only exact (normalised) labels; anything else waits for a person (F6).
# "Total income from operations" is deliberately absent: it maps to revenue only when a person agrees.
DICTIONARY = {
    "revenue from operations": "revenue", "total revenue from operations": "revenue",
    "revenue from operations net": "revenue",
    "other income": "other_income",
    "total income": "total_income",
    "employee benefits expense": "employee_cost", "employee benefit expense": "employee_cost",
    "employee benefits expenses": "employee_cost",
    "ebitda": "ebitda", "earnings before interest tax depreciation and amortisation": "ebitda",
    "earnings before interest tax depreciation and amortization": "ebitda",
    "depreciation and amortisation expense": "depreciation", "depreciation and amortization expense": "depreciation",
    "depreciation and amortisation expenses": "depreciation", "depreciation and amortisation": "depreciation",
    "finance costs": "finance_cost", "finance cost": "finance_cost",
    "profit before tax": "pbt", "profit before tax pbt": "pbt",
    "total tax expense": "tax", "total tax expenses": "tax", "tax expense": "tax", "income tax expense": "tax",
    "profit for the year": "pat", "net profit": "pat", "profit for the period": "pat", "profit after tax": "pat",
    "net profit for the year": "pat",
    "basic eps": "eps_basic", "basic": "eps_basic", "basic earnings per share": "eps_basic",
    "earnings per share basic": "eps_basic", "eps basic": "eps_basic",
    "total assets": "total_assets", "total equity": "total_equity",
    "borrowings": "borrowings", "total borrowings": "borrowings",
    "cash and cash equivalents": "cash",
    "net cash from operating activities": "operating_cash_flow",
    "net cash generated from operating activities": "operating_cash_flow",
    "net cash flow from operating activities": "operating_cash_flow",
    "net cash generated from used in operating activities": "operating_cash_flow",
    "operating margin": "operating_margin",
    "number of employees": "headcount", "headcount": "headcount",
}

_NUMBERING = re.compile(r"^\s*(\(?([ivxlc]+|[a-z]|\d{1,2})[.)]\s+|[-•*]\s+)", re.IGNORECASE)


def normalise_label(label: str) -> str:
    """Lower case, no numbering ("I.", "(a)", "1."), no currency or unit marks, no punctuation, single spaces."""
    s = (label or "").strip()
    for _ in range(2):
        s = _NUMBERING.sub("", s)
    s = re.sub(r"\((₹|rs\.?|inr|%|in\s+%|in\s+₹)\)", " ", s, flags=re.IGNORECASE)
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


def value_kind(label: str, metric: str, table_unit: Unit) -> str:
    low = (label or "").lower()
    if metric:
        kind = STANDARD_METRICS.get(metric)
        if kind and kind != "AMOUNT":
            return kind
    if "per share" in low or re.search(r"\beps\b", low):
        return "PER_SHARE"
    if "%" in low:
        return "PERCENT"
    if low.startswith("number of") or "headcount" in low:
        return "COUNT"
    return "PERCENT" if table_unit.percent else "AMOUNT"


def to_base(value: Decimal, kind: str, scale: int) -> tuple[int, bool]:
    """The integer in the base unit, and whether it had to be rounded (more decimals than the base unit holds)."""
    factor = {"AMOUNT": Decimal(scale), "PERCENT": Decimal(100), "PER_SHARE": Decimal(100), "COUNT": Decimal(1)}[kind]
    exact = value * factor
    whole = exact.to_integral_value(rounding=ROUND_HALF_EVEN)
    return int(whole), whole != exact


def is_total_label(label: str) -> bool:
    return normalise_label(label).startswith("total")
