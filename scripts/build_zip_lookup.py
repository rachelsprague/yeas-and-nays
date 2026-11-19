# /// script
# requires-python = ">=3.12"
# dependencies = ["pyproj>=3.6", "pyshp>=2.3", "shapely>=2.1"]
# ///
"""Build the ZIP code lookup for the /find/ page's district map.

ZIP codes are matched to districts through ZIP Code Tabulation Areas (ZCTAs),
the Census Bureau's areas built from census blocks that approximate ZIP codes.
Each block's ZCTA comes from the Census ZCTA-to-block relationship file, and
its district from the Census block equivalency file for that Congress (public
domain). A ZCTA lists every district it has land in, as the Census Bureau's
own ZCTA-to-district relationship files do; one listing several districts is
split, and the page shows them all rather than guessing one. Writes
site/assets/maps/zip-<congress>.json:

    {"congress": 120,
     "districts": {"KY-6": "40003 40004 ...", "WY": "82001 ..."},
     "no_voting_member": "20001 ... 00601 ..."}

"no_voting_member" holds ZCTAs only in the District of Columbia or the
territories, whose House members can't vote on the floor (not on the map).

    uv run scripts/build_zip_lookup.py 119
    uv run scripts/build_zip_lookup.py 120

Run it again whenever build_district_map.py rewrites a district map. The 119th
build stops unless it matches the Census Bureau's 119th ZCTA-to-district file
exactly, which checks the method used for Congresses that file doesn't cover
yet. Every build stops unless its districts are the map's. Downloads (the
ZCTA-to-block file is about 1 GB) are cached in data/raw/maps/. Imports the
50 states from build_district_map.py, so it takes that script's libraries,
pinned in build_zip_lookup.py.lock.

Sources:
  ZCTA to block: rel2020/zcta520/tab20_zcta520_tabblock20_natl.txt
  Blocks to districts: decennial/rdo/mapping-files, cd119.zip and cd120.zip.
    A block a plan splits between districts is assigned to one of them
    (CD<congress>_BlockSplits.pdf beside each file), so a ZCTA that reaches
    another district only through such a block isn't listed as split.
  Check (119th): rel2020/cd-sld/tab20_cd11920_zcta520_natl.txt
"""

import csv
import io
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_district_map import STATE_FIPS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "raw" / "maps"
MAPS = ROOT / "site" / "_maps"
OUT = ROOT / "site" / "assets" / "maps"

REL = "https://www2.census.gov/geo/docs/maps-data/data/rel2020"
ZCTA_BLOCKS = f"{REL}/zcta520/tab20_zcta520_tabblock20_natl.txt"
MAPPING = "https://www2.census.gov/programs-surveys/decennial/rdo/mapping-files"
BLOCK_FILES = {
    119: (f"{MAPPING}/2025/119-congressional-district-befs/cd119.zip", "NationalCD119.txt"),
    120: (f"{MAPPING}/2027/120-congressional-district-befs/cd120.zip", "NationalCD120.txt"),
}
CHECK_FILES = {119: f"{REL}/cd-sld/tab20_cd11920_zcta520_natl.txt"}

FIPS = {state: fips for fips, state in STATE_FIPS.items()}
NO_DISTRICT = "ZZ"  # blocks in water, with no district
NON_VOTING = "98"  # the delegate or resident commissioner's seat in DC and the territories


def fetch(url):
    """Returns the cached path of the file at url, downloading it once."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / url.rsplit("/", 1)[1]
    if not path.exists():
        print(f"downloading {url}", file=sys.stderr)
        part = path.with_name(path.name + ".part")  # a failed download never leaves a cached file
        with urllib.request.urlopen(url, timeout=120) as r, open(part, "wb") as f:
            shutil.copyfileobj(r, f)
        part.replace(path)
    return path


def seat(fips, code):
    """The site's seat key ("KY-6", "WY" at large) for a state FIPS code and
    district code, or None for a seat with no floor vote."""
    state = STATE_FIPS.get(fips)
    if state is None or code == NON_VOTING:
        return None
    n = int(code)
    return f"{state}-{n}" if n else state


def block_seats(rows):
    """{block GEOID as int: seat key or None} from a block equivalency file's rows."""
    return {int(r["GEOID"]): seat(r["GEOID"][:2], r["CDFP"]) for r in rows if r["CDFP"] != NO_DISTRICT}


def zcta_seats(rows, blocks):
    """{ZCTA: set of seat keys} for each ZCTA with land, from the ZCTA-to-block
    relationship file's rows. An empty set: land only where no member votes."""
    out = {}
    for r in rows:
        zcta = r["GEOID_ZCTA5_20"]
        if not zcta or int(r["AREALAND_PART"]) == 0:
            continue
        seats = out.setdefault(zcta, set())
        s = blocks.get(int(r["GEOID_TABBLOCK_20"]))  # missing: no district (water)
        if s:
            seats.add(s)
    return out


def official_seats(rows):
    """{ZCTA: set of seat keys} from a Census ZCTA-to-district relationship file's rows, by land."""
    out = {}
    for r in rows:
        zcta, cd = r["GEOID_ZCTA5_20"], next(v for k, v in r.items() if k.startswith("GEOID_CD"))
        if not zcta or int(r["AREALAND_PART"]) == 0:
            continue
        s = seat(cd[:2], cd[2:])
        out.setdefault(zcta, set())
        if s:
            out[zcta].add(s)
    return out


def differences(ours, official, limit=10):
    """Lines naming ZCTAs whose seats differ between two lookups."""
    keys = sorted(set(ours) | set(official))
    diff = [f"{z}: {sorted(ours.get(z, ()))} vs {sorted(official.get(z, ()))}"
            for z in keys if ours.get(z) != official.get(z)]
    return diff[:limit] + ([f"... and {len(diff) - limit} more"] if len(diff) > limit else [])


def map_problems(lookup, map_seats):
    """Lines naming seats in the lookup but not on the map, or on the map with no ZCTA."""
    found = set().union(*lookup.values())
    return ([f"not on the map: {s}" for s in sorted(found - map_seats)]
            + [f"no ZCTA: {s}" for s in sorted(map_seats - found)])


def seat_order(key):
    state, _, n = key.partition("-")
    return state, int(n or 0)


def document(congress, lookup):
    """The file's JSON: each seat's ZCTAs, and those where no member votes."""
    by_seat = {}
    for zcta, seats in lookup.items():
        for s in seats:
            by_seat.setdefault(s, []).append(zcta)
    return {"congress": congress,
            "districts": {s: " ".join(sorted(by_seat[s])) for s in sorted(by_seat, key=seat_order)},
            "no_voting_member": " ".join(sorted(z for z, seats in lookup.items() if not seats))}


def read_rows(path, delimiter="|"):
    with open(path, encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f, delimiter=delimiter)


def build(congress):
    url, member = BLOCK_FILES[congress]
    with zipfile.ZipFile(fetch(url)) as z, z.open(member) as f:
        blocks = block_seats(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline="")))
    lookup = zcta_seats(read_rows(fetch(ZCTA_BLOCKS)), blocks)

    if congress in CHECK_FILES:
        diff = differences(lookup, official_seats(read_rows(fetch(CHECK_FILES[congress]))))
        if diff:
            sys.exit(f"{congress}: lookup doesn't match the Census relationship file:\n  " + "\n  ".join(diff))
    drawn = json.loads((MAPS / f"{congress}.json").read_text())["districts"]
    problems = map_problems(lookup, {seat(FIPS[d["state"]], f"{d['district']:02d}") for d in drawn})
    if problems:
        sys.exit(f"{congress}: lookup doesn't fit the district map:\n  " + "\n  ".join(problems))

    path = OUT / f"zip-{congress}.json"
    path.write_text(json.dumps(document(congress, lookup), separators=(",", ":")) + "\n")
    split = sum(len(s) > 1 for s in lookup.values())
    print(f"wrote {path.relative_to(ROOT)}: {len(lookup)} ZCTAs, {split} split, "
          f"{path.stat().st_size // 1024} KB", file=sys.stderr)


if __name__ == "__main__":
    for arg in sys.argv[1:] or ["119", "120"]:
        build(int(arg))
