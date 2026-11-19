# /// script
# requires-python = ">=3.12"
# dependencies = ["pyproj>=3.6", "pyshp>=2.3", "shapely>=2.1"]
# ///
"""Build the congressional district map for the site's /find/ page.

Downloads Census Bureau boundary files and population estimates (public
domain), clips districts to the shoreline, projects them to an Albers USA
layout (Alaska and Hawaii inset), simplifies them as one coverage (so each
shared edge is simplified once; it stops if districts overlap or their shared
edges don't match), and writes SVG path data, city labels and each district's
largest cities and towns to site/_maps/<congress>.json. The site plugin pairs
each district with its current member.

    uv run scripts/build_district_map.py 119
    uv run scripts/build_district_map.py 120

Run it again only when district lines change (a new Congress or a court-ordered
map), then run scripts/build_vote_map.py for the vote pages' smaller map and
scripts/build_zip_lookup.py for the ZIP code search.
Downloads are cached in data/raw/maps/. Library versions are pinned in
build_district_map.py.lock (`uv lock --script --upgrade
scripts/build_district_map.py` to update), so a rebuild of unchanged
downloads gives the same file.

Sources:
  119th Congress: cartographic boundary file cb_2024_us_cd119_500k (already
    clipped to the shoreline).
  120th Congress: TIGER/Line 2026 tl_2026_<state>_cd120, one file per state,
    clipped here to the shoreline of cb_2024_us_state_500k. The Census Bureau's
    note on these files:
    census.gov/programs-surveys/geography/technical-documentation/user-note/120cd.html
"""

import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import shapefile
import shapely
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "raw" / "maps"
OUT = ROOT / "site" / "_maps"

CENSUS = "https://www2.census.gov/geo/tiger"
STATES_FILE = f"{CENSUS}/GENZ2024/shp/cb_2024_us_state_500k.zip"
PLACES_FILE = f"{CENSUS}/GENZ2024/shp/cb_2024_us_place_500k.zip"
# Population estimates for incorporated places (cities, towns, villages, boroughs).
POPULATION_FILE = ("https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/cities/totals/"
                   "sub-est2024.csv")

# The 50 states by FIPS code. DC and the territories elect House members who
# can't vote on the floor, so they aren't drawn.
STATE_FIPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE",
    "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS",
    "21": "KY", "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY",
    "37": "NC", "38": "ND", "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC",
    "46": "SD", "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV",
    "55": "WI", "56": "WY",
}
DISTRICT_FILES = {
    119: [f"{CENSUS}/GENZ2024/shp/cb_2024_us_cd119_500k.zip"],
    120: [f"{CENSUS}/TIGER2026/CD/tl_2026_{fips}_cd120.zip" for fips in STATE_FIPS],
}

# States whose 120th Congress districts are their 119th ones, although the
# 2026 TIGER/Line file shows a newer plan (e.g. a court-ordered map the file
# doesn't have yet). None now: Missouri was here until its file had the 2022
# plan that courts required for the November 2026 election (checked 2026-11-15).
KEEP_119 = {120: set()}

# Equal-area Albers projections (NAD83, meters): lower 48, Alaska, Hawaii.
CONUS = "+proj=aea +lat_1=29.5 +lat_2=45.5 +lat_0=37.5 +lon_0=-96 +datum=NAD83 +units=m"
ALASKA = "+proj=aea +lat_1=55 +lat_2=65 +lat_0=50 +lon_0=-154 +datum=NAD83 +units=m"
HAWAII = "+proj=aea +lat_1=8 +lat_2=18 +lat_0=13 +lon_0=-157 +datum=NAD83 +units=m"

# Output space: a 975 x 610 map at 10 units per pixel, coordinates to 0.1 unit,
# so the lines stay sharp when zoomed in on dense city districts.
WIDTH, HEIGHT = 9750, 6100
MARGIN = 100
SIMPLIFY = 1  # coverage simplification tolerance in output units (about 500 m in the lower 48)
MIN_PART = 40  # drop islands smaller than this many square units unless they are a district's only part
# Total length of a district's edges that may miss its neighbors' (under half
# a pixel). The 120th's shoreline clip leaves a few such slivers (under 1 unit).
MAX_MISMATCH = 5
ALASKA_SCALE = 0.35  # Alaska is drawn at about a third of its size, as on most US maps

# City labels by 2024 population: tier 1 on the whole map, the others once
# zoomed in (site/assets/js/district-map.js sets the zoom levels).
LABEL_TIERS = [(700_000, 1), (250_000, 2), (100_000, 3)]
# Places listed for a district: the largest by estimated population inside it,
# counting a place only where at least this share of its area falls in the district.
PLACES_SHOWN = 8
MIN_PLACE_SHARE = 0.02


def fetch(url):
    """Returns the zip at url, downloading it once into the cache."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / url.rsplit("/", 1)[1]
    if not path.exists():
        print(f"downloading {url}", file=sys.stderr)
        part = path.with_name(path.name + ".part")  # a failed download never leaves a cached file
        with urllib.request.urlopen(url, timeout=120) as r:
            part.write_bytes(r.read())
        part.replace(path)
    return path


def read_shapes(url):
    """Yields (record dict, shapely geometry in lon/lat) for each feature in the zipped shapefile."""
    with zipfile.ZipFile(fetch(url)) as z:
        names = z.namelist()
        part = lambda ext: io.BytesIO(z.read(next(n for n in names if n.endswith(ext))))
        reader = shapefile.Reader(shp=part(".shp"), shx=part(".shx"), dbf=part(".dbf"))
        for sr in reader.iterShapeRecords():
            yield sr.record.as_dict(), shape(sr.shape.__geo_interface__)


def projector(state):
    """Returns a function mapping a lon/lat geometry to output coordinates for that state."""
    proj = {"AK": ALASKA, "HI": HAWAII}.get(state, CONUS)
    to_m = Transformer.from_crs("EPSG:4269", proj, always_xy=True).transform
    # The western Aleutians lie past 180° but stay beside the rest of Alaska: PROJ
    # measures longitude from the projection's central meridian, wrapped to ±180°.
    return lambda geom: shapely.transform(geom, lambda c: np.column_stack(to_m(c[:, 0], c[:, 1])))


def place(geom, scale, left, top, bounds):
    """Scales a projected geometry and moves its top-left corner to (left, top), y down."""
    minx, _, _, maxy = bounds
    return shapely.transform(geom, lambda c: np.column_stack([left + (c[:, 0] - minx) * scale,
                                                              top + (maxy - c[:, 1]) * scale]))


def polygons(geom):
    """The polygons in a geometry, including those inside a collection's multipolygons."""
    return [p for part in shapely.get_parts(geom) for p in shapely.get_parts(part) if isinstance(p, Polygon)]


def tidy(geom):
    """Drops small islands from a simplified geometry (keeping the largest part)."""
    parts = sorted(polygons(geom), key=lambda p: -p.area)
    return [p for i, p in enumerate(parts) if i == 0 or p.area >= MIN_PART]


def check_coverage(seats, areas):
    """Stops the build if drawn districts overlap or their shared edges don't match.

    coverage_simplify leaves such edges as they are instead of failing, so each
    side would be drawn as its own line. Islands tidy() drops aren't checked.
    """
    edges = shapely.coverage_invalid_edges([MultiPolygon(tidy(a)) for a in areas])
    bad = [f"{s}-{n}" for (s, n), e in zip(seats, edges) if e.length >= MAX_MISMATCH]
    if bad:
        sys.exit(f"districts overlap or don't fit their neighbors: {', '.join(bad)}")


def path_data(parts):
    """SVG path data for polygons: one decimal, relative moves after each ring's first point."""
    return "".join(line_data(ring.coords[:-1], closed=True)
                   for poly in parts for ring in [poly.exterior, *poly.interiors])


def line_data(coords, closed=False):
    pts = [(round(x, 1), round(y, 1)) for x, y in coords]
    pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    if closed and len(pts) > 1 and pts[-1] == pts[0]:
        pts.pop()  # "z" closes the ring; a last point on the first would repeat it
    if len(pts) < (3 if closed else 2):
        return ""
    seg = [f"M{fmt(pts[0][0])} {fmt(pts[0][1])}l"]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg.append(f"{fmt(x1 - x0)} {fmt(y1 - y0)} ")
    return "".join(seg).rstrip() + ("z" if closed else "")


def lines(geom):
    if geom.geom_type == "LineString":
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if g.geom_type == "LineString"]


def fmt(v):
    s = f"{round(v, 1):.1f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def load_states():
    """Returns {state: lon/lat geometry} for the 50 states, clipped to the shoreline."""
    return {STATE_FIPS[r["STATEFP"]]: g for r, g in read_shapes(STATES_FILE) if r["STATEFP"] in STATE_FIPS}


def load_places():
    """Returns [(state, name, 2024 population, lon/lat geometry)] for incorporated places in the 50 states."""
    import csv

    with open(fetch(POPULATION_FILE), encoding="latin-1", newline="") as f:
        pop = {r["STATE"] + r["PLACE"]: int(r["POPESTIMATE2024"])
               for r in csv.DictReader(f) if r["SUMLEV"] == "162"}
    return [(STATE_FIPS[r["STATEFP"]], r["NAME"], pop[r["GEOID"]], g)
            for r, g in read_shapes(PLACES_FILE)
            if r["STATEFP"] in STATE_FIPS and r["GEOID"] in pop and not g.is_empty]


def place_lists(drawn_full, places_placed):
    """For each district, the names of its largest places (by population inside
    it, estimated from the share of the place's area) and how many more there are."""
    tree = shapely.STRtree([p[3] for p in places_placed])
    out = []
    for state, _, geom in drawn_full:
        geom = shapely.make_valid(geom)
        found = []
        for i in tree.query(geom, predicate="intersects"):
            p_state, name, pop, pgeom = places_placed[i]
            if p_state != state or pgeom.area == 0:
                continue
            share = pgeom.intersection(geom).area / pgeom.area
            if share >= MIN_PLACE_SHARE:
                found.append((pop * share, name))
        names = [n for _, n in sorted(found, key=lambda t: (-t[0], t[1]))]
        out.append((names[:PLACES_SHOWN], max(0, len(names) - PLACES_SHOWN)))
    return out


def city_labels(places_placed):
    """[{name, x, y, tier}] for places big enough to label, largest first. A name
    labeled in more than one state gets its state ("Kansas City, MO")."""
    labels = []
    for state, name, pop, geom in sorted(places_placed, key=lambda p: (-p[2], p[1])):
        tier = next((t for floor, t in LABEL_TIERS if pop >= floor), None)
        if tier is None:
            break
        pt = geom.representative_point()
        labels.append({"state": state, "name": name, "x": round(pt.x, 1), "y": round(pt.y, 1), "tier": tier})
    repeated = {n for n in (l["name"] for l in labels) if sum(l["name"] == n for l in labels) > 1}
    for label in labels:
        state = label.pop("state")
        if label["name"] in repeated:
            label["name"] += f", {state}"
    return labels


def load_districts(congress, states):
    """Returns [(state, district number, lon/lat geometry)]; 0 is an at-large seat."""
    keep = KEEP_119.get(congress, set())
    # Clipped to the whole shoreline, not each state's own outline: the state file
    # draws state lines a little differently from TIGER/Line, so per-state clips
    # would leave slivers of gap and overlap between neighboring states.
    land = unary_union(list(states.values())) if congress != 119 else None
    rows = []
    for url in DISTRICT_FILES[congress]:
        for r, g in read_shapes(url):
            state = STATE_FIPS.get(r["STATEFP"])
            code = r[f"CD{congress}FP"]
            if state is None or state in keep or not code.isdigit():  # "ZZ": water with no district
                continue
            if congress != 119:  # TIGER/Line runs out into the water; clip to the shoreline
                g = g.buffer(0).intersection(land)
            rows.append((state, int(code), g))
    for url in DISTRICT_FILES[119] if keep else []:
        for r, g in read_shapes(url):
            if STATE_FIPS.get(r["STATEFP"]) in keep:
                rows.append((STATE_FIPS[r["STATEFP"]], int(r["CD119FP"]), g))
    by_seat = {}
    for state, n, g in rows:  # a district can come as several records
        by_seat.setdefault((state, n), []).append(g)
    return [(s, n, unary_union(gs)) for (s, n), gs in sorted(by_seat.items())]


def build(congress):
    states = load_states()
    districts = load_districts(congress, states)

    # Project everything, fit the lower 48 to the frame, and inset Alaska and
    # Hawaii in the lower left. Each region: (scale, left, top, projected bounds).
    states_m = {s: projector(s)(g) for s, g in states.items()}
    districts_m = [(s, n, projector(s)(g)) for s, n, g in districts]
    conus_bounds = unary_union([g for s, g in states_m.items() if s not in ("AK", "HI")]).bounds
    minx, miny, maxx, maxy = conus_bounds
    scale = min((WIDTH - 2 * MARGIN) / (maxx - minx), (HEIGHT - 2 * MARGIN) / (maxy - miny))
    region = {"CONUS": (scale, MARGIN, MARGIN, conus_bounds)}
    ak_b = states_m["AK"].bounds
    region["AK"] = (scale * ALASKA_SCALE, MARGIN, HEIGHT - MARGIN - (ak_b[3] - ak_b[1]) * scale * ALASKA_SCALE, ak_b)
    # Place Hawaii by its main islands; the Northwestern Hawaiian Islands are
    # too small to draw but would otherwise push the inset far to the right.
    hi_b = MultiPolygon([p for p in polygons(states_m["HI"]) if p.area > 1e8]).bounds
    region["HI"] = (scale, MARGIN + (ak_b[2] - ak_b[0]) * scale * ALASKA_SCALE + 150,
                    HEIGHT - MARGIN - (hi_b[3] - hi_b[1]) * scale, hi_b)

    def placed_full(state, geom_m):
        s, left, top, bounds = region.get(state, region["CONUS"])
        return place(geom_m, s, left, top, bounds)

    full = [(s, n, placed_full(s, g)) for s, n, g in districts_m]
    # Simplified together, so an edge two districts share (a state border too)
    # is simplified once: both sides keep the same points and it's drawn once.
    areas = [MultiPolygon(polygons(shapely.make_valid(g))) for _, _, g in full]
    check_coverage([(s, n) for s, n, _ in full], areas)
    simple = shapely.coverage_simplify(areas, SIMPLIFY)
    drawn = [(s, n, tidy(g)) for (s, n, _), g in zip(full, simple)]
    places = [(s, name, pop, shapely.make_valid(placed_full(s, projector(s)(g)))) for s, name, pop, g in load_places()]
    listed = place_lists(full, places)
    # Borders between states, taken from the drawn districts so they line up
    # exactly. Coastlines are already district edges, so they're left out here.
    by_state = {}
    for s, _, parts in drawn:
        by_state.setdefault(s, []).extend(parts)
    outlines = [unary_union(parts).buffer(0) for parts in by_state.values()]
    coast = unary_union(outlines).boundary.buffer(1)
    borders = unary_union([o.boundary for o in outlines]).difference(coast)
    borders = shapely.line_merge(borders)

    doc = {
        "congress": congress,
        "width": WIDTH,
        "height": HEIGHT,
        "borders": "".join(line_data(line.coords) for line in lines(borders)),
        "cities": city_labels(places),
        "districts": [{"state": s, "district": n, "places": names, "more_places": more, "d": path_data(p)}
                      for (s, n, p), (names, more) in zip(drawn, listed)],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{congress}.json"
    path.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    print(f"wrote {path.relative_to(ROOT)}: {len(doc['districts'])} districts, {path.stat().st_size // 1024} KB",
          file=sys.stderr)


if __name__ == "__main__":
    for arg in sys.argv[1:] or ["119", "120"]:
        build(int(arg))
