"""P1.4: the envelope cache must not merge what the compression kept apart.

`EnvelopeKey` carries model, dtype, the per-island
`accelerator|role|tp|pp|ep|dp` segments, the scheduler config, the network
class and the workload bucket. **It carries no island id and no shared
resource.** So two placements on different nodes with the same accelerator and
the same knobs collide on one key, and the graph signature is the only thing
keeping their cache entries apart (heteropilot D126).

That is the compression's own counterexample reappearing one layer down: if the
cache merged them, the second would silently read the first's TTFT and every
correctness number computed on top would be measuring one placement twice.
"""

from __future__ import annotations

import pytest

from graphsearch import paths_root
from graphsearch.embeddings import enumerate_embeddings
from graphsearch.equivalence import compress
from graphsearch.schema import build_resource_graph
from tests.graph_fixtures import FIXTURES, load_toy_cluster, toy_profiles_for

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.envelope import key_for  # noqa: E402
from planner.inventory import detect_islands  # noqa: E402
from planner.spec import load_service_spec  # noqa: E402


def _world(name: str, limit: int = 2):
    spec = load_service_spec(FIXTURES / "service_specs/graph-toy-llama31-8b.yaml")
    cluster = load_toy_cluster(name)
    profiles = toy_profiles_for(cluster)
    islands = detect_islands(cluster, profiles)
    by_id = {i.id: i for i in islands}
    graph = build_resource_graph(cluster, profiles)
    generated = CandidateGenerator(
        spec, cluster, islands, profiles,
        enable_bound_pruning=False, enable_pd=True,
    ).generate()
    templates = [c for c in generated.candidates if c.total_devices <= limit]
    embeddings, _ = enumerate_embeddings(templates, by_id, graph, spec)
    representatives, _, _ = compress(embeddings, graph)
    return spec, by_id, graph, representatives


def _colliding_pairs(spec, islands, representatives):
    """Representatives that share an EnvelopeKey but not their boundary."""
    accelerator_of = {i: island.accelerator_model for i, island in islands.items()}
    by_key: dict[str, list] = {}
    for representative in sorted(representatives, key=lambda r: r.rep_id):
        candidate = representative.exemplar.template.model_copy(
            update={"id": representative.exemplar.id}
        )
        key = key_for(
            candidate, spec, accelerator_of=accelerator_of, link_bw_gbps=1.0
        )
        by_key.setdefault(key.digest(), []).append(representative)

    pairs = []
    for group in by_key.values():
        for index, first in enumerate(group):
            for second in group[index + 1 :]:
                if set(first.exemplar.boundary.shared_resources) != set(
                    second.exemplar.boundary.shared_resources
                ):
                    pairs.append((first, second))
    return pairs


@pytest.mark.parametrize("name", ["shared_nic_v2", "abcde_v2"])
def test_the_key_alone_cannot_tell_two_boundaries_apart(name: str) -> None:
    """The condition the graph signature exists for is present in the corpus.

    A finder that grouped by `template_id` instead reported "no such pair" for
    `shared_nic_v2` -- the counterexample fixture, where the property holds by
    construction -- because two placements on different nodes are different
    templates. The key does not know that, which is the point.
    """
    spec, islands, _, representatives = _world(name)
    pairs = _colliding_pairs(spec, islands, representatives)
    assert pairs, (
        f"{name} contains no two representatives sharing an EnvelopeKey with "
        f"different boundaries; the cache-keying property cannot be tested here"
    )


def test_the_graph_signature_separates_every_such_pair() -> None:
    """Same key, different boundary -> different signature. No exceptions.

    One pair sharing a signature is one pair sharing a cache file, and a shared
    file is a shared verdict.
    """
    spec, islands, _, representatives = _world("shared_nic_v2")
    pairs = _colliding_pairs(spec, islands, representatives)
    assert pairs
    for first, second in pairs:
        assert first.signature.wl_hash != second.signature.wl_hash, (
            f"{first.exemplar.id} and {second.exemplar.id} share an "
            f"EnvelopeKey AND a graph signature, so they would share one "
            f"cache entry despite crossing different shared resources"
        )
