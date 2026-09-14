# AutoContract R3-P3a context-compatible cross-framework transfer

Status: **pass** (11/11 harness checks).

> Posthoc transfer on already-known H7 corpora; not blind evidence.

## Context gate

| Framework | Registered context | Replay-transfer status | Units in accuracy denominator |
|---|---|---|---:|
| TorchIO | legacy sample_apply | Unsupported: no frozen replay_apply evidence | 0/7 |
| imgaug | deterministic / replay_apply | Eligible RNG-state replay | 8/8 |
| Albumentations | stored params / replay_apply | Eligible parameter-record replay | 8/8 |

## Frozen EffectV7 transfer

Eligible units: 16; TP=11, FP=0, FN=0, TN=5; safe recall=100.0%; reason accuracy=100.0%.
Replay semantic families: parameter_record_replay, rng_state_restoration. New analyzer/adapter rules: 0.

## Source binding transfer boundary

Partial static AST slices: 11/11 admitted units, 63 method records, 11029 bytes.
These slices bind declared reachable method ASTs but do not measure defaults, closures, globals, native dependencies, runtime origins or monkeypatch state.
Full P2b runtime measured-index readiness: 0/2 eligible frameworks in the frozen environment (imgaug missing cv2; Albumentations missing pydantic and cv2).

## Interpretation

The configuration/phase representation transfers posthoc across two distinct replay families without rule changes, but the runtime measured-source mechanism does not yet have cross-framework execution evidence. TorchIO H7C cannot be pooled into replay accuracy because its frozen units answer a sample_apply question.
