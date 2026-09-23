"""The five toy clusters, the two toy profiles, and a graph-aware mock.

Imported by `tests/*` as plain fixtures. Everything here is fictional; see the
header of any file under `fixtures/`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from graphsearch import paths_root

paths_root.ensure_importable()

# heteropilot's mock, loaded by `conftest` under a non-clashing module name.
# Imported here rather than re-derived: its roofline consistency with the
# bounds is what makes an oracle-agreement failure mean something.
import hp_conftest  # noqa: E402
from planner.inventory import (  # noqa: E402
    AcceleratorProfile,
    ClusterSpecV2,
    ExecutionIsland,
    detect_islands,
    load_accelerator_profile,
    load_cluster_spec,
    load_profiles_for,
)
from planner.spec import ServiceSpec, load_service_spec  # noqa: E402

_MOCK_BASE = hp_conftest.MockPredictor

ROOT = paths_root.GRAPHSEARCH_ROOT
FIXTURES = ROOT / "fixtures"

#: Every committed toy cluster, so a test can sweep them.
CLUSTER_FILES = {
    "abcde": FIXTURES / "clusters/graph-toy-abcde.yaml",
    "abcde_v2": FIXTURES / "clusters/graph-toy-abcde.v2.yaml",
    "shared_nic": FIXTURES / "clusters/graph-toy-shared-nic.yaml",
    "shared_nic_v2": FIXTURES / "clusters/graph-toy-shared-nic.v2.yaml",
    "asym_v2": FIXTURES / "clusters/graph-toy-asym.v2.yaml",
}


def load_toy_cluster(name: str) -> ClusterSpecV2:
    return load_cluster_spec(CLUSTER_FILES[name])


def toy_profiles_for(cluster: ClusterSpecV2) -> dict[str, AcceleratorProfile]:
    """Profiles resolve against THIS repo's root, not heteropilot's.

    The fixtures name `fixtures/profiles/*.yaml`, which only exists here.
    """
    return load_profiles_for(cluster, ROOT)


@pytest.fixture
def toy_cluster() -> ClusterSpecV2:
    return load_toy_cluster("abcde")


@pytest.fixture
def toy_cluster_v2() -> ClusterSpecV2:
    return load_toy_cluster("abcde_v2")


@pytest.fixture
def toy_shared_cluster() -> ClusterSpecV2:
    return load_toy_cluster("shared_nic")


@pytest.fixture
def toy_shared_cluster_v2() -> ClusterSpecV2:
    return load_toy_cluster("shared_nic_v2")


@pytest.fixture
def toy_asym_cluster() -> ClusterSpecV2:
    return load_toy_cluster("asym_v2")


@pytest.fixture
def toy_profiles(toy_cluster: ClusterSpecV2) -> dict[str, AcceleratorProfile]:
    return toy_profiles_for(toy_cluster)


@pytest.fixture
def toy_islands(toy_cluster, toy_profiles) -> list[ExecutionIsland]:
    return detect_islands(toy_cluster, toy_profiles)


@pytest.fixture
def toy_spec() -> ServiceSpec:
    return load_service_spec(FIXTURES / "service_specs/graph-toy-llama31-8b.yaml")


def toy_profile(name: str) -> AcceleratorProfile:
    return load_accelerator_profile(FIXTURES / "profiles" / f"{name}.yaml")


def profile_path(name: str) -> Path:
    return FIXTURES / "profiles" / f"{name}.yaml"


class GraphAwareMockPredictor(_MOCK_BASE):
    """Deterministic mock that can see WHERE a candidate was placed.

    heteropilot's `MockPredictor` derives latency from the real weight and KV
    sizes and the profile's memory bandwidth, so it respects the same physics as
    the bounds. That property is load-bearing -- a mock that can beat a bound
    makes the oracle-agreement test fail for reasons unrelated to the search --
    so this subclasses it rather than replacing it, and only ADDS communication
    time on top.

    Until G5 binds embeddings this behaves exactly like its base. From G5:

        TTFT = base TTFT + sum over PD_KV_TRANSFER flows of
               bytes / (path bottleneck - external reservation)
        TPOT = base TPOT + TP all-reduce time on the flow's path bottleneck

    Both are additions to an already-roofline-bounded figure, so the result is
    never faster than the bound that admitted it.
    """

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        #: template id -> the embedding whose placement to price. Empty means
        #: "no placement known", which is the base class's behaviour.
        self._embeddings: dict = {}

    def bind_embeddings(self, by_template_id: dict) -> None:
        """Tell the mock which placement each template was evaluated at.

        Filled in at G5, when `EmbeddedCandidate` exists. Binding an empty dict
        clears it.
        """
        self._embeddings = dict(by_template_id)
