# AutoContract H7M buffered Merkle-batch Kornia replay

Correctness/security tests: 12/12; batch size: 4.
Root signature verifications performed: 7 across multiple batches; each root is cached only after digest/schema/key authentication.

| Test | Pass | Detail |
|---|---|---|
| heterogeneous_parameter_batch_output_trace | True | 226a60af5d3c43e702166ca6659fddd2f61783bed144ee912fd772349773c987 |
| batch_commit_before_release | True | {'state': 'committed', 'generation': 1, 'lease_id': '6293a36daf729334114ce56b93d04089', 'worker_id': 'main/valid', 'output_sha256': '226a60af5d3c43e702166ca6659fddd2f61783bed144ee912fd772349773c987'} |
| batch_rng_unchanged | True | 3d496d6a8ac856a94f3de336ee65181f2bcf1d86447d2decabfccc9ea7ab264b |
| one_signature_verified_for_batch | True | 1 |
| duplicate_batch_zero_operator_calls | True | batch_committed |
| buffered_batch_gradient_trace | True | e537e0e19a5f6dd1ddbcf79a790dd092f5fecc529d427020825bd1257d9c440f,739e07c357d6d6e879825397b17efb71080862dd4a1171fd7863ed4c3507c2ff,61dff0e97ba5116b4bc3612e168f8f8612bc0efeee2e20ea4e95fa0b77514728,cda7aeda145d089f77cdeace33af6c7e52d847ac2041d37f14f451229486dd4b |
| wrong_input_zero_operator_calls | True | leaf_claim_mismatch |
| ticket_reorder_zero_operator_calls | True | ticket_order_mismatch |
| merkle_proof_tamper_zero_operator_calls | True | merkle_inclusion_mismatch |
| cached_attestation_alias_tamper_rejected | True | batch_attestation_digest_mismatch |
| four_way_batch_claim_one_release | True | success=1,reject=3,invocations=4,reasons=['batch_leased', 'batch_leased', 'batch_leased'] |
| operator_failure_aborts_batch_without_release | True | reasons=('operator_mutated_working_record',),state={'state': 'issued', 'generation': 2, 'lease_id': None, 'worker_id': None, 'output_sha256': None} |

Outputs remain buffered until the fenced lease commits. This provides batch authorization/commit safety, not optimizer-side-effect exactly-once.
