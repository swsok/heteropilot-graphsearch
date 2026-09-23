"""The five toy clusters, the two toy profiles, and a graph-aware mock.

Imported by `tests/*` as plain fixtures. Everything here is fictional; see the
header of any file under `fixtures/`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from graphsearch import paths_root

paths_root.ensure_importable()

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

# heteropilot's mock, loaded by path under a non-clashing module name.
# Reused rather than re-derived: its roofline consistency with the bounds is
# what makes an oracle-agreement failure mean something. The loader lives in
# `paths_root` because `python -m graphsearch --predictor mock` needs it too,
# and a fixture module that only works under pytest cannot serve a CLI.
_MOCK_BASE: Any = paths_root.load_heteropilot_conftest().MockPredictor

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


def _allreduces(model: str) -> int:
    from graphsearch.contention import allreduces_per_token

    return allreduces_per_token(model)


class GraphAwareMockPredictor(_MOCK_BASE):
    """Deterministic mock that can see WHERE a candidate was placed.

    heteropilot's `MockPredictor` derives latency from the real weight and KV
    sizes and the profile's memory bandwidth, so it respects the same physics as
    the bounds. That property is load-bearing -- a mock that can beat a bound
    makes the oracle-agreement test fail for reasons unrelated to the search --
    so this subclasses it rather than replacing it, and only ADDS time:

        TTFT += sum over PD_KV_TRANSFER flows of
                bytes / (path bottleneck - external reservation)
        TPOT += TP all-reduce time on the flow's path bottleneck

    Both are additions to an already-roofline-bounded figure, so the result is
    never faster than the bound that admitted it -- which is the invariant that
    makes an oracle disagreement mean something.

    With nothing bound it is exactly its base class, so a test that does not
    care about placement does not have to.
    """

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        #: template id -> the embedding whose placement to price.
        self._embeddings: dict[str, object] = {}
        self._result_hook = None
        self._compile_hook = None

    def bind_embeddings(self, by_template_id: dict) -> None:
        """Tell the mock which placement each template was evaluated at.

        Keyed by TEMPLATE id because that is what a `CandidateConfig` carries
        into `predict`; the driver binds one representative exemplar per
        template before each batch.
        """
        self._embeddings = dict(by_template_id)

    def predict(self, candidate, spec, cluster, islands, profiles):
        result = super().predict(candidate, spec, cluster, islands, profiles)
        embedding = self._embeddings.get(candidate.id)
        if embedding is None or result.metrics is None:
            # Still through `_finish`: the result hook prices the P/D handoff
            # and is independent of whether this mock knows the placement.
            return self._finish(candidate, result)

        from graphsearch.contention import tp_allreduce_tpot_ms
        from graphsearch.demand import FlowKind
        from graphsearch.paths import effective_bottleneck_bytes_per_s

        graph = getattr(self, "_graph", None)
        tpot_add = 0.0
        for flow in embedding.flows:
            if not flow.allowed_paths:
                continue
            best = flow.allowed_paths[0].best
            if best is None:
                continue
            if graph is not None:
                capacity = effective_bottleneck_bytes_per_s(graph, best)
            else:
                capacity = best.bottleneck_bytes_per_s
            if capacity <= 0:
                continue
            seconds = flow.bytes_per_event / capacity + best.latency_ns / 1e9
            if flow.kind is FlowKind.TP_ALLREDUCE:
                # Through the SAME function the bound uses. Charging one
                # all-reduce per token here (which this did) put the mock below
                # the floor that admitted the candidate, and a mock faster than
                # a bound makes every oracle disagreement meaningless.
                tpot_add += (
                    tp_allreduce_tpot_ms(flow, graph, spec.model)
                    if graph is not None
                    else seconds * 1e3 * _allreduces(spec.model)
                )

        metrics = result.metrics.model_copy(
            update={
                "p50_tpot_ms": result.metrics.p50_tpot_ms + tpot_add,
                "p95_tpot_ms": result.metrics.p95_tpot_ms + tpot_add,
                "p99_tpot_ms": result.metrics.p99_tpot_ms + tpot_add,
            }
        )
        # `replace`, not a hand-built SimResult: that would silently drop
        # `artifacts` and `operating_point`, and the accuracy-domain machinery
        # reads the second one.
        from dataclasses import replace

        return self._finish(candidate, replace(result, metrics=metrics))

    def set_result_hook(self, hook) -> None:
        """The same seam heteropilot's real predictor has (D125).

        The P/D transfer is NOT added inside `predict` any more. It used to be,
        and then it was charged in two places -- here and by the driver -- which
        happened to cancel out only because the driver was subtracting
        heteropilot's figure rather than adding its own. One place charges it
        now, and this is the seam that place plugs into.
        """
        self._result_hook = hook

    def set_compile_hook(self, hook) -> None:
        """Accepted and ignored: this predictor never compiles anything, so
        `adapter.bind` can install both hooks on it without a special case."""
        self._compile_hook = hook

    def _finish(self, candidate, result):
        hook = getattr(self, "_result_hook", None)
        return result if hook is None else hook(candidate, result)

    def bind_graph(self, graph) -> None:
        """The graph whose reservations to subtract. Optional: without it the
        nominal path bottleneck is used, which is the base-class behaviour plus
        link time and still never faster than a bound."""
        self._graph = graph
