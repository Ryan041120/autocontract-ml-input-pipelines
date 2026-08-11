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
- The optimizer-boundary MVP runs 37 common adjacent-rewrite candidates through
  fail-closed, registry, static, dynamic, hybrid, manual, and oracle policies.
  Hybrid selected 10/10 non-overlapping safe opportunities with no unsafe
  selection; dynamic-only selected one external-state-unsafe rewrite.
- H8A connects frozen EffectV7 leaf analyses and bound H7J proofs to real H7K
  paired profiles. One-call horizons reject registration for all three shapes;
  ten-call horizons select it for all three after measured amortization.
- H8B adds a content-addressed cache-prefix contract over the H5 JPEG artifact.
  It rejects the legacy under-specified sidecar, detects six invalidation attacks,
  and predicts the H5b cold/warm training choices correctly. The one positive
  workload reaches 100% oracle benefit but is explicitly treated as a pilot.
- H8C freezes and runs a common five-workload CV/audio cache calibration suite.
  Hybrid preserves both safe opportunities, rejects all three profitable unsafe
  candidates, and matches the pilot oracle benefit; dynamic-only selects all
  three unsafe plans. The corpus and oracle are not independently blinded.
- H7L-H7M extend the prototype with signed provenance, Merkle batches, fenced
  leases, and buffered release. These are treated as distributed-system
  extensions rather than the primary paper contribution.
- In the H7M Kornia batch-size-4 pilot, consumer latency was 0.835x H7L and was
  lower in 10/10 randomized rounds; batch size 1 was a no-go at 1.911x.

The complete, caveated result history is in
[the current experiment summary](.research/semantics_safe_reconfiguration/current_experiment_summary.zh-CN.md).
The frozen working claims and non-claims are in
[the paper claim freeze](.research/semantics_safe_reconfiguration/paper_claim_freeze_v0.zh-CN.md).

## Repository layout

- `experiments/`: analyzers, runtime prototypes, safety tests and benchmarks.
- `benchmark/`: versioned evidence manifests and the final-benchmark schema work.
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

Audit the H6-H7H evidence history without pooling incompatible versions:

```bash
python experiments/build_autocontract_evidence_inventory.py
```

Run the dependency-light-on-data optimizer-boundary pilot (requires the
recorded PyTorch stack):

```bash
python experiments/autocontract_optimizer_boundary.py
```

Run the EffectV7-to-profiled-plan integration pilot:

```bash
python experiments/autocontract_h8a_effect_v7_optimizer.py
```

Audit the H5 cache artifact and run the H8B horizon-aware cache decisions:

```bash
python experiments/autocontract_h8b_cache_prefix_optimizer.py
```

Run the dependency-local H8C smoke checks (the registered calibration result is
already frozen and should not be resealed):

```bash
python experiments/autocontract_h8c_multiworkload_cache.py --smoke
```

Run the R3 posthoc Kornia strong-baseline and invalidation calibrations with the
recorded Python 3.12 / PyTorch 2.4 environment:

```bash
python experiments/autocontract_r3_p1_kornia_greybox.py
python experiments/autocontract_r3_p2_kornia_invalidation.py
python experiments/autocontract_r3_p2b_cached_source_index.py
python experiments/autocontract_r3_p3a_cross_framework_context.py
```

These R3 runs use already-known H7H/H7I material. They are novelty-falsification
and mechanism-calibration evidence, not new blind holdouts.

Exercise the final-blind handoff guardrails without using any real labels:

```bash
python experiments/autocontract_final_benchmark_admin.py self-test \
  --output outputs/autocontract_final_handoff_selftest.json
```

## Publication boundary and next work

The next research milestone is not a broader exactly-once trainer protocol.
R3-P1 showed that a source-guided greybox dynamic baseline can match frozen
EffectV7 on the nine known Kornia decision units, so detection accuracy is no
longer a defensible headline contribution on that scope. R3-P2 then found that
the existing lineage-v1 certificate admits a same-commit runtime callable
replacement. The immediate milestone is therefore a cached, measured-source
index with explicit Unknown handling, followed by cross-framework greybox
transfer calibration. R3-P2b now demonstrates that boundary on the known
Kornia replay slice: the process-local sentinel adds a 0.669 ms median hot
check, rejects supported class/code/instance mutations, and returns Unknown
for a native replacement. The remaining immediate milestone is R3-P3
cross-framework transfer calibration. R3-P3a now excludes the context-incompatible
TorchIO sample-apply units and reproduces 16/16 known imgaug/Albumentations
replay decisions without rule changes, but full runtime measured-index readiness
is still 0/2 because the frozen environment lacks the required framework
dependencies. P3b therefore requires an isolated dependency-locked runtime.
The final benchmark remains necessary, but its primary
question should be versioned/auditable rewrite invalidation unless later
cross-framework evidence restores a detection-accuracy gap.

The versioned handoff protocol is now in `benchmark/final_v1/`. It separates a
label-free public manifest from a salted private-oracle commitment, requires
independent annotation and adjudication, and freezes the public execution
bundle before a one-shot prediction. Its administrative self-test passes
10/10 leakage, consistency, tamper, placeholder, and sealing checks. This means
the project is ready to hand to an independent corpus curator; it does **not**
mean the final benchmark has been run. The remaining blockers are 50-80 real
source-bound units, an independently completed oracle, and frozen final runner
adapters.

Before making this repository public, review the third-party source snapshots,
licenses, dataset terms, and the research claims with the project supervisor.

R3-P3b has now run in an isolated Python 3.9.19 environment. All 11 known
admitted leaves construct, 10/11 replay exactly, and all 22 supported Python
wrapper mutations are rejected while 11 native overrides remain Unknown.
The preregistered run still fails 2/8 gates: Albumentations explicitly refuses
to serialize `HistogramMatching` for public replay, and SourceIndexV0 is stable
for only 3/11 units across fresh processes because `repr(code.co_consts)`
contains process addresses and unordered frozenset representations. The next
milestone is P3c recursive constant canonicalization, followed by a separate
framework replay-capability obligation; neither failure is hidden by the
11/11 in-process Supported result.

R3-P3c now passes all 7 preregistered gates. SourceIndexV1 recursively binds
typed constants and nested code without memory addresses or hash-order reprs,
raising fresh-process stability from 3/11 to 11/11 while preserving all
registered entries. Its portable reindex results are 22 wrapper Rejects,
11 native Unknowns, and zero Admits. The repair costs about 1.064x serialized
bytes and 1.042x median-of-medians cold time, so it remains a deployment-time
artifact. The separate `HistogramMatching` replay-capability failure remains
open for P3d capability composition.

R3-P3d now passes all 7 preregistered gates with a separate
`ReplayCapabilityV1` layer rather than modifying EffectV7. The 11 semantic
Admits and 11 stable SourceIndexV1 bindings remain unchanged; capability and
final eligibility are 10 Supported/Admit and one explicit Unsupported.
`HistogramMatching` is still conditionally effect-safe, but the public
Albumentations serializer prohibits its replay record, so it cannot become a
deployment Admit. R3-P3 calibration is now closed; the next mainline work is
adapter-burden accounting and an independently curated final-blind corpus,
not more rule tuning on these known units.

P4A has now completed the adapter-burden audit and preserves a negative result:
only 4/8 frozen adapters meet the preregistered lightweight diagnostic, so the
project cannot claim adapters are generally lightweight or reduce human time.
P4B freezes a dependency-light `ReplayCapabilityV1` JSON schema and validator
(14/14 administrative self-tests). P4C adds `benchmark/final_v2/`, where replay
capability is explicitly scoped only to registered parameter replay; cache and
reorder candidates retain rewrite-specific verification obligations. The v2
handoff administrator passes 20/20 leakage, scope, commitment, and artifact
freeze checks after preserving a 19/20 failed first attempt and protocol-bound
test correction.

Exercise the v2 final-blind administrative handoff without real labels:

```bash
python experiments/autocontract_final_benchmark_admin_v2.py self-test \
  --output outputs/autocontract_p4c_final_blind_v2_selftest.json
python experiments/autocontract_final_benchmark_admin_v2.py validate-public \
  benchmark/final_v2/public_manifest.template.json
```

This is infrastructure readiness only. A real final run remains blocked on an
independently selected 50–80 unit corpus, independently reviewed private oracle,
frozen final adapters/runner, and prospective adapter-time records.

P5A adds a constraint-only bridge to published optimizer interfaces. It emits
cedar-shaped random/fix/dependency hints, HyCache-shaped online-only/cache-prefix
hints, and a Cachew-shaped autocache boundary while leaving all cost, placement,
tier, and ILP decisions to the target optimizer. The final synthetic conformance
test passes 15/15 after preserving two invalid attempts: one exposed missing
ancestor-effect propagation, and one exposed an incorrect protocol-hash binding.

```bash
python experiments/autocontract_p5a_constraint_compiler.py self-test \
  --output outputs/autocontract_p5a_constraint_compiler_selftest.json
```

P5B binds the recipe to a fixed official cedar commit and P5C imports that
checkout in an isolated Python 3.11 runtime, constructs the public API objects,
and executes an optimizer-disabled data path (15/15). P5D then shows actual
cedar cache-plan consumption of the generated `is_random` hint (17/17), while
P5E shows actual reorder candidate/plan consumption of generated `fix` and
`depends_on` hints (17/17).

That integration exposed a safety bug rather than closing the evaluation.
P5F demonstrates that deterministic, stateless, one-to-one functions need not
commute: cedar reordered `x+1 -> 2x -> x-3`, changing outputs from
`[-1,1,3,5,7]` to `[-5,-3,-1,1,3]`. The old claim that P5A purity constraints
can authorize reordering is withdrawn. This is an AutoContract policy failure,
not a cedar bug; cedar expects user-supplied order constraints.

P5G adds `ReorderCapabilityV0`. Reordering now fails closed unless every pair
inside a contiguous unfixed region has exactly one source/context-bound
Supported commutativity receipt. The P5F counterexample is reduced to one plan
with the original output, while three pairwise-commuting functions regain six
candidate plans and preserve output after cedar reorders them (20/20 synthetic
calibration). Missing, stale, Unsupported, or duplicate receipts shrink the
region.

P5H then exposes the remaining trust boundary: V0 verifies receipt shape and
binding, not the proof behind `proof_sha256`. Three forged but syntactically
valid Supported receipts reopen the unsafe P5F plan and change outputs again
(8/8 attack reproduction; system verdict FAIL). V0 is therefore only a
trusted-receipt composition format. Strict deployment must keep every operator
fixed until a V1 locally replays a proof verifier or authenticates an approved,
revocable issuer; finite differential testing alone cannot mint strict
Supported receipts.

```bash
python experiments/autocontract_p5c_cedar_runtime_smoke.py \
  --cedar-root /path/to/fixed/cedar \
  --output outputs/autocontract_p5c_cedar_runtime_smoke.json
python experiments/autocontract_p5d_cedar_optimizer_consumption.py \
  --cedar-root /path/to/fixed/cedar \
  --output outputs/autocontract_p5d_cedar_optimizer_consumption.json
python experiments/autocontract_p5f_reorder_unsoundness.py \
  --cedar-root /path/to/fixed/cedar \
  --output outputs/autocontract_p5f_reorder_unsoundness.json
python experiments/autocontract_p5g_reorder_capability.py \
  --cedar-root /path/to/fixed/cedar \
  --output outputs/autocontract_p5g_reorder_capability.json
python experiments/autocontract_p5h_reorder_receipt_trust.py \
  --cedar-root /path/to/fixed/cedar \
  --output outputs/autocontract_p5h_reorder_receipt_trust.json
```

These are fixed-profile mechanism calibrations, not final evidence. The next
step is ReorderCapabilityV1 proof/issuer verification, followed by a source-bound
real-operator commutativity corpus, independent pair oracle, proof-producer
comparison, and executed one-shot plans. Cache, parameter replay, and reorder
must remain separate evaluation strata.

P5I now implements the first strict `ReorderCapabilityV1` producer/verifier for
a deliberately narrow integer-affine Python subset. It locally replays exact
composition IR, binds the current callable through SourceIndexV1, binds the
verifier plus its indexing dependencies, supports revocation, and rejects V0,
manual, differential-only, stale, tampered, or unsupported claims. On the fixed
cedar checkout it passes 23/23 checks: the P5H forgery remains at one plan, while
three proved translations recover six plans and preserve runtime output.

P5J attempt 0 is retained as a 5/6 failure: all 55 receipt mutations were
rejected, but V0's greedy overlapping-region selection violated evidence
monotonicity in 1/19 subset comparisons. Strict V1 now opens a maximal
base-flexible segment only under complete pair coverage. The repair passes 55/55
mutations, 19/19 subset comparisons, callable-replacement rejection, and the
complete-cover gate (6/6 checks). This remains synthetic mechanism evidence;
the next mainline is a frozen 20–40 real-operator-pair corpus and independent
commutativity oracle, not further affine-fixture expansion.

```bash
python experiments/autocontract_p5i_reorder_capability_v1.py \
  --cedar-root /path/to/fixed/cedar \
  --output outputs/autocontract_p5i_reorder_capability_v1.json
python experiments/autocontract_p5j_reorder_v1_mutation.py \
  --output outputs/autocontract_p5j_reorder_v1_mutation.json
```

P5K then audits 28 known-contaminated real torchvision v2 pairs on an exact
0.15.2+cpu Python-source tree. Under global sequential RNG, bounded probes find
14 concrete counterexamples and leave 14 pairs Unknown; operator-keyed RNG gives
11 counterexamples and 17 Unknown, with three context-dependent contrasts. No
negative differential result is promoted to Supported. The integer-affine V1
producer supports 0/28 real pairs, so proof trust is closed but real proof
coverage is not. P5L should test a small source-bound relation algebra
(identity, pointwise channel maps, spatial index maps/selections) rather than
blindly accepting library calls in the AST verifier.

```bash
python experiments/autocontract_p5k_torchvision_real_pairs.py \
  --output outputs/autocontract_p5k_torchvision_real_pairs.json
```

P5L adds a deliberately small, source-bound `ReorderCapabilityV2` relation
algebra instead of admitting arbitrary library calls into the proof AST. On the
fixed torchvision 0.15.2+cpu tree it locally proves 10 of P5K's 14 Unknown
pairs (71.43%; 10/28 overall) with zero conflict against the 14 known
counterexamples. Eight proof/verifier/source/domain/config/duplicate/revocation
attacks fail closed. A real cedar chain of `Identity`, `Normalize`, and
`CenterCrop` regains six candidate plans from one; cedar changes the order but
all five output digests remain exact (`max_abs_delta=0`). This is still
known-corpus calibration. P5M should attack shape/channel/dtype/config
boundaries and a random-chain RNG post-state before adding interpolation,
boundary, or rounding lemmas.

```bash
python experiments/autocontract_p5l_torchvision_relation_algebra.py \
  --cedar-root /path/to/fixed/cedar \
  --output outputs/autocontract_p5l_torchvision_relation_algebra.json
```

P5M freezes P5L and attacks the handwritten semantic bridge rather than adding
new relation families. All 15 domain/totality mutations and 13 operator-config
mutations fail before receipt issuance. Across 864 admitted boundary trials,
both execution orders have exact outputs and identical Python, NumPy, and torch
RNG post-state. A random cedar `Normalize`/`RandomCrop`/`Identity` chain regains
six candidates from one, changes path, and preserves eight exact outputs plus
RNG post-state. The result also records non-trivial burden: a 2,928-byte receipt,
about 80.5/101.8 ms median generation/verification, and 208 semantic-adapter
SLOC. The next scientific step is independent reorder-pair selection and a
sealed oracle, not further tuning on the known P5K corpus.

```bash
python experiments/autocontract_p5m_relation_boundary_falsification.py \
  --cedar-root /path/to/fixed/cedar \
  --output outputs/autocontract_p5m_relation_boundary_falsification.json
```

P5N stops known-corpus rule tuning and makes the reorder-final handoff
machine-checkable. Separate public, private-oracle, and sealed-prediction schemas
enforce 20–40 pairs, three frameworks, two domains, exact source/config/input/RNG
context, two-person `Commutes`/`Noncommutes`/`Unknown` annotation, salted oracle
commitment, public artifact freeze, prediction seal, and safety-first reveal.
Attempt 0 is retained because the leakage scanner incorrectly rejected the
legitimate prediction field `receipt_sha256`; separate public/prediction policies
repair it. The final synthetic administrative test passes 30/30, including
post-commit/post-seal tampering and an intentional unsafe-Supported gate failure.
No synthetic label or score is scientific evidence: real independent selectors,
annotators, and an oracle custodian are still required.

```bash
python experiments/autocontract_p5n_reorder_final_handoff.py self-test \
  --output outputs/autocontract_p5n_reorder_final_handoff_selftest.json
```

P5O-P5Q close the final-v3 administrative and cedar-workload chain. P5O adds
domain/native-assurance accounting and an 8-pair contaminated dry run; P5P turns
final-v3 into executable validation, commitment, freeze, seal, and reveal CLI
checks; P5Q then runs the cedar-to-ResNet18 workload calibration. P5Q preserves
tensor, RNG, loss, logits, gradient, and final-model identity, but its guarded
preprocessing median is about 1.057x the baseline, so it is semantic propagation
evidence, not a benefit claim.

P5R and P5S test whether the mechanism can survive a larger image workload.
P5S completes the DIV2K warm-cache CPU end-to-end semantic, freeze, and audit
checks, but the preregistered 30-pair bootstrap ratio CI upper bound is
0.952507, which misses the `<0.95` benefit gate. The correct verdict is
mechanism success and benefit No-Go.

P5T attempt3-v4 then performs a single authorized fresh 8-block M0 calibration
after closing the missing no-data prerequisites, freeze-v8, launcher-v8, and
execution-v8 chain. The aggregate SHA-256 is
`8801942b31a08850c83e5694b6c52a3dcf3568754cbb2147543eafbf68cdf7c4`, and all
eight registered symmetric points validate with `fresh_attempt_only=true` and
`old_partial_aggregate=false`. The aggregate is explicitly
`scientific_evidence=false`: it allows pointwise calibration description only,
not pooling, CI, Go/No-Go, overall acceleration, generalization, causal, cold
cache, GPU, or formal test-set performance claims. See the
[P5T postmortem](.research/semantics_safe_reconfiguration/p5t_attempt3_v4_calibration_postmortem.zh-CN.md).
