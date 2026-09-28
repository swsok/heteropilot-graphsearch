# Measurement-node preparation — the checklist (P0.3)

**This file is a checklist, not a record.** Nothing in it is a measurement.
Claude Code wrote the steps; the person at the keyboard runs them on each node
and commits what came back. Until that happens, every hardware number in this
repository is `source: placeholder` and says so — including the ones a step
below tells you where to put.

Three nodes are in scope: the **A40** node, the **A5000** node and the **RNGD**
(FuriosaAI NPU) node. They are not interchangeable and no committed statement
about "the node" is true on more than one of them, which is why step A exists
and why it runs first, every time.

Run each step from the repository root with the submodule initialised:

```bash
cd ~/heteropilot-graphsearch
git submodule update --init --recursive      # --recursive: step B needs ASTRA-Sim
export PYTHONPATH=$PWD:$PWD/vendor/heteropilot
```

Work through A → B → C → D → E on one node before starting the next. A, C and D
produce artefacts to commit; B produces an environment that stays on the node.

---

## A — Which node is this, and which cards are in it

```bash
bash vendor/heteropilot/scripts/whichnode.sh     # detect, never assume
```

The detector already answers both halves of the question. Its `detected node`
line is a node **kind** — any box with an RNGD reads `npu`, so it does not
identify a machine — and its `accel serials` line is the string that does: the
FuriosaAI `device_sn` values from `furiosa-smi info`, the NVIDIA card UUIDs from
`nvidia-smi -L`, sorted and joined. That is the string rule 3 of the work order
asks the `REAL HARDWARE` banner to carry, and a result whose banner names none
of it cannot be attributed to a machine.

On the NVIDIA nodes, take the per-card detail the detector does not print:

```bash
nvidia-smi --query-gpu=index,name,serial,uuid,pci.bus_id --format=csv
nvidia-smi topo -m                 # this is what determines island structure
```

A40s and A5000s commonly report `[N/A]` for `serial`. Record the UUID and write
"serial unavailable" beside it — a blank field is a missing measurement, not an
absent card.

**Record, verbatim**, into `docs/nodes/<a40|a5000|rngd>.md` in this repository —
a new file per node, not an edit of heteropilot's copies under `vendor/`, which
are read-only and describe that repository's own runs:

- the whole `whichnode.sh` stdout, including the lines about what it could *not*
  observe;
- the per-card table and the topology matrix;
- `uname -r`, `nproc`, and the driver/CUDA line, so a later run can tell whether
  it is looking at the same machine.

If `accel serials` does not match what heteropilot's `docs/nodes/*.md` records
for that node kind, **stop and say so**: it is a different machine, and nothing
in those files is reliable for it.

- [ ] `whichnode.sh` output recorded, `accel serials` line included
- [ ] per-card table recorded (UUID + "serial unavailable" where `[N/A]`)
- [ ] kernel, core count, driver and `nvidia-smi topo -m` recorded

---

## B — A simulator this node can actually run

`--predictor sim` needs LLMServingSim and ASTRA-Sim *built*, in
`vendor/heteropilot/.venv` and in no other interpreter. This is heteropilot's
own recipe (`vendor/heteropilot/CLAUDE.md` § Environment), repeated here only
because P1 will ask you for the result of it; if the two ever disagree, that
file wins.

```bash
sudo apt install -y protobuf-compiler libprotobuf-dev     # not pip-installable
cd vendor/heteropilot
uv venv --python 3.10 .venv && source .venv/bin/activate
uv pip install pyyaml pyinstrument transformers datasets msgspec scikit-learn \
  xgboost==3.1.2 matplotlib==3.5.3 pandas==1.5.3 numpy==1.23.5 rich
uv pip install pydantic
uv pip install pytest ruff mypy
bash scripts/compile.sh
uv pip install ./astra-sim/extern/graph_frontend/chakra
uv pip install "protobuf>=7.35.1"
```

Both post-`compile.sh` lines are required. `compile.sh`'s own bare `pip3` misses
the venv, and Chakra's generated code needs `protobuf>=7.35.1`; a venv carrying
the wrong one raises at the first conversion instead of converting wrongly
(heteropilot D26/D27), which is the failure mode you want.

**Do not `pip install -e` this repository into that venv, and do not copy files
into `vendor/`.** `graphsearch` is reached by `PYTHONPATH`, and the submodule
must stay a pristine checkout of its pinned sha — `git -C vendor/heteropilot
status --porcelain` printing nothing is part of the quality gate.

- [ ] `vendor/heteropilot/.venv` exists and `compile.sh` finished without error
- [ ] `git -C vendor/heteropilot status --porcelain` still prints nothing
- [ ] record in `docs/nodes/<node>.md`: the date, and `.venv/bin/python -c
      "import chakra, google.protobuf; print(google.protobuf.__version__)"`

---

## C — One real-simulator run, end to end

Thirty requests is not a workload; it is a proof that the path exists on this
node. It is the smallest thing that exercises trace generation, the Chakra
conversion and ASTRA-Sim in one go.

```bash
cd vendor/heteropilot
bash experiments/scripts/livelock_watch.sh \
  .venv/bin/python -m planner plan \
    --service examples/service_specs/llama31-8b.yaml \
    --cluster examples/clusters/heterogeneous-lab.yaml \
    --num-requests 30 --seed 42 \
    --cache-dir outputs/.hp-envelope-prep \
    --output outputs/plans/prep-smoke.yaml
```

`livelock_watch.sh` is not optional decoration: it ends a provably stuck run in
seconds and separates a tick stall (exit 3) from a child that went quiet (exit
4), which is the difference between "this node is slow" and "this node cannot do
it".

Record in `docs/nodes/<node>.md`: the exit code, the wall time, and how many
candidates the run simulated. Keep `outputs/` out of git — it is gitignored here
and regenerable — but **do** paste the `plan` stdout summary lines (feasible
count, rejected counts by stage, recommended plan) into the node file.

On the RNGD node this step is expected to be partial, and that is a result, not
a failure to hide: `planner/deploy` carries `vllm_cuda`, an Ascend stub and a
Kubernetes stub, and **no FuriosaAI backend**. Write down exactly which stage
refused and with which message.

- [ ] the command completed, or the refusal is recorded with its message
- [ ] exit code, wall time and simulated-candidate count recorded

---

## D — One link measurement, between two nodes

This is the only number in the whole checklist that becomes
`source: measured`, and it is the one P2 and P3 build on.

heteropilot's `experiments/p2_evidence/link_probe.py` is written for ranks
*inside* one host (`run_link_probe.sh` drives it with `--nproc-per-node`). A
cross-node figure needs the same script under a two-node `torchrun`, with one
rank per node so the collective actually crosses the wire:

```bash
# On the node you pick as rendezvous host (node 0):
cd vendor/heteropilot
.venv-vllm/bin/torchrun --nnodes 2 --node-rank 0 --nproc-per-node 1 \
  --master-addr <node0-ip> --master-port 29571 \
  experiments/p2_evidence/link_probe.py \
  --ranks 0,1 --label xnode-a40-a5000 \
  --out outputs/p2_evidence/link/xnode-a40-a5000.json

# On the other node, the same command with --node-rank 1 and its own --out.
```

If `torchrun` is not installed on both nodes, say so and stop — a
single-node figure is not an inter-node measurement and must not be filed as
one. `p2p_probe.py` (direct peer copy, no NCCL) is the independent control if
the NCCL number looks implausible; run it only within a node, which is all it
can do.

**Record it as a `LinkMeasurement`**, because every field of that record is a
condition the figure holds under and a condition left out is a figure that will
later answer a question it was never measured for:

```yaml
measurements:
  - collective: all_reduce        # or all_gather / p2p — what you actually ran
    msg_size_class: bulk          # small <1 MiB, mid <4 MiB, bulk >=4 MiB
    binding: unpinned             # or numa_pinned; `unknown` if you did not record it
    bus_bw_gbps: 0.0              # the busbw plateau, GB/s — NOT the wire rate
    world_size: 2                 # how many ranks took part
    source: measured
    method: "torch <ver> + NCCL <ver> under torchrun, link_probe.py"
    msg_bytes: [4194304, 8388608, 16777216, 33554432, 67108864]
    date: "YYYY-MM-DD"
    raw: experiments/raw/link/<date>-<node-serial>/xnode-a40-a5000.json
    note: "<what the spread across iterations was, and anything odd>"
```

Three rules the schema enforces and one it does not:

- `msg_bytes` must all fall inside the band `msg_size_class` names, or the load
  fails. A `bulk` label over a 1 MiB sweep is rejected rather than believed.
- `source: measured` must name a `method`. An unattributed number is not a
  measurement.
- `world_size` is part of the key. On heteropilot's A40 bridge a two-rank
  all-reduce measures 19.29 GB/s and a four-rank one 8.8 — one wire, 2.2× apart.
  Filing one under the other's key is the substitution the key exists to stop.
- The schema will *not* stop you from recording a single trial. Do at least ten
  iterations and record the spread; heteropilot's own `docs/nodes/a40.md`
  records two runs disagreeing by 38 % on a single parallel trial.

Commit the probe's raw JSON under `experiments/raw/link/<date>-<node-serial>/`
and point `raw:` at it. The JSON is the evidence; the YAML is the claim.

- [ ] the probe ran between two named nodes, ≥10 iterations
- [ ] raw JSON committed, path recorded
- [ ] the `LinkMeasurement` block filled in, every field, no blanks

---

## E — Write it into the cluster spec draft

The destination is `fixtures/clusters/real-<lab>.v2.yaml` — `schema_version: 2`,
the same shape as `fixtures/clusters/graph-toy-shared-nic.v2.yaml`, which is
worth reading first because it is short and carries the comments explaining what
each block is for.

What goes where:

| What you measured | Where it goes | `source:` |
| --- | --- | --- |
| cards, counts, memory, PCI ids (step A) | `nodes[].accelerators[]` | — (observed inventory, not a rate) |
| the link's datasheet rate | `links[].bandwidth_gbps` | `vendor_spec` |
| the busbw you measured (step D) | `links[].measurements[]` | `measured` |
| uplink capacity and what is reserved on it | `shared_resources[]` | whichever is true |
| per-hour prices | `*_price_per_hour_usd` + `price_source` | `placeholder` unless quoted |

**The datasheet number is never edited by a measurement.** They sit side by side
so the two can be compared; a measurement that overwrote its spec value would
destroy the only evidence that the spec was wrong (heteropilot absolute rule
A3). This is also why `links[].bandwidth_gbps` keeps `vendor_spec` even on a
link you have just measured.

Anything you did not measure stays `source: placeholder`, and a result computed
from a placeholder is not a measurement of anything — the work order's rule 1,
and the reason `REAL HARDWARE` is a banner and not a default.

- [ ] `fixtures/clusters/real-<lab>.v2.yaml` drafted
- [ ] every number carries a `source:`
- [ ] no number was invented to fill a field; unknown fields are absent or
      explicitly `placeholder`

---

## What to hand back

Commit, on a branch (`exp/p0-3-<node>-prep`):

1. `docs/nodes/<node>.md` — steps A, B, C, filled in.
2. `experiments/raw/link/<date>-<node-serial>/*.json` — step D's raw artefacts.
3. `fixtures/clusters/real-<lab>.v2.yaml` — step E's draft.

Then say so. Claude Code then, and not before:

- loads the YAML through `planner.inventory.load_cluster_spec` and reports every
  validation error with the field that raised it;
- checks each `LinkMeasurement` against `msg_size_class_of(msg_bytes)` and
  against its `raw:` file actually existing at that path;
- adds the fixture to `tests/test_fixtures.py`'s load parametrisation so a later
  edit cannot silently break it;
- reports what is still `placeholder`, by field, so the gap is visible rather
  than averaged away.

**No number gets filled in from this side.** If a field is empty after you hand
it over, it stays empty and every result computed from that fixture says which
inputs were missing. That is rule 7 of the work order and it is not negotiable:
a plausible number is the one failure this whole pipeline cannot detect.
