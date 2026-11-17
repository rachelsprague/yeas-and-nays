import importlib.util
import json
import re
from pathlib import Path

import pytest
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon, box

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_district_map.py"
spec = importlib.util.spec_from_file_location("build_district_map", SCRIPT)
dm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dm)


def path_points(d):
    """Each subpath's points in path data written by line_data (closed or open)."""
    out = []
    for start, rest in re.findall(r"M([^l]+)l([^Mz]*)", d):
        x, y = map(float, start.split())
        pts = [(x, y)]
        steps = list(map(float, rest.split()))
        for dx, dy in zip(steps[::2], steps[1::2]):
            x, y = x + dx, y + dy
            pts.append((x, y))
        out.append(pts)
    return out


def path_bounds(d):
    """(minx, miny, maxx, maxy) of every point in path data written by path_data."""
    xs, ys = zip(*(p for ring in path_points(d) for p in ring))
    return min(xs), min(ys), max(xs), max(ys)


# fmt, line_data, path_data

def test_fmt_drops_trailing_zeros_and_negative_zero():
    assert dm.fmt(2.0) == "2"
    assert dm.fmt(3.10) == "3.1"
    assert dm.fmt(-0.04) == "0"
    assert dm.fmt(-1.26) == "-1.3"


def test_line_data_writes_an_absolute_move_then_relative_lines():
    assert dm.line_data([(10, 20), (15, 20), (15, 30.5)]) == "M10 20l5 0 0 10.5"


def test_line_data_rounds_to_one_decimal():
    assert dm.line_data([(0.04, 0), (1.26, 0)]) == "M0 0l1.3 0"


def test_line_data_drops_points_that_round_onto_the_one_before():
    assert dm.line_data([(0, 0), (0.02, 0), (5, 0)]) == "M0 0l5 0"


def test_line_data_needs_two_points_open_and_three_closed():
    assert dm.line_data([(0, 0), (0.01, 0.01)]) == ""
    assert dm.line_data([(0, 0), (5, 0)], closed=True) == ""
    assert dm.line_data([(0, 0), (5, 0), (5, 5)], closed=True) == "M0 0l5 0 0 5z"


def test_line_data_drops_a_closing_point_that_rounds_onto_the_first():
    assert dm.line_data([(0, 0), (5, 0), (5, 5), (0.02, 0.01)], closed=True) == "M0 0l5 0 0 5z"
    # An open line keeps it: there is no "z" to draw that last step.
    assert dm.line_data([(0, 0), (5, 0), (5, 5), (0.02, 0.01)]) == "M0 0l5 0 0 5 -5 -5"


def test_line_data_skips_a_ring_left_with_two_points_once_the_closing_point_is_dropped():
    assert dm.line_data([(0, 0), (5, 0), (0.01, 0)], closed=True) == ""


def test_path_data_writes_each_ring_once_closed():
    poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    assert dm.path_data([poly]) == "M0 0l10 0 0 10 -10 0z"


def test_path_data_writes_holes_and_parts_as_their_own_rings():
    holed = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(2, 2), (4, 2), (4, 4)]])
    island = Polygon([(20, 0), (22, 0), (22, 2)])
    assert dm.path_data([holed, island]) == "M0 0l10 0 0 10 -10 0zM2 2l2 0 0 2zM20 0l2 0 0 2z"


def test_path_data_skips_a_ring_that_rounds_to_fewer_than_three_points():
    sliver = Polygon([(0, 0), (0.01, 0), (0.01, 0.01)])
    poly = Polygon([(0, 0), (10, 0), (10, 10)])
    assert dm.path_data([sliver, poly]) == "M0 0l10 0 0 10z"


# polygons, tidy

def test_polygons_keeps_only_polygon_parts():
    a, b = box(0, 0, 1, 1), box(2, 2, 3, 3)
    assert dm.polygons(a) == [a]
    assert dm.polygons(MultiPolygon([a, b])) == [a, b]
    assert dm.polygons(GeometryCollection([a, LineString([(0, 0), (1, 1)]), Point(5, 5)])) == [a]
    # A clip can return a collection holding a multipolygon.
    assert dm.polygons(GeometryCollection([MultiPolygon([a, b]), LineString([(0, 0), (1, 1)])])) == [a, b]


def test_tidy_drops_small_islands_and_puts_the_largest_part_first():
    main, island, speck = box(0, 0, 100, 100), box(200, 0, 210, 10), box(300, 0, 302, 2)
    parts = dm.tidy(MultiPolygon([speck, island, main]))
    assert [p.area for p in parts] == [10000, 100]


def test_tidy_keeps_a_district_whose_only_part_is_small():
    parts = dm.tidy(box(0, 0, 2, 2))
    assert [p.area for p in parts] == [4]


# projector, place

def test_projector_centers_the_lower_48_on_its_origin():
    pt = dm.projector("TX")(Point(-96, 37.5))
    assert abs(pt.x) < 1e-6 and abs(pt.y) < 1e-6


def test_projector_keeps_the_western_aleutians_beside_alaska():
    to_ak = dm.projector("AK")
    east_of_180, west_of_180 = to_ak(Point(-179, 52)), to_ak(Point(179, 52))
    # 179°E is 2° west of 179°W, so it lands just left of it, not across the map.
    assert west_of_180.x < east_of_180.x
    assert east_of_180.x - west_of_180.x < 200_000


def test_place_scales_and_moves_the_top_left_corner_with_y_down():
    geom = box(10, 20, 30, 60)
    placed = dm.place(geom, 2, 100, 50, geom.bounds)
    assert placed.bounds == (100, 50, 140, 130)
    # The north edge (y = 60) is at the top.
    north = dm.place(Point(10, 60), 2, 100, 50, geom.bounds)
    assert (north.x, north.y) == (100, 50)


# place_lists

def test_place_lists_ranks_places_by_population_inside_the_district():
    district = box(0, 0, 10, 10)
    places = [
        ("TX", "Half In", 1000, box(5, 0, 15, 10)),  # half its area inside: counts as 500
        ("TX", "Small", 600, box(1, 1, 2, 2)),
        ("TX", "Outside", 9000, box(20, 20, 30, 30)),
    ]
    assert dm.place_lists([("TX", 1, district)], places) == [(["Small", "Half In"], 0)]


def test_place_lists_skips_places_in_another_state_or_barely_inside():
    district = box(0, 0, 10, 10)
    places = [
        ("OK", "Across the Line", 5000, box(1, 1, 2, 2)),
        ("TX", "Edge", 5000, box(9.9, 0, 19.9, 10)),  # 1% inside, under MIN_PLACE_SHARE
        ("TX", "Line", 5000, LineString([(1, 1), (2, 2)])),  # no area
        ("TX", "Town", 10, box(3, 3, 4, 4)),
    ]
    assert dm.place_lists([("TX", 1, district)], places) == [(["Town"], 0)]


def test_place_lists_shows_the_largest_and_counts_the_rest(monkeypatch):
    monkeypatch.setattr(dm, "PLACES_SHOWN", 2)
    district = box(0, 0, 10, 10)
    places = [("TX", name, pop, box(i, 0, i + 1, 1))
              for i, (name, pop) in enumerate([("A", 10), ("B", 30), ("C", 20), ("D", 30)])]
    # B and D tie and are ordered by name.
    assert dm.place_lists([("TX", 1, district)], places) == [(["B", "D"], 2)]


# city_labels

def test_city_labels_tiers_by_population_and_stops_below_the_last_tier():
    places = [
        ("TX", "Mid", 300_000, box(0, 0, 2, 2)),
        ("TX", "Big", 800_000, box(10, 10, 12, 12)),
        ("TX", "Small", 150_000, box(20, 20, 22, 22)),
        ("TX", "Tiny", 99_999, box(30, 30, 32, 32)),
    ]
    assert dm.city_labels(places) == [
        {"name": "Big", "x": 11, "y": 11, "tier": 1},
        {"name": "Mid", "x": 1, "y": 1, "tier": 2},
        {"name": "Small", "x": 21, "y": 21, "tier": 3},
    ]


def test_city_labels_add_the_state_to_a_name_labeled_twice():
    places = [
        ("MO", "Kansas City", 510_000, box(0, 0, 2, 2)),
        ("KS", "Kansas City", 155_000, box(4, 0, 6, 2)),
        ("TX", "Austin", 990_000, box(10, 10, 12, 12)),
    ]
    assert [label["name"] for label in dm.city_labels(places)] == [
        "Austin", "Kansas City, MO", "Kansas City, KS"]


# load_districts

def _shapes(files):
    """A stub read_shapes serving files[url] as (record, geometry) pairs."""
    return lambda url: iter(files[url])


def test_load_districts_skips_water_and_non_states_and_joins_split_records(monkeypatch):
    monkeypatch.setattr(dm, "DISTRICT_FILES", {119: ["cd119"]})
    monkeypatch.setattr(dm, "read_shapes", _shapes({"cd119": [
        ({"STATEFP": "48", "CD119FP": "02"}, box(0, 0, 1, 1)),
        ({"STATEFP": "48", "CD119FP": "01"}, box(1, 0, 2, 1)),
        ({"STATEFP": "48", "CD119FP": "02"}, box(0, 1, 1, 2)),  # a second record for TX-2
        ({"STATEFP": "48", "CD119FP": "ZZ"}, box(5, 5, 6, 6)),  # water
        ({"STATEFP": "11", "CD119FP": "98"}, box(7, 7, 8, 8)),  # DC: not drawn
        ({"STATEFP": "02", "CD119FP": "00"}, box(9, 9, 10, 10)),  # at large
    ]}))
    rows = dm.load_districts(119, states={})
    assert [(s, n) for s, n, _ in rows] == [("AK", 0), ("TX", 1), ("TX", 2)]
    assert rows[2][2].area == 2


def test_load_districts_clips_a_later_congress_to_the_shoreline(monkeypatch):
    monkeypatch.setattr(dm, "DISTRICT_FILES", {119: ["cd119"], 120: ["tx120"]})
    monkeypatch.setattr(dm, "read_shapes", _shapes({"tx120": [
        ({"STATEFP": "48", "CD120FP": "01"}, box(0, 0, 10, 10)),
    ]}))
    rows = dm.load_districts(120, states={"TX": box(0, 0, 10, 6)})
    assert rows[0][2].area == 60


def test_load_districts_clips_to_the_whole_shoreline_not_the_states_own_outline(monkeypatch):
    # The state file draws the Texas line a little west of TIGER/Line's; the
    # district keeps TIGER/Line's edge, so it meets its neighbor with no gap.
    monkeypatch.setattr(dm, "DISTRICT_FILES", {119: ["cd119"], 120: ["tx120"]})
    monkeypatch.setattr(dm, "read_shapes", _shapes({"tx120": [
        ({"STATEFP": "48", "CD120FP": "01"}, box(0, 0, 10, 10)),
    ]}))
    rows = dm.load_districts(120, states={"TX": box(0, 0, 9, 12), "OK": box(9, 0, 20, 12)})
    assert rows[0][2].area == 100


def test_load_districts_takes_a_kept_state_from_the_119th_file(monkeypatch):
    monkeypatch.setattr(dm, "DISTRICT_FILES", {119: ["cd119"], 120: ["mo120", "tx120"]})
    monkeypatch.setattr(dm, "KEEP_119", {120: {"MO"}})
    monkeypatch.setattr(dm, "read_shapes", _shapes({
        "cd119": [({"STATEFP": "29", "CD119FP": "01"}, box(0, 0, 1, 1)),
                  ({"STATEFP": "48", "CD119FP": "01"}, box(5, 5, 6, 6))],
        "mo120": [({"STATEFP": "29", "CD120FP": "01"}, box(0, 0, 3, 3))],
        "tx120": [({"STATEFP": "48", "CD120FP": "01"}, box(5, 5, 7, 7))],
    }))
    states = {"MO": box(0, 0, 10, 10), "TX": box(0, 0, 10, 10)}
    rows = dm.load_districts(120, states)
    assert [(s, n, g.area) for s, n, g in rows] == [("MO", 1, 1), ("TX", 1, 4)]


# build

# The Texas-New Mexico line, jagged (as real borders are) by about the
# simplification tolerance, so simplifying each district on its own would keep
# different points on each side of it.
SHARED_EDGE = [(-106 + 0.002 * ((i * 7919) % 101 / 50 - 1), 31 + i * 0.01) for i in range(501)]
STATES = {
    "WA": box(-125, 45, -117, 49),  # widens the lower 48, so the insets are clear of Texas
    "TX": Polygon([(-106, 26), (-94, 26), (-94, 36), *reversed(SHARED_EDGE), (-106, 31)]),
    "NM": Polygon([(-109, 31), *SHARED_EDGE, (-106, 37), (-109, 37)]),
    "ME": box(-71, 43, -67, 47),
    # Alaska and Hawaii centered on their projections' central meridians (154°W, 157°W),
    # so each one's top corners are level when drawn in its own projection.
    "AK": box(-168, 55, -140, 70),
    # Hawaii's main islands, and a Northwestern Hawaiian island far to the west.
    "HI": MultiPolygon([box(-159.5, 19, -154.5, 22), box(-176.01, 25, -176, 25.01)]),
}
PLACES = [
    ("TX", "Big City", 800_000, box(-98, 30, -97, 31)),
    ("NM", "Town", 5_000, box(-108, 33, -107.9, 33.1)),
]


def one_district_each(congress, states):
    return [(st, 1, g) for st, g in sorted(states.items())]


def build_doc(monkeypatch, tmp_path, load_districts=one_district_each):
    """Runs build() on STATES (one district each by default) and PLACES, and returns the written map."""
    monkeypatch.setattr(dm, "load_states", lambda: STATES)
    monkeypatch.setattr(dm, "load_districts", load_districts)
    monkeypatch.setattr(dm, "load_places", lambda: PLACES)
    monkeypatch.setattr(dm, "OUT", tmp_path)
    monkeypatch.setattr(dm, "ROOT", tmp_path)
    dm.build(119)
    return json.loads((tmp_path / "119.json").read_text())


def test_build_fits_the_lower_48_and_insets_alaska_and_hawaii(monkeypatch, tmp_path):
    doc = build_doc(monkeypatch, tmp_path)
    bounds = {d["state"]: path_bounds(d["d"]) for d in doc["districts"]}
    margin, width, height = dm.MARGIN, dm.WIDTH, dm.HEIGHT
    near = lambda a, b: abs(a - b) <= 1

    # The lower 48 starts at the top-left margin and fills the frame in one direction.
    lower48 = ("WA", "TX", "NM", "ME")
    conus = (min(bounds[s][0] for s in lower48), min(bounds[s][1] for s in lower48),
             max(bounds[s][2] for s in lower48), max(bounds[s][3] for s in lower48))
    assert near(conus[0], margin) and near(conus[1], margin)
    assert conus[2] <= width - margin + 1 and conus[3] <= height - margin + 1
    assert near(conus[2], width - margin) or near(conus[3], height - margin)

    # Alaska sits in the lower-left corner; Hawaii's main islands 150 units to its right, on
    # the bottom margin (placing by the western island too would push them further right).
    ak, hi = bounds["AK"], bounds["HI"]
    assert near(ak[0], margin) and near(ak[3], height - margin)
    assert near(hi[0], ak[2] + 150) and near(hi[3], height - margin)


def test_build_draws_alaska_and_hawaii_in_their_own_projections(monkeypatch, tmp_path):
    doc = build_doc(monkeypatch, tmp_path)
    for d in doc["districts"]:
        if d["state"] in ("AK", "HI"):
            [ring] = path_points(d["d"])  # Hawaii's small western island is dropped
            top = sorted(ring, key=lambda p: p[1])[:2]
            # Level in its own projection; tilted by hundreds of units in the lower 48's.
            assert abs(top[0][1] - top[1][1]) <= 1, d["state"]
            assert abs(top[0][0] - top[1][0]) > 100, d["state"]


def test_build_draws_state_borders_but_not_coastlines(monkeypatch, tmp_path):
    doc = build_doc(monkeypatch, tmp_path)
    rings = {d["state"]: Polygon(path_points(d["d"])[0]) for d in doc["districts"]}
    border = [Point(p) for line in path_points(doc["borders"]) for p in line]
    # Only the Texas-New Mexico line: every point on both states' edges, none on Maine's.
    assert len(border) >= 2
    assert all(rings["TX"].boundary.distance(p) <= 1 and rings["NM"].boundary.distance(p) <= 1 for p in border)
    # It runs most of the shared edge (lat 31 to 36), trimmed only where it meets the coast.
    ys = [p.y for p in border]
    tx = path_bounds(next(d["d"] for d in doc["districts"] if d["state"] == "TX"))
    assert max(ys) - min(ys) > 0.4 * (tx[3] - tx[1])


def test_build_draws_a_shared_state_border_once(monkeypatch, tmp_path):
    def split_tx_and_nm(congress, states):
        # Each state's districts meet partway along the line, at different points on each side.
        rows = [r for r in one_district_each(congress, states) if r[0] not in ("TX", "NM")]
        for st, y in (("TX", 33.27), ("NM", 34.61)):
            south = box(-110, 25, -93, y)
            rows += [(st, 1, states[st].intersection(south)), (st, 2, states[st].difference(south))]
        return rows

    doc = build_doc(monkeypatch, tmp_path, split_tx_and_nm)
    points = {}
    for d in doc["districts"]:
        points.setdefault(d["state"], set()).update(
            (round(x, 1), round(y, 1)) for ring in path_points(d["d"]) for x, y in ring)
    # Both states keep the same points along the line, so it's drawn as one line, not two side by side.
    [line] = path_points(doc["borders"])
    assert len(line) > 10
    # (Its ends are cut where it meets the coast, so they aren't vertices.)
    assert {(round(x, 1), round(y, 1)) for x, y in line[1:-1]} <= points["TX"] & points["NM"]


def test_build_writes_city_labels_and_each_districts_places(monkeypatch, tmp_path):
    doc = build_doc(monkeypatch, tmp_path)
    [label] = doc["cities"]  # Town is too small to label
    assert label["name"] == "Big City" and label["tier"] == 1
    tx = next(d for d in doc["districts"] if d["state"] == "TX")
    assert Polygon(path_points(tx["d"])[0]).contains(Point(label["x"], label["y"]))
    places = {d["state"]: (d["places"], d["more_places"]) for d in doc["districts"]}
    assert places == {"TX": (["Big City"], 0), "NM": (["Town"], 0),
                      "WA": ([], 0), "ME": ([], 0), "AK": ([], 0), "HI": ([], 0)}


def with_texas(make_tx):
    """load_districts with one district each, Texas replaced by make_tx(states)."""
    def load(congress, states):
        return [(st, n, make_tx(states) if st == "TX" else g) for st, n, g in one_district_each(congress, states)]
    return load


def test_build_stops_when_districts_overlap(monkeypatch, tmp_path):
    load = with_texas(lambda states: states["TX"].union(box(-107, 32, -105, 33)))
    with pytest.raises(SystemExit, match="overlap or don't fit their neighbors: NM-1, TX-1$"):
        build_doc(monkeypatch, tmp_path, load)
    assert not (tmp_path / "119.json").exists()


def test_build_stops_when_a_shared_edge_has_different_points_on_each_side(monkeypatch, tmp_path):
    # As if Texas came from another source file: the same line, with every other point.
    edge = SHARED_EDGE[::2]
    load = with_texas(lambda states: Polygon([(-106, 26), (-94, 26), (-94, 36), *reversed(edge), (-106, 31)]))
    with pytest.raises(SystemExit, match="NM-1, TX-1$"):
        build_doc(monkeypatch, tmp_path, load)


def test_build_ignores_an_island_too_small_to_draw_over_a_neighbor(monkeypatch, tmp_path):
    # As the Northwestern Hawaiian Islands land on the Alaska inset.
    load = with_texas(lambda states: MultiPolygon([states["TX"], box(-107.5, 34, -107.49, 34.01)]))
    doc = build_doc(monkeypatch, tmp_path, load)
    tx = next(d for d in doc["districts"] if d["state"] == "TX")
    assert len(path_points(tx["d"])) == 1
