# AutoContract H7L signed-provenance Kornia replay

Correctness/security tests: 21/21.
Input-mutation stress: 26 safe successes, 24 pre-apply rejects, 0 mismatched outputs across 50 attempts.
Trusted issuer key id: f43633539f8072654a622588ba782bb873834f9ae71acc64f785e8f8a142ddbb.

| Test | Pass | Detail |
|---|---|---|
| valid_token_output_trace | True | 35553126c8b4e450e0a0a97d9d8a2377f2e00c704a12f90d716dd55dfd71ba40 |
| token_registration_apply_binding | True | e590e8c0100114e7484c93ed745451d8e11ee90a49a9a138a5b33dea0df27b5d |
| valid_token_rng_unchanged | True | 7a9e916bddbb5b7f35101bb3e4eb0665cabf45733f9d6bd375ebbf7724bbe446 |
| duplicate_token_zero_operator_calls | True | token_consumed |
| sealed_input_preserves_gradient_trace | True | direct=405ebdc762e7fbd46dfb2766d901280eabc4e2a349f9bfe0ae952a71da41a810,bound=405ebdc762e7fbd46dfb2766d901280eabc4e2a349f9bfe0ae952a71da41a810 |
| wrong_run_zero_operator_calls | True | claim_mismatch:run_id |
| wrong_replay_sample_zero_operator_calls | True | claim_mismatch:replay_sample_id |
| wrong_dataset_revision_zero_operator_calls | True | claim_mismatch:dataset_revision |
| wrong_manifest_zero_operator_calls | True | claim_mismatch:dataset_manifest_sha256 |
| wrong_epoch_zero_operator_calls | True | claim_mismatch:epoch |
| wrong_sampler_zero_operator_calls | True | claim_mismatch:sampler_context_sha256 |
| wrong_subjects_zero_operator_calls | True | claim_mismatch:subjects |
| wrong_operator_path_zero_operator_calls | True | claim_mismatch:operator_path |
| wrong_registration_zero_operator_calls | True | claim_mismatch:registration_sha256 |
| wrong_input_claim_zero_operator_calls | True | claim_mismatch:input_content_sha256 |
| changed_input_bytes_zero_operator_calls | True | claim_mismatch:input_content_sha256 |
| revoked_token_zero_operator_calls | True | token_revoked |
| unknown_key_zero_operator_calls | True | unknown_signing_key;invalid_signature |
| signature_tamper_zero_operator_calls | True | token_digest_mismatch;invalid_signature |
| concurrent_input_mutation_never_releases_mismatched_output | True | success=26,rejected=24,digests=['35553126c8b4e450e0a0a97d9d8a2377f2e00c704a12f90d716dd55dfd71ba40'] |
| mutation_stress_rng_unchanged | True | 7a9e916bddbb5b7f35101bb3e4eb0665cabf45733f9d6bd375ebbf7724bbe446 |

The input is cloned before content hashing and the clone is consumed, preserving validated-bytes/consumed-bytes equality. A token is consumed before H7K apply; failed apply requires a newly issued retry token.
