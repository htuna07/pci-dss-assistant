"""Fusing the results of several rewritten queries must keep the best answer of every query."""

import sys

from conftest import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from search import fuse_id_rankings  # noqa: E402

LENGTH_QUERY = ["8.3.6", "8.3.5", "8.3.1", "8.3.9", "8.2.2"]
SHARED_QUERY = ["8.6.3", "8.2.2", "8.3.9", "8.6.2", "8.3.5"]


def test_plain_fusion_pushes_down_a_requirement_that_wins_only_one_query():
    fused = fuse_id_rankings([LENGTH_QUERY, SHARED_QUERY])

    assert fused.index("8.3.6") > 2


def test_reserved_places_keep_the_best_results_of_every_query():
    fused = fuse_id_rankings([LENGTH_QUERY, SHARED_QUERY], reserve=2)

    assert fused[:4] == ["8.3.6", "8.6.3", "8.3.5", "8.2.2"]


def test_reserving_places_loses_no_requirement_and_repeats_none():
    fused = fuse_id_rankings([LENGTH_QUERY, SHARED_QUERY], reserve=3)

    assert len(fused) == len(set(fused))
    assert set(fused) == set(LENGTH_QUERY) | set(SHARED_QUERY)


def test_a_ranking_shorter_than_the_reserve_is_fine():
    assert fuse_id_rankings([["a"], ["b", "c"]], reserve=3) == ["a", "b", "c"]
