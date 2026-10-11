"""E-G8's harness: each direction puts each role on the right node, with that
node's engine, memory share and HCA, and the background on the KV's NIC."""

from __future__ import annotations

import importlib.util
import json
import sys
from types import SimpleNamespace

import pytest

from graphsearch import paths_root

paths_root.ensure_importable()
ROOT = paths_root.GRAPHSEARCH_ROOT


@pytest.fixture(scope="module")
def arm():
    path = ROOT / "experiments" / "e_g8" / "pd_arm.py"
    spec = importlib.util.spec_from_file_location("e_g8_pd_arm", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["e_g8_pd_arm"] = module
    spec.loader.exec_module(module)
    return module


PLAN = SimpleNamespace(candidate=SimpleNamespace(
    dtype="bfloat16", knobs=SimpleNamespace(max_num_seqs=32, max_num_batched_tokens=2048,
                                            kv_cache_dtype="auto")))


@pytest.mark.parametrize("direction,prefill,decode", [("D1", "s8", "a5k2"), ("D2", "a5k2", "s8")])
def test_each_direction_places_each_role(arm, direction, prefill, decode) -> None:
    p, d = arm.DIRECTIONS[direction]
    assert (p.name, d.name) == (prefill, decode)
    bg = arm.NicBackground(direction)
    assert (bg.sender.name, bg.receiver.name) == (prefill, decode)


@pytest.mark.parametrize("node,util,hca", [("s8", "0.6", "mlx5_0"), ("a5k2", "0.9", "mlx5_1")])
def test_engine_argv_and_env_follow_the_node(arm, node, util, hca) -> None:
    n = arm.NODES[node]
    argv = arm.serve_argv(n, PLAN, "meta-llama/Llama-3.1-8B", 8100, "kv_producer")
    assert argv[0] == n.vllm
    assert argv[argv.index("--gpu-memory-utilization") + 1] == util
    cfg = json.loads(argv[argv.index("--kv-transfer-config") + 1])
    assert cfg == {"kv_connector": "NixlConnector", "kv_role": "kv_producer",
                   "kv_buffer_device": "cuda"}
    env = arm.engine_env(n)
    assert env["UCX_NET_DEVICES"] == f"{hca}:1" and env["VLLM_NIXL_SIDE_CHANNEL_HOST"] == n.ib_ip


def test_a_mock_rehearsal_never_writes_beside_registered_files(arm) -> None:
    assert arm.raw_root(SimpleNamespace(predictor="mock")) != arm.RAW
    assert arm.raw_root(SimpleNamespace(predictor="sim")) == arm.RAW


D1_ID = "pd(cuda-a40-s8-tp1-dp1 P + cuda-rtx-a5000-a5k2-tp1-dp1 D)-s32-t8192"
D2_ID = "pd(cuda-rtx-a5000-a5k2-tp1-dp1 P + cuda-a40-s8-tp1-dp1 D)-s32-t8192"


def test_the_mirror_swaps_the_islands_and_keeps_the_knobs(arm) -> None:
    assert arm.mirror_template_id(D2_ID) == D1_ID
    assert arm.mirror_template_id(arm.mirror_template_id(D1_ID)) == D1_ID


def test_an_unjudged_direction_takes_the_mirror_and_stays_unknown(arm, tmp_path,
                                                                  monkeypatch) -> None:
    monkeypatch.setattr(arm, "ROOT", tmp_path)
    monkeypatch.setattr(arm, "selection_path", lambda d, a: tmp_path / f"selection-{d}.json")
    (tmp_path / "selection-D2.json").write_text(json.dumps(
        {"chosen": D2_ID, "rule_applied": True}))
    log = tmp_path / "select" / "sim" / "sims" / "pd_x" / "sim1.log"
    log.parent.mkdir(parents=True)
    log.write_text("RuntimeError: [MemoryModel] NPU: tried to load 108.00MB but only "
                   "25.89MB is available.\n")
    table = [{"template_id": D1_ID, "state": "unknown_measurement", "feasible": None,
              "p99_ttft_ms": None, "p99_tpot_ms": None}]
    sel = arm.unjudged_selection("D1", table, tmp_path / "select",
                                 SimpleNamespace(predictor="sim"), 42)
    assert sel["chosen"] == D1_ID and sel["state"] == "unknown_measurement"
    assert sel["rule_applied"] is False and sel["all_infeasible"] is None
    assert sel["simulator_errors"] == [
        "RuntimeError: [MemoryModel] NPU: tried to load <n>MB but only <n>MB is available."]


def test_a_mirror_is_never_mirrored_again(arm, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(arm, "selection_path", lambda d, a: tmp_path / f"selection-{d}.json")
    (tmp_path / "selection-D2.json").write_text(json.dumps(
        {"chosen": D2_ID, "rule_applied": False}))
    with pytest.raises(SystemExit):
        arm.unjudged_selection("D1", [], tmp_path, SimpleNamespace(predictor="sim"), 42)
