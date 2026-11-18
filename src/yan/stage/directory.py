"""Parse member biographies from the Congressional Directory's plain text.

The directory (GovInfo package CDIR-YYYY-MM-DD, saved by `yan.ingest.directory`)
has a section per state and territory, each starting at a `<DOC>` line with the
state's name on a line of its own. Under a SENATORS heading come the senators'
biographies; under district headings ("ELEVENTH DISTRICT", "AT LARGE",
"DELEGATE", "RESIDENT COMMISSIONER"), each Representative's. A biography is
one paragraph:

    LATEEFAH SIMON, Democrat, of Oakland, CA; born in San Francisco, CA,
    January 29, 1977; education: B.A., public policy, Mills College, ...;
    professional history: non-profit executive; ...; election history:
    elected to the 119th Congress on November 5, 2024.

Each is staged with its seat (state, chamber, district: 0 for an at-large
seat, a Delegate or the Resident Commissioner, as in congress-legislators),
the name as printed, the opening after the name and party ("of Oakland, CA;
born in ...") as printed, and the text of each labeled field. The opening
isn't split further: its wording varies from member to member ("born in",
"born on", "raised in", or no birthplace). A paragraph under no seat heading,
or outside a state's section, is skipped.
"""

import re
from pathlib import Path

STATES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA",
    "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT",
    "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM",
    "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
    "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
    "AMERICAN SAMOA": "AS", "DISTRICT OF COLUMBIA": "DC", "GUAM": "GU",
    "NORTHERN MARIANA ISLANDS": "MP", "PUERTO RICO": "PR", "VIRGIN ISLANDS": "VI",
}
# House seats with no numbered district: congress-legislators numbers them 0.
SEAT_ZERO = {"AT LARGE", "DELEGATE", "RESIDENT COMMISSIONER"}
_UNITS = ["FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH", "SEVENTH", "EIGHTH", "NINTH",
          "TENTH", "ELEVENTH", "TWELFTH", "THIRTEENTH", "FOURTEENTH", "FIFTEENTH", "SIXTEENTH",
          "SEVENTEENTH", "EIGHTEENTH", "NINETEENTH"]
ORDINALS = {word: n for n, word in enumerate(_UNITS, 1)}
ORDINALS["NINTEENTH"] = 19  # as printed in the 2026 edition
for _n, (_tens, _tenth) in enumerate([("TWENTY", "TWENTIETH"), ("THIRTY", "THIRTIETH"),
                                      ("FORTY", "FORTIETH"), ("FIFTY", "FIFTIETH")], 2):
    ORDINALS[_tenth] = _n * 10
    for _unit, _u in zip(_UNITS[:9], range(1, 10)):
        ORDINALS[f"{_tens}-{_unit}"] = _n * 10 + _u
DISTRICT_HEADING = re.compile(r"([A-Z-]+) DISTRICT")
FIELDS = {"education": "education", "professional history": "professional_history",
          "military service": "military_service", "election history": "election_history"}
# A label follows a semicolon, or now and then a comma.
FIELD_LABEL = re.compile(r"[;,]\s*(" + "|".join(FIELDS) + r"):\s*")
# Names are in capitals, but with a lowercase letter here and there ("SARAH McBRIDE",
# "DONALD S. BEYER, Jr."). The party is followed by a comma, or now and then by more words
# ("Democrat Delegate,", "Democratic-Farmer-Labor Party,") or no comma ("Republican of Austin").
PARTY = r"(?:Democrat(?:ic-Farmer-Labor Party| Delegate)?|Republican|Independent)"
BIO = re.compile(rf"(?P<name>[A-Z][^;:]*?), {PARTY},? (?P<opening>.*)", re.S)


def parse_dir(path: Path) -> list[dict]:
    """Biographies from the newest edition saved under `path` (none if there is none), each
    with its source file, edition (package ID) and date issued (from the ID)."""
    files = sorted(path.glob("CDIR-*.txt"))
    if not files:
        return []
    newest = files[-1]
    edition = newest.stem
    return [{"source_file": newest.name, "edition": edition, "date_issued": edition.removeprefix("CDIR-"), **row}
            for row in parse(newest.read_text(encoding="utf-8"))]


def parse(text: str) -> list[dict]:
    """One row per biography: state, chamber, district, printed_name, opening, and the
    labeled fields (None when a biography doesn't have one)."""
    rows = []
    state = chamber = district = None
    # A <DOC> line starts a new paragraph even with no blank line before it.
    text = re.sub(r"^<DOC>", "\n<DOC>", text.replace("\r\n", "\n"), flags=re.M)
    for para in re.split(r"\n[ \t]*\n", text):
        lines = [line for line in para.split("\n") if line.strip()]
        for line in lines:
            if line.startswith("<DOC>"):
                state = chamber = district = None
            elif line.strip() in STATES:
                state, chamber, district = STATES[line.strip()], None, None
            elif state and (seat := _seat(line.strip())):
                chamber, district = seat
        if not (state and chamber and lines) or not (bio := BIO.fullmatch(_join(lines))):
            continue
        opening, *rest = FIELD_LABEL.split(bio["opening"])
        fields = dict.fromkeys(FIELDS.values())
        for label, value in zip(rest[::2], rest[1::2]):
            fields[FIELDS[label]] = _clean(value)
        rows.append({"state": state, "chamber": chamber, "district": district,
                     "printed_name": bio["name"], "opening": _clean(opening), **fields})
    return rows


def _seat(heading: str) -> tuple[str, int | None] | None:
    """(chamber, district) for a seat heading line, or None for any other line."""
    if heading == "SENATORS":
        return "senate", None
    if heading in SEAT_ZERO:
        return "house", 0
    if (m := DISTRICT_HEADING.fullmatch(heading)) and m[1] in ORDINALS:
        return "house", ORDINALS[m[1]]
    return None


def _join(lines: list[str]) -> str:
    """A paragraph's lines as one line. A line ending in a hyphen ("1985-", "Kamlager-")
    continues without a space."""
    out = ""
    for line in lines:
        line = line.strip()
        out += line if not out or out.endswith("-") else " " + line
    return out


def _clean(value: str) -> str | None:
    return value.strip().rstrip(";,.").strip() or None
