"""Numbers in text, as exact values. Used by conflict rule C1 and grounding check V2 (contracts 04, 11 section 6)."""
import re
from decimal import Decimal

# Grouped numbers (Indian 4,35,500 or western 435,500), optionally in brackets for negatives, or plain numbers.
# The look-behind stops "FY2026" or "v2" from giving numbers; "P-104" gives 104 on both sides of a comparison.
_NUMBER = re.compile(r"(?<![\w.])(\()?(-?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)(\))?")


def numbers_in(text: str) -> set[Decimal]:
    """Every number in the text as a Decimal, so ₹4,35,500 and 435500 and 435500.00 are the same value."""
    values = set()
    for opening, digits, closing in _NUMBER.findall(text):
        value = Decimal(digits.replace(",", ""))
        if opening and closing:
            value = -value          # accounting style: (1,234) means minus 1,234
        values.add(value.normalize())
    return values
