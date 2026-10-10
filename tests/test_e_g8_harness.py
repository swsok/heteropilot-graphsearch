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
