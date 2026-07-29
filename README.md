# AutoContract

Contract-carrying rewrites for machine-learning input pipelines.

AutoContract studies how to infer conservative semantic-effect contracts for
ML preprocessing operators and use those contracts to guard reordering,
caching, parameter replay, and composition. The current prototype is
adapter-assisted: unsupported or unresolved Python behavior fails closed.

> Research status: mechanism prototype and pilot evaluation. This repository
> does not claim framework-agnostic inference for arbitrary Python/C++/CUDA
> operators, formal equivalence for every accepted rewrite, or end-to-end
> exactly-once model updates.

## Research question

Can an input-pipeline optimizer automatically recover enough phase-,
configuration-, randomness-, state-, and lineage-sensitive information to
enable useful rewrites without accepting known unsafe transformations?

The intended architecture is:

```text
operator source + configuration + framework adapter
                         |
                         v
              EffectV7 contract inference
                         |
                         v
                  rewrite validator
                         |
             +-----------+-----------+
             |                       |
             v                       v
     existing cost optimizer   atomic runtime checks
                                     |
                                     v
                         output/RNG/gradient/lineage
```

## Current evidence

- Hidden RNG effects can make apparently deterministic operators unsafe to
  skip or reorder.
- A generic blind EffectV2 evaluation failed, motivating adapter-assisted,
  phase-aware and configuration-aware analysis.
- The frozen EffectV7/Kornia pilot passed 9/9 registered decisions with zero
  known-unsafe false accepts. Its scale is still too small for a broad claim.
- The H7I-H7K runtime path validates parameter lineage, seals mutable records,
  composes child contracts, and applies registered operators atomically.
- H7L-H7M extend the prototype with signed provenance, Merkle batches, fenced
  leases, and buffered release. These are treated as distributed-system
  extensions rather than the primary paper contribution.
- In the H7M Kornia batch-size-4 pilot, consumer latency was 0.835x H7L and was
  lower in 10/10 randomized rounds; batch size 1 was a no-go at 1.911x.

The complete, caveated result history is in
[the current experiment summary](.research/semantics_safe_reconfiguration/current_experiment_summary.zh-CN.md).

## Repository layout

- `experiments/`: analyzers, runtime prototypes, safety tests and benchmarks.
- `outputs/`: checked-in tables, manifests and reports; transient SQLite state
  is intentionally ignored.
- `.research/semantics_safe_reconfiguration/`: protocols, freeze records,
  candidate-selection notes and postmortems.
- `.research/literature_matrix.md`: related-work matrix.
- `cachew_pecan_optimization_research_memo.md`: the original broad-direction
  memo and the evidence used to narrow the topic.

Several frozen upstream frameworks are Git submodules. Clone recursively:

```bash
git clone --recurse-submodules <repository-url>
```

See [THIRD_PARTY.md](THIRD_PARTY.md) for exact repositories and commits.

## Environment

The latest H7 experiments were validated on Windows with Python 3.12.4 and a
CPU build of PyTorch 2.4.0. Install the recorded Python dependencies with:

```bash
python -m pip install -r requirements.txt
```

PyTorch wheels are platform-specific. If the command above does not select the
desired CPU/CUDA build, install the matching PyTorch and torchvision wheels
first, then install the remaining requirements.

## Quick verification

Compile the latest protocol/runtime files:

```bash
python -m py_compile \
  experiments/autocontract_h7m_batch_lease.py \
  experiments/autocontract_h7m_buffered_executor.py \
  experiments/autocontract_h7m_kornia_buffered.py
```

Run the dependency-light H7M protocol self-test:

```bash
python experiments/autocontract_h7m_batch_lease.py \
  --self-test \
  --output outputs/autocontract_h7m_batch_lease_selftest.json
```

Verify the frozen Kornia corpus and analyzer hashes after cloning submodules:

```bash
python -c "import sys; sys.path.insert(0, 'experiments'); import autocontract_h7h_kornia as h; print(h.verify_freeze())"
```

## Publication boundary and next work

The next research milestone is not a broader exactly-once trainer protocol.
It is a consolidated benchmark and an optimizer integration that compares
AutoContract with manual cedar-style hints, static-only analysis, dynamic
differential testing, fail-closed execution, and a human oracle.

Before making this repository public, review the third-party source snapshots,
licenses, dataset terms, and the research claims with the project supervisor.
