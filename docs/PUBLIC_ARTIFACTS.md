# Public research artifacts

Updated 2026-10-14. This publication is a curated research snapshot. It is not a release of a general optimizer, a full native-runtime reproduction package, or an independent benchmark result.

## Reading order

1. [Research summary (Chinese)](research_summary_2026-10-14.zh-CN.md)
2. [Focused roadmap (Chinese)](research_roadmap.zh-CN.md)
3. [Critical assessment (Chinese)](../review/research_assessment_2026-10-14.zh-CN.md)
4. [Public evidence projections](../reports/research/2026-10-14/README.md)

## What is included

The new package contains a claim-bounded summary, a focused plan, an assessment, selected historical result tables, exact copies of the existing pure symbolic models and their standard-library helpers, and a public projection of four saved conditional model examples.

The projections record the SHA-256 of the original local research records and retain their evidence limitations. They omit machine telemetry, absolute local paths, native dependency closures and unrelated result fields. They are new derived artifacts; they do not replace or rewrite original frozen results. A recorded source hash is a provenance anchor, not proof of an independent audit.

Historical files elsewhere in this branch retain their original time-specific conclusions. Mandatory human handoff requirements in old protocols are historical; the current plan treats manual hints and human oracle input as optional. Neither optional human input nor a successful model check grants execution permission.

## Safe offline check

With Python 3.11, from the repository root:

```sh
python -B experiments/check_published_model_examples.py
```

This checks the packaged model-source bindings and four saved conditional model relations, then verifies that targeted changes to context or certificate are rejected. It uses only the standard library. It does not load Torch, build tensors or models, access images, install drivers, collect temperatures, profile or train.

The check reconstructs the trusted model derivations. It does not verify native kernels, live runtime guards, source-to-model mappings, the ownership of arbitrary Python programs, or the full Cedar API. Historical environment manifests are not a portable installation recipe, and historical experiment entry points should not be run as a generic test suite.

## What remains local

Machine-bound frozen launchers, raw failure/partial state, system installation records, private oracle material, datasets, temporary PDF extracts/previews and third-party installers/DLLs are not added by this publication. Existing local originals are preserved. Historical partial performance, including the restricted P5T v13 material, is not read or exported.

The publication does not resume profiling or training. Public snapshots contain no actual hardware readiness claim; local resource preparation has been deferred.
