# /// script
# requires-python = ">=3.12"
# dependencies = ["shapely>=2.1"]
# ///
"""Build the small US map that vote pages draw each member's position on.

Reads the /find/ district map (site/_maps/<congress>.json, written by
scripts/build_district_map.py), simplifies its districts as one coverage so
neighbors still share edges, merges them into state outlines, and writes
site/assets/maps/<congress>.json. Vote pages fetch that file once (the browser
caches it) and fill each district (House) or state (Senate).

    uv run scripts/build_vote_map.py 119
    uv run scripts/build_vote_map.py 120

Run it again whenever build_district_map.py rewrites a district map.
Library versions are pinned in build_vote_map.py.lock (`uv lock --script
--upgrade scripts/build_vote_map.py` to update), so a rebuild of unchanged
input gives the same file.
"""

import json
import re
import sys
from pathlib import Path

import shapely
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "site" / "_maps"
OUT = ROOT / "site" / "assets" / "maps"

SCALE = 5  # source units per output unit: the 9750 x 6100 source becomes 1950 x 1220
CLOSE = 2  # gap between neighboring districts closed when merging a state, in source units
MIN_HOLE = 2500  # smallest hole kept in a state outline, in square source units (about 100 square px at 975 px wide)
SIMPLIFY = 40  # coverage simplification tolerance in source units (about 4 px at 975 px wide)

RING = re.compile(r"M(-?[\d.]+) (-?[\d.]+)l([^Mz]*)z")


def parse_path(d):
    """A district's path data (absolute move, relative lines, one ring per
    subpath) as one geometry, filled even-odd: a ring inside another is a hole."""
    geom = None
    for m in RING.finditer(d):
        x, y = float(m[1]), float(m[2])
        pts = [(x, y)]
        nums = [float(t) for t in m[3].split()]
        for dx, dy in zip(nums[::2], nums[1::2]):
            x, y = x + dx, y + dy
            pts.append((x, y))
        if len(pts) < 3:
            continue
        ring = Polygon(pts).buffer(0)
        geom = ring if geom is None else geom.symmetric_difference(ring)
    return shapely.make_valid(geom)


def path_data(geom):
    """SVG path data in output units: whole numbers, relative lines after each ring's first point."""
    out = []
    for poly in getattr(geom, "geoms", [geom]):
        if poly.geom_type != "Polygon":
            continue
        for ring in [poly.exterior, *poly.interiors]:
            pts = [(round(x / SCALE), round(y / SCALE)) for x, y in ring.coords[:-1]]
            pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
            if len(pts) < 3:
                continue
            steps = " ".join(f"{x1 - x0} {y1 - y0}" for (x0, y0), (x1, y1) in zip(pts, pts[1:]))
            out.append(f"M{pts[0][0]} {pts[0][1]}l{steps}z")
    return "".join(out)


def outline(parts):
    """A state's outline from its districts. The source districts were simplified
    one by one, so their shared edges can leave hairline gaps and slivers; close
    them, and drop any hole too small to be a real lake or bay."""
    merged = shapely.union_all(parts).buffer(CLOSE, join_style="mitre").buffer(-CLOSE, join_style="mitre")
    return shapely.MultiPolygon([
        Polygon(p.exterior, [r for r in p.interiors if Polygon(r).area >= MIN_HOLE])
        for p in getattr(merged, "geoms", [merged]) if p.geom_type == "Polygon"
    ])


def seat(state, district):
    """The site's seat code (Yan.seat): "KY-4", or "WY" for an at-large seat."""
    return f"{state}-{district}" if district > 0 else state


def build(congress):
    src = json.loads((SOURCE / f"{congress}.json").read_text())
    rows = src["districts"]
    shapes = shapely.coverage_simplify([parse_path(r["d"]) for r in rows], SIMPLIFY)

    by_state = {}
    for r, g in zip(rows, shapes):
        by_state.setdefault(r["state"], []).append(g)

    doc = {
        "congress": congress,
        "width": src["width"] // SCALE,
        "height": src["height"] // SCALE,
        "states": {s: path_data(outline(gs)) for s, gs in sorted(by_state.items())},
        "districts": {seat(r["state"], r["district"]): path_data(g) for r, g in zip(rows, shapes)},
    }
    empty = [k for k, d in [*doc["states"].items(), *doc["districts"].items()] if not d]
    if empty:
        sys.exit(f"nothing left to draw for {', '.join(empty)}; lower SIMPLIFY or SCALE")

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{congress}.json"
    path.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    print(f"wrote {path.relative_to(ROOT)}: {len(doc['states'])} states, {len(doc['districts'])} districts, "
          f"{path.stat().st_size // 1024} KB", file=sys.stderr)


if __name__ == "__main__":
    for arg in sys.argv[1:] or ["119", "120"]:
        build(int(arg))
