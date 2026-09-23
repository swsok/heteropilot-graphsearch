"""G7: provable elimination, and the property that makes it safe.

`test_each_bound_is_a_relaxation` is the reason this file exists. heteropilot
has been burned here: an early throughput bound rejected under-provisioned
candidates although §5.6 declared no throughput constraint, and the
oracle-agreement test caught it as a pruned-versus-oracle disagreement. The
comment left in `planner/candidate_generator.py` says restoring that bound needs
feasibility to declare one first -- which H1 did, and which is why
`throughput_capacity` here refuses to run until a spec sets `min_goodput_rps`.

The other tests are about the four states that are NOT refusals. Counting a cap,
a demoted check or an unstated capability as "infeasible" reports a budget, a
heuristic or an empty field as a property of the hardware.
"""

from __future__ import annotations

import itertools

import pytest

from graphsearch import paths_root
from graphsearch.bounds import (
    ALL_CHECKS,
    BoundPolicy,
    CandidateStatus,
    prune,
    status_counts,
    surviving,
)
from graphsearch.demand import pd_kv_bytes
from graphsearch.embeddings import EmbeddingPolicy, enumerate_embeddings
from graphsearch.equivalence import compress
from graphsearch.schema import build_resource_graph
from tests.graph_fixtures import (
    FIXTURES,
    GraphAwareMockPredictor,
    load_toy_cluster,
    toy_profiles_for,
)

paths_root.ensure_importable()

from planner.candidate_generator import CandidateGenerator  # noqa: E402
from planner.inventory import detect_islands  # noqa: E402
from planner.optimizer.exhaustive import evaluate_candidates, rank_plans  # noqa: E402
from planner.plan import (  # noqa: E402
    CandidateConfig,
    IslandAssignment,
    RejectionStage,
    Role,
    ServingArch,
)
from planner.spec import Objective, load_service_spec  # noqa: E402

MODEL = "meta-llama/Llama-3.1-8B"


def spec(**slo):
    base = load_service_spec(FIXTURES / "service_specs/graph-toy-llama31-8b.yaml")
    # The fixture's objective is cost, which nothing fills in until G9's driver
    # attaches a price; device count is scorable from the plan alone.
    base = base.model_copy(
        update={
            "objective": base.objective.model_copy(
                update={
                    "primary": Objective.MINIMIZE_ACTIVE_ACCELERATORS,
                    "secondary": None,
                }
            )
        }
    )
    if slo:
        base = base.model_copy(update={"slo": base.slo.model_copy(update=slo)})
    return base


def setup(name: str = "abcde_v2"):
    cluster = load_toy_cluster(name)
    profiles = toy_profiles_for(cluster)
    islands = detect_islands(cluster, profiles)
    return (
        cluster,
        profiles,
        islands,
        {i.id: i for i in islands},
        build_resource_graph(cluster, profiles),
    )


def island_named(islands, node: str) -> str:
    return next(i.id for i in islands.values() if i.node_id == node)


def pipeline(name: str, service_spec, *, limit: int | None = None):
    """Templates -> embeddings -> representatives, the way G9 will drive it."""
    cluster, profiles, islands, by_id, graph = setup(name)
    generated = CandidateGenerator(
        service_spec, cluster, islands, profiles, enable_bound_pruning=False
    ).generate()
    templates = generated.candidates
    if limit is not None:
        templates = [c for c in templates if c.total_devices <= limit]
    found, stats = enumerate_embeddings(templates, by_id, graph, service_spec)
    representatives, _, _ = compress(found, graph)
    return cluster, profiles, by_id, graph, representatives, stats


# --- (i) the property that makes elimination safe -------------------------

def _best_feasible(representatives, service_spec, cluster, by_id, profiles):
    """Simulate the survivors and return (candidate id, objective value).

    Each representative is dispatched under its EMBEDDING id, not its template
    id. Several representatives can share one template -- that is the normal
    case, since two placements of one template with different boundaries are
    different representatives -- and `predict_all` refuses duplicate candidate
    ids because its per-id isolation would race and silently drop a result.
    G9's driver has to do the same.
    """
    predictor = GraphAwareMockPredictor()
    result = evaluate_candidates(
        [
            r.exemplar.template.model_copy(update={"id": r.exemplar.id})
            for r in representatives
        ],
        service_spec, cluster, by_id, profiles, predictor,
    )
    ranked = rank_plans(result.feasible_plans, service_spec)
    if ranked.best is None:
        return None
    return ranked.best.plan.candidate.id, round(ranked.best.value, 9)


@pytest.mark.parametrize("fixture", ["abcde_v2", "shared_nic_v2"])
def test_each_bound_is_a_relaxation(fixture: str) -> None:
    """With every check on, and with each one off, the best feasible plan must
    be the same plan with the same objective value.

    A check that fails this is not a bound, it is an extra condition: it
    removed a candidate the feasibility test would have accepted.
    """
    service_spec = spec()
    cluster, profiles, by_id, graph, representatives, stats = pipeline(
        fixture, service_spec, limit=2
    )
    verdicts, _ = prune(representatives, service_spec, graph, by_id, profiles, stats)
    reference = _best_feasible(
        surviving(representatives, verdicts), service_spec, cluster, by_id, profiles
    )

    for check in ALL_CHECKS:
        policy = BoundPolicy(**{check: False})
        loosened, _ = prune(
            representatives, service_spec, graph, by_id, profiles, stats, policy=policy
        )
        got = _best_feasible(
            surviving(representatives, loosened), service_spec, cluster, by_id, profiles
        )
        assert got == reference, (
            f"check {check!r} is not a relaxation on {fixture}: with it enabled the "
            f"best feasible plan is {reference}, with it disabled {got}"
        )


def test_disabling_everything_leaves_every_representative() -> None:
    service_spec = spec()
    _, profiles, by_id, graph, representatives, stats = pipeline(
        "abcde_v2", service_spec, limit=2
    )
    off = BoundPolicy(
        compat=False, memory=False, comm_latency=False,
        throughput_capacity=False, cost_lower_bound=False,
    )
    verdicts, rejections = prune(
        representatives, service_spec, graph, by_id, profiles, stats, policy=off
    )
    assert surviving(representatives, verdicts) == representatives
    assert not [r for r in rejections if r.stage is not RejectionStage.EXCLUDED_BY_SCOPE]


# --- (ii) a bound with no constraint to relax does not run ----------------

def test_the_throughput_bound_is_silent_without_a_declared_floor() -> None:
    """Until H1 added `min_goodput_rps`, §5.6 declared no throughput constraint.
    A bound with nothing to relax is an extra condition -- the exact mistake
    `candidate_generator` had to undo."""
    service_spec = spec()
    assert service_spec.slo.min_goodput_rps is None
    _, profiles, by_id, graph, representatives, stats = pipeline(
        "abcde_v2", service_spec, limit=2
    )
    verdicts, rejections = prune(
        representatives, service_spec, graph, by_id, profiles, stats
    )
    assert not [
        r for r in rejections if r.stage is RejectionStage.THROUGHPUT_UPPER_BOUND
    ]
    assert not [
        p
        for v in verdicts.values()
        for p in v.proofs
        if p.check == "throughput_capacity"
    ]


def test_an_impossible_floor_does_eliminate() -> None:
    """And with the field set, the bound has something to relax and bites."""
    service_spec = spec(min_goodput_rps=1e9)
    _, profiles, by_id, graph, representatives, stats = pipeline(
        "abcde_v2", service_spec, limit=2
    )
    verdicts, rejections = prune(
        representatives, service_spec, graph, by_id, profiles, stats
    )
    charged = [
        r for r in rejections if r.stage is RejectionStage.THROUGHPUT_UPPER_BOUND
    ]
    assert charged
    assert all(
        v.status is CandidateStatus.IMPOSSIBLE_PROVEN
        for v in verdicts.values()
        if v.stage is RejectionStage.THROUGHPUT_UPPER_BOUND
    )


# --- (iii) the research design's §9 filter --------------------------------

def test_section_9_additional_filter() -> None:
    """§9: 0.4 GB of cut traffic against a 50 ms limit.

        5 GB/s cut  -> 80 ms, excluded (C-D, and both fast-slow directions)
       10 GB/s cut  -> 40 ms, survives (A-B)

    Three representatives are left: the two intra-node classes, which cross no
    node boundary at all, and A-B.
    """
    base = spec(ttft=load_service_spec(
        FIXTURES / "service_specs/graph-toy-llama31-8b.yaml"
    ).slo.ttft)
    per_token = pd_kv_bytes(MODEL, "bfloat16", "auto", 1)
    prompt = round(0.4e9 / per_token)
    assert pd_kv_bytes(MODEL, "bfloat16", "auto", prompt) == pytest.approx(0.4e9, rel=1e-3)

    service_spec = base.model_copy(
        update={
            "traffic": base.traffic.model_copy(
                update={
                    "input_tokens": base.traffic.input_tokens.model_copy(
                        update={"p50": prompt, "p95": prompt, "p99": prompt}
                    )
                }
            )
        }
    )
    assert service_spec.slo.ttft.max_ms == 50

    _, profiles, islands, by_id, graph = setup("abcde_v2")
    gpu = sorted(i.id for i in islands if i.backend == "cuda")

    def pd(prefill: str, decode: str) -> CandidateConfig:
        return CandidateConfig(
            id=f"pd-{prefill}-{decode}", model=MODEL, dtype="bfloat16",
            serving_arch=ServingArch.PD_SPLIT,
            assignments=[
                IslandAssignment(island_id=prefill, role=Role.PREFILL, tp_size=1),
                IslandAssignment(island_id=decode, role=Role.DECODE, tp_size=1),
            ],
        )

    def local(island: str) -> CandidateConfig:
        return CandidateConfig(
            id=f"tp2-{island}", model=MODEL, dtype="bfloat16",
            assignments=[IslandAssignment(island_id=island, tp_size=2)],
        )

    templates = [pd(a, b) for a, b in itertools.permutations(gpu, 2)]
    templates += [local(i) for i in gpu]
    found, stats = enumerate_embeddings(templates, by_id, graph, service_spec)
    representatives, _, _ = compress(found, graph)
    verdicts, _ = prune(representatives, service_spec, graph, by_id, profiles, stats)

    left = surviving(representatives, verdicts)
    assert len(left) == 3

    crossing = [r for r in left if len(r.exemplar.nodes) > 1]
    assert len(crossing) == 1
    assert crossing[0].exemplar.nodes == {"nodeA", "nodeB"}


# --- (iv) every rejection is recomputable ---------------------------------

def test_every_rejection_carries_a_proof_with_its_inputs() -> None:
    service_spec = spec(min_goodput_rps=1e9)
    _, profiles, by_id, graph, representatives, stats = pipeline(
        "abcde_v2", service_spec, limit=2
    )
    verdicts, rejections = prune(
        representatives, service_spec, graph, by_id, profiles, stats
    )
    verdicts_by_candidate = {
        r.exemplar.id: verdicts[r.rep_id] for r in representatives
    }
    for rejection in rejections:
        if rejection.stage is RejectionStage.EXCLUDED_BY_SCOPE:
            continue          # not a verdict; there is nothing to prove
        verdict = verdicts_by_candidate[rejection.candidate_id]
        assert verdict.proofs
        proof = verdict.proofs[-1]
        assert proof.inputs, f"{proof.check} states no inputs"
        assert proof.relaxations, f"{proof.check} states no relaxations"
        assert proof.check in rejection.reason
        assert "relaxations:" in rejection.reason


def test_the_throughput_proof_recomputes_from_its_inputs() -> None:
    service_spec = spec(min_goodput_rps=1e9)
    _, profiles, by_id, graph, representatives, stats = pipeline(
        "abcde_v2", service_spec, limit=2
    )
    verdicts, _ = prune(representatives, service_spec, graph, by_id, profiles, stats)
    proofs = [
        p
        for v in verdicts.values()
        for p in v.proofs
        if p.check == "throughput_capacity"
    ]
    assert proofs
    for proof in proofs:
        assert proof.threshold == pytest.approx(
            min(proof.inputs["ub_rps_memory"], proof.inputs["ub_rps_cut"])
        )
        assert proof.bound_value == pytest.approx(proof.inputs["min_goodput_rps"])


# --- (v) unstated is not unsupported --------------------------------------

def test_an_unstated_runtime_capability_is_a_note_not_a_rejection() -> None:
    """"No profile says" is not "the profile says no". Rejecting here would turn
    an unfilled field into a hardware verdict."""
    service_spec = spec()
    _, profiles, by_id, graph, representatives, stats = pipeline(
        "abcde_v2", service_spec, limit=2
    )
    blank = {
        model: profile.model_copy(update={"runtime_capabilities": None})
        for model, profile in profiles.items()
    }
    verdicts, rejections = prune(
        representatives, service_spec, graph, by_id, blank, stats
    )
    assert not [
        r for r in rejections if r.stage is RejectionStage.BACKEND_INCOMPATIBLE
    ]
    assert any(
        "runtime_capabilities unstated" in note
        for v in verdicts.values()
        for note in v.notes
    )


def test_a_stated_absence_does_reject() -> None:
    service_spec = spec()
    _, profiles, by_id, graph, representatives, stats = pipeline(
        "abcde_v2", service_spec, limit=2
    )
    stripped = {}
    for model, profile in profiles.items():
        caps = profile.runtime_capabilities
        if caps is not None:
            caps = caps.model_copy(update={"collectives": []})
        stripped[model] = profile.model_copy(update={"runtime_capabilities": caps})

    verdicts, rejections = prune(
        representatives, service_spec, graph, by_id, stripped, stats
    )
    charged = [
        r for r in rejections if r.stage is RejectionStage.BACKEND_INCOMPATIBLE
    ]
    assert charged, "a tp=2 candidate on a runtime stating no all_reduce must go"
    assert all("all_reduce" in r.reason for r in charged)
    # tp=1 candidates need no collective and must survive.
    assert surviving(representatives, verdicts)


# --- (vi) a demoted check may not eliminate -------------------------------

def test_a_demoted_check_defers_rather_than_refusing() -> None:
    """It runs, it may be right, and it is not a proof.

    TPOT rather than TTFT: an aggregated candidate has no KV transfer and no
    stage boundary, so nothing gates its first token and only the all-reduce
    floor can trip `comm_latency`.
    """
    service_spec = spec(tpot=spec().slo.tpot.model_copy(update={"max_ms": 0.001}))
    _, profiles, by_id, graph, representatives, stats = pipeline(
        "abcde_v2", service_spec, limit=2
    )
    strict, _ = prune(representatives, service_spec, graph, by_id, profiles, stats)
    assert any(v.status is CandidateStatus.IMPOSSIBLE_PROVEN for v in strict.values())

    policy = BoundPolicy(demoted=frozenset({"comm_latency"}))
    demoted, rejections = prune(
        representatives, service_spec, graph, by_id, profiles, stats, policy=policy
    )
    deferred = [
        v for v in demoted.values() if v.status is CandidateStatus.DEFERRED_HEURISTIC
    ]
    assert deferred
    assert all(p.safe is False for v in deferred for p in v.proofs)
    assert all(
        "not a proof" in " ".join(p.relaxations) for v in deferred for p in v.proofs
    )
    assert all(
        r.stage is RejectionStage.SURROGATE_PRUNED
        for r in rejections
        if r.stage is not RejectionStage.EXCLUDED_BY_SCOPE
    )
    # Deferred is not eliminated: they are still available to evaluate.
    assert surviving(representatives, demoted) == representatives


# --- a cap is reported as scope, not as a refusal -------------------------

def test_a_truncated_template_becomes_excluded_by_scope() -> None:
    service_spec = spec()
    cluster, profiles, islands, by_id, graph = setup("abcde_v2")
    generated = CandidateGenerator(
        service_spec, cluster, islands, profiles, enable_bound_pruning=False
    ).generate()
    # Templates that really have more than one placement, or there is nothing
    # for a cap of 1 to truncate: a tp=2 candidate on a two-device island has
    # exactly one.
    templates = [
        c
        for c in generated.candidates
        if c.total_devices == 2 and len(c.assignments) == 2
    ][:4]
    assert templates
    found, stats = enumerate_embeddings(
        templates, by_id, graph, service_spec,
        EmbeddingPolicy(max_embeddings_per_template=1),
    )
    representatives, _, _ = compress(found, graph)
    _, rejections = prune(representatives, service_spec, graph, by_id, profiles, stats)

    scoped = [r for r in rejections if r.stage is RejectionStage.EXCLUDED_BY_SCOPE]
    assert scoped
    assert all("NOT a verdict" in r.reason for r in scoped)
    assert all(r.candidate_id.endswith("/*") for r in scoped)


def test_the_five_states_are_counted_separately() -> None:
    service_spec = spec()
    _, profiles, by_id, graph, representatives, stats = pipeline(
        "abcde_v2", service_spec, limit=2
    )
    verdicts, _ = prune(representatives, service_spec, graph, by_id, profiles, stats)
    counts = status_counts(verdicts)
    assert set(counts) == {s.value for s in CandidateStatus}
    assert sum(counts.values()) == len(representatives)


def test_checking_the_exemplar_judges_every_placement_it_stands_for() -> None:
    """G6 merged them only after VF2 confirmed the graphs isomorphic, so the
    arithmetic reads the same numbers for all of them."""
    service_spec = spec(min_goodput_rps=1e9)
    _, profiles, by_id, graph, representatives, stats = pipeline(
        "abcde_v2", service_spec, limit=2
    )
    verdicts, rejections = prune(
        representatives, service_spec, graph, by_id, profiles, stats
    )
    eliminated = [r for r in representatives if verdicts[r.rep_id].eliminated]
    assert eliminated
    covered = sum(r.multiplicity for r in eliminated)
    assert covered > len(eliminated), "no representative covers more than one placement"
    assert all(
        f"covers {r.multiplicity} placement(s)" in rejection.reason
        for r in eliminated
        for rejection in rejections
        if rejection.candidate_id == r.exemplar.id
    )
