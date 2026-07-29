# AutoContract H7K registered Kornia replay

Correctness/security tests: 14/14.
Registration: 21.989 ms for pool size 4.
Concurrent minimal receipts: 100/100 correct calls in 1934.145 ms (51.7 calls/s).
Target slots observed: [0, 1, 2, 3]; errors: 0.

| Test | Pass | Detail |
|---|---|---|
| auto_leaf_proofs | True | d5cb174801f94a4312fc7a552ad961a4b02c3f3502254848bc96ea38a74ba52d |
| registration_binds_pool_and_child_proofs | True | 2c04b16face5496a23ceab8cf0eabe6dda34ca040508e29469951faac6affad3 |
| minimal_output_trace_without_output_digest | True | 99f2d91a2558abdee237b1f6fd91427c4ac5d4a90bd0bcce4f7877b3dc250c62 |
| audit_output_trace_with_output_digest | True | 99f2d91a2558abdee237b1f6fd91427c4ac5d4a90bd0bcce4f7877b3dc250c62 |
| wrong_sample_zero_operator_calls | True | sample_lineage_mismatch |
| wrong_input_schema_zero_operator_calls | True | input_schema_mismatch |
| original_record_mutation_isolated | True | 99f2d91a2558abdee237b1f6fd91427c4ac5d4a90bd0bcce4f7877b3dc250c62 |
| registered_gradient_trace | True | direct=04840a7f1b611f4fd8d6e3400415e34fce465d70db824dfd775bfc9c4fb0329b,registered=04840a7f1b611f4fd8d6e3400415e34fce465d70db824dfd775bfc9c4fb0329b |
| changed_target_rejected_at_registration | True | target[0]:operator_graph_mismatch |
| missing_child_proof_rejected_at_registration | True | target[0]:unsupported_child_effect:RandomAffine_1 |
| operator_mutation_output_not_released | True | operator_mutated_working_record |
| private_pool_concurrent_correctness | True | calls=100/100,errors=[],slots=[0, 1, 2, 3] |
| concurrent_replay_rng_unchanged | True | 4772f27ab7ef391cf2939ccc7d036a33df65537046418855db703ffc554a3290 |
| executor_accounting | True | {"operator_invocations": 103, "rejected_calls": 2, "successful_calls": 103} |

Static graph, version, leaf-proof, and child-composition checks are cached at registration. Each call still verifies sample lineage and input schema, copies the private parameter snapshot, leases an owned target, and checks the post-use parameter digest before releasing output.
