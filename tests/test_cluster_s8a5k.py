"""The E-G8 fixture is generated, current, loadable, and shared in one field only."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from graphsearch import paths_root

paths_root.ensure_importable()

from planner.inventory import detect_islands, load_cluster_spec, load_profiles_for  # noqa: E402

ROOT = paths_root.GRAPHSEARCH_ROOT
SCRIPT = ROOT / "experiments" / "e_g8" / "build_cluster_s8a5k.py"


@pytest.fixture(scope="module")
def builder():
    spec = importlib.util.spec_from_file_location("build_cluster_s8a5k", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_cluster_s8a5k"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("shared", [None, "D1", "D2"])
def test_the_committed_fixture_is_what_the_raw_files_give(builder, shared) -> None:
    out = builder.OUT_SHARED[shared] if shared else builder.OUT
    assert out.read_text() == builder.render(shared)


def test_it_loads_as_two_islands_with_a_cross_node_link(builder) -> None:
    cluster = load_cluster_spec(builder.OUT)
    profiles = load_profiles_for(cluster, ROOT)
    islands = sorted(i.id for i in detect_islands(cluster, profiles))
    assert islands == ["cuda-a40-s8", "cuda-rtx-a5000-a5k2"]
    ids = {link.id for link in cluster.links}
    assert {"ib-s8-a5k2", "ib-a5k2-s8"} <= ids


def test_a5k2_carries_gpu0_only(builder) -> None:
    doc = yaml.safe_load(builder.OUT.read_text())
    a5k2 = next(n for n in doc["nodes"] if n["id"] == "a5k2")
    assert [a["id"] for a in a5k2["accelerators"]] == ["gpu0"]


@pytest.mark.parametrize("shared", ["D1", "D2"])
def test_a_shared_variant_reserves_only_the_kv_direction(builder, shared) -> None:
    base = yaml.safe_load(builder.OUT.read_text())
    variant = yaml.safe_load(builder.OUT_SHARED[shared].read_text())
    assert base["links"] == variant["links"] and base["nodes"] == variant["nodes"]
    src, dst = builder.KV_DIRECTION[shared]
    changed = [(a["id"], b["reserved"]) for a, b in
               zip(base["shared_resources"], variant["shared_resources"], strict=True) if a != b]
    assert len(changed) == 1 and changed[0][0] == f"nic-{src}-to-{dst}"
    nic = next(r for r in base["shared_resources"] if r["id"] == changed[0][0])
    assert changed[0][1] == round(nic["capacity"] * 0.6, 2)


def test_every_measured_nic_capacity_names_its_raw_directory(builder) -> None:
    for (src, dst), name in builder.NIC_RAW.items():
        assert (builder.LINKS_RAW / name).is_dir()
        assert builder.nic_capacity_gbit(src, dst) > 0
    assert Path(builder.COLLECTIVE_RAW).is_dir()
