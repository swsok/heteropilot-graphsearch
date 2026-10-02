"""GS-38: a TP group's link figure covers every rank pair, measured first.

The adapter read only the first rank pair of a tensor-parallel flow. For the
four-rank group on {gpu0..gpu3} -- two NVLink pairs bridged by PCIe -- that is
gpu0-gpu1, and the simulator was told 112.5 GB/s for a ring that crosses the
bridge. It now takes the slowest link over every pair, and on each link the
measured all_reduce busbw at world_size = tp where the link carries one
(heteropilot's `Link.measurement_for`, S3/D112).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from graphsearch import paths_root
from graphsearch.__main__ import _load, _templates
from graphsearch.adapter import compile_embedded
from graphsearch.demand import FlowKind
from graphsearch.embeddings import EmbeddingPolicy, enumerate_embeddings

ROOT = paths_root.GRAPHSEARCH_ROOT
SPEC = str(ROOT / "fixtures/service_specs/graph-toy-llama31-8b.yaml")
CLUSTER = str(ROOT / "fixtures/clusters/real-a40x8.v2.yaml")


def _embedding(template_id: str, devices: set[str], max_devices: int):
    args = SimpleNamespace(service=SPEC, cluster=CLUSTER, profiles_root=str(ROOT),
                           no_enable_pd=False)
    spec, cluster, profiles, islands, graph = _load(args)
    by_id = {i.id: i for i in islands}
    templates = [t for t in _templates(spec, cluster, islands, profiles, True,
                                       max_devices=max_devices) if t.id == template_id]
    assert templates, template_id
    embs, _ = enumerate_embeddings(templates, by_id, graph, spec, EmbeddingPolicy())
    emb = next(e for e in embs if e.devices == frozenset(devices))
    return emb, cluster, by_id, profiles, graph


@pytest.mark.parametrize(("name", "template", "devices", "n", "expected"), [
    # the NVLink pair: measured all_reduce at world 2 (52.64 is its p2p figure)
    ("T1", "cuda-a40-a40x8-tp2-dp1-s128-t2048", {"a40x8/gpu0", "a40x8/gpu1"}, 2, 39.24),
    # across the bridge: measured all_reduce at world 2
    ("T2", "cuda-a40-a40x8-tp2-dp1-s128-t2048", {"a40x8/gpu0", "a40x8/gpu2"}, 2, 19.34),
    # the four-rank group: measured all_reduce at world 4, not the NVLink 112.5
    ("T3", "cuda-a40-a40x8-tp4-dp1-s128-t2048",
     {"a40x8/gpu0", "a40x8/gpu1", "a40x8/gpu2", "a40x8/gpu3"}, 4, 8.71),
])
def test_the_tp_link_figure_is_the_measured_collective(name, template, devices, n, expected):
    emb, cluster, by_id, profiles, graph = _embedding(template, devices, n)
    config, _reduction, _report = compile_embedded(emb, cluster, by_id, profiles, graph=graph)
    bw = config["link_bw"]
    first = bw[0] if isinstance(bw, list) else bw
    assert first == pytest.approx(expected), (name, bw)


def test_a_four_rank_flow_carries_every_pair() -> None:
    """The structure the old code ignored: six path sets, the first NVLink."""
    emb, *_ = _embedding("cuda-a40-a40x8-tp4-dp1-s128-t2048",
                                 {"a40x8/gpu0", "a40x8/gpu1", "a40x8/gpu2", "a40x8/gpu3"}, 4)
    (flow,) = [f for f in emb.flows if f.kind is FlowKind.TP_ALLREDUCE]
    assert len(flow.allowed_paths) == 6
    assert flow.allowed_paths[0].best.edges == ("gpu0-gpu1:fwd",)
