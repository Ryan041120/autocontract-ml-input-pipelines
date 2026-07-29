# H7I posthoc TOCTOU audit (non-gating)

Pre-mutation certificate decision: admit.
Post-mutation certificate decision: reject (parameter_record_mismatch).
Shared mutated record preserves output: False.
Immutable validated snapshot preserves output: True.

The certificate is sound only if the validated parameter bytes are the bytes used by apply. A separate validate call followed by mutable shared-record use has a TOCTOU gap. The next design must use an immutable snapshot, sealed buffer, or atomic validate-and-apply boundary.
