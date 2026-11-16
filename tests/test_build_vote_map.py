import importlib.util
from pathlib import Path

import pytest
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Polygon, box

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_vote_map.py"
spec = importlib.util.spec_from_file_location("build_vote_map", SCRIPT)
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)


def square(x, y, size):
    """Path data for a square, in the source's absolute-move, relative-lines form."""
    return f"M{x} {y}l{size} 0 0 {size} {-size} 0z"


# parse_path

def test_parse_path_reads_one_ring():
    geom = vm.parse_path(square(0, 0, 100))
    assert geom.geom_type == "Polygon"
    assert geom.area == 10000
    assert geom.bounds == (0, 0, 100, 100)


def test_parse_path_reads_negative_and_decimal_coordinates():
    geom = vm.parse_path("M-10.5 -20l10.5 0 0 20 -10.5 0z")
    assert geom.bounds == (-10.5, -20, 0, 0)


def test_parse_path_ring_inside_another_is_a_hole():
    geom = vm.parse_path(square(0, 0, 100) + square(25, 25, 50))
    assert geom.area == 10000 - 2500
    assert len(geom.interiors) == 1


def test_parse_path_island_inside_a_hole_is_filled():
    # Even-odd: outer filled, the ring inside it a hole, the ring inside that filled again.
    geom = vm.parse_path(square(0, 0, 100) + square(20, 20, 60) + square(40, 40, 20))
    assert geom.area == 10000 - 3600 + 400


def test_parse_path_separate_rings_make_a_multipolygon():
    geom = vm.parse_path(square(0, 0, 10) + square(50, 50, 10))
    assert geom.geom_type == "MultiPolygon"
    assert len(geom.geoms) == 2
    assert geom.area == 200


def test_parse_path_skips_a_subpath_with_fewer_than_three_points():
    geom = vm.parse_path("M0 0l5 5z" + square(0, 0, 10))
    assert geom.area == 100


# path_data

def test_path_data_scales_and_writes_relative_lines():
    geom = Polygon([(0, 0), (100, 0), (100, 50), (0, 50)])
    assert vm.path_data(geom) == "M0 0l20 0 0 10 -20 0z"


def test_path_data_rounds_to_whole_output_units():
    # 12 / 5 = 2.4 rounds to 2; 13 / 5 = 2.6 rounds to 3.
    geom = Polygon([(0, 0), (12, 0), (12, 13), (0, 13)])
    assert vm.path_data(geom) == "M0 0l2 0 0 3 -2 0z"


def test_path_data_drops_points_that_round_onto_the_one_before():
    geom = Polygon([(0, 0), (1, 0), (50, 0), (50, 50), (0, 50)])
    assert vm.path_data(geom) == "M0 0l10 0 0 10 -10 0z"


def test_path_data_drops_a_ring_that_rounds_to_fewer_than_three_points():
    geom = MultiPolygon([box(0, 0, 2, 2), Polygon([(0, 0), (50, 0), (50, 50), (0, 50)])])
    assert vm.path_data(geom) == "M0 0l10 0 0 10 -10 0z"


def test_path_data_writes_holes_as_their_own_rings():
    geom = Polygon(
        [(0, 0), (100, 0), (100, 100), (0, 100)],
        [[(25, 25), (25, 75), (75, 75), (75, 25)]],
    )
    assert vm.path_data(geom) == "M0 0l20 0 0 20 -20 0zM5 5l0 10 10 0 0 -10z"


def test_path_data_skips_parts_that_are_not_polygons():
    geom = GeometryCollection([LineString([(0, 0), (100, 100)]), box(0, 0, 50, 50)])
    assert vm.path_data(geom).count("M") == 1


def test_path_data_round_trips_through_parse_path():
    geom = vm.parse_path(square(0, 0, 500) + square(100, 100, 100) + square(600, 0, 50))
    back = vm.parse_path(vm.path_data(geom))
    assert back.area == geom.area / vm.SCALE**2
    assert back.symmetric_difference(
        vm.parse_path(square(0, 0, 100) + square(20, 20, 20) + square(120, 0, 10))
    ).area == 0


# outline

def test_outline_closes_a_hairline_gap_between_districts():
    parts = [box(0, 0, 100, 100), box(101, 0, 201, 100)]
    state = vm.outline(parts)
    assert len(state.geoms) == 1
    assert state.area == pytest.approx(201 * 100)


def test_outline_keeps_districts_apart_across_a_real_gap():
    parts = [box(0, 0, 100, 100), box(110, 0, 210, 100)]
    assert len(vm.outline(parts).geoms) == 2


def test_outline_drops_holes_smaller_than_min_hole():
    big, small = box(100, 100, 200, 200), box(500, 500, 540, 540)
    assert big.area >= vm.MIN_HOLE > small.area
    parts = [box(0, 0, 1000, 1000).difference(big).difference(small)]
    (state,) = vm.outline(parts).geoms
    assert len(state.interiors) == 1
    assert Polygon(state.interiors[0]).area == pytest.approx(big.area)


def test_outline_is_a_multipolygon_for_a_one_part_state():
    assert vm.outline([box(0, 0, 100, 100)]).geom_type == "MultiPolygon"
