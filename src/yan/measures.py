"""Map a vote's measure number, as recorded, to a Congress.gov bill type and number.

The House records "H R 1013" or "H RES 1655"; the Senate records "H.R. 2347",
"S. 5" or "S.J.Res. 98". Nominations ("PN1129", "PN11-22") and non-measure
questions ("QUORUM", "ADJOURN") have no bill and map to None.
"""

import re

# Letters of the recorded prefix -> Congress.gov API bill type.
BILL_TYPES = {
    "HR": "hr",
    "S": "s",
    "HRES": "hres",
    "SRES": "sres",
    "HJRES": "hjres",
    "SJRES": "sjres",
    "HCONRES": "hconres",
    "SCONRES": "sconres",
}


def parse_measure(measure_number: str | None) -> tuple[str, str] | None:
    """("hres", "1655") for "H RES 1655"; None when the measure isn't a bill or resolution."""
    if not measure_number:
        return None
    m = re.fullmatch(r"([A-Za-z. ]+?)\s*(\d+)", measure_number.strip())
    if not m:
        return None
    bill_type = BILL_TYPES.get(re.sub(r"[^A-Z]", "", m.group(1).upper()))
    return (bill_type, m.group(2)) if bill_type else None
