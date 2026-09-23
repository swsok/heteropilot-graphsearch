"""G0: the skeleton loads. No search logic yet -- that starts at G1.

If this file fails, nothing later in the work order can be trusted, because
every other test reads these same five clusters.
"""

from __future__ import annotations

import pytest

from graphsearch import paths_root
from tests.graph_fixtures import (
    CLUSTER_FILES,
    GraphAwareMockPredictor,
    load_toy_cluster,
    toy_profiles_for,
)


def test_both_packages_import() -> None:
    """The one-way dependency, asserted rather than assumed."""
    import planner

    import graphsearch

    assert graphsearch.__file__ is not None
    assert planner.__file__ is not None
    assert paths_root.HETEROPILOT_ROOT.is_dir()


@pytest.mark.parametrize("name", sorted(CLUSTER_FILES))
def test_every_toy_cluster_loads_with_its_profiles(name: str) -> None:
    cluster = load_toy_cluster(name)
    profiles = toy_profiles_for(cluster)
    assert profiles, f"{name} resolved no profiles"


def test_island_counts_match_the_research_design() -> None:
    """§9's example cluster is five islands; the shared-NIC pair is two."""
    from planner.inventory import detect_islands

    abcde = load_toy_cluster("abcde")
    assert len(detect_islands(abcde, toy_profiles_for(abcde))) == 5

    shared = load_toy_cluster("shared_nic")
    assert len(detect_islands(shared, toy_profiles_for(shared))) == 2


def test_the_v1_and_v2_copies_describe_the_same_hardware() -> None:
    """They differ in what they can EXPRESS, not in what is there.

    The v2 file adds sockets, switches and capacities; the accelerators and
    their prices-per-model must still line up, or the two are not a pair and
    comparing a v1 result against a v2 one proves nothing.
    """
    for base, v2 in (("abcde", "abcde_v2"), ("shared_nic", "shared_nic_v2")):
        a, b = load_toy_cluster(base), load_toy_cluster(v2)
        assert a.schema_version == 1 and b.schema_version == 2
        assert [n.id for n in a.nodes] == [n.id for n in b.nodes]
        for na, nb in zip(a.nodes, b.nodes, strict=True):
            assert [x.id for x in na.accelerators] == [x.id for x in nb.accelerators]
            assert [x.model for x in na.accelerators] == [x.model for x in nb.accelerators]


def test_the_npu_profile_has_no_simulator_bundle() -> None:
    """This is how §9's "예시 runtime 미지원" rows are expressed.

    No `sim_hardware` means the generator's first stage drops every NPU pair, so
    45 device pairs become the 28 the compression example counts.
    """
    from tests.graph_fixtures import toy_profile

    assert toy_profile("toy_npu").sim_hardware is None
    assert toy_profile("toy_gpu").sim_hardware == "A5000"


def test_shared_nic_fixture_differs_only_in_the_reservation() -> None:
    """The whole point of that fixture, pinned so an edit cannot erase it."""
    cluster = load_toy_cluster("shared_nic_v2")
    reserved = {r.node: r.reserved for r in cluster.shared_resources}
    assert reserved == {"nodeX": 6.0, "nodeY": 0.0}
    caps = {r.capacity for r in cluster.shared_resources}
    assert caps == {10.0}, "capacities must match; only the reservation differs"


def test_the_asym_fixture_really_is_asymmetric() -> None:
    """If two nodes ever became alike, the compression-ratio-1.0 case is gone."""
    cluster = load_toy_cluster("asym_v2")
    caps = [r.capacity for r in cluster.shared_resources]
    prices = [n.host_price_per_hour_usd for n in cluster.nodes]
    assert len(set(caps)) == len(caps)
    assert len(set(prices)) == len(prices)


def test_the_graph_aware_mock_is_a_predictor() -> None:
    from planner.predictor import Predictor

    predictor = GraphAwareMockPredictor()
    assert isinstance(predictor, Predictor)
    assert predictor.calls == []
    predictor.bind_embeddings({})          # no placement bound: base behaviour
