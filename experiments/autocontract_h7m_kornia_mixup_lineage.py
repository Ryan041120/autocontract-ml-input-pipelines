"""Posthoc mechanism extension: ordered partner lineage for Kornia MixUp replay."""

from __future__ import annotations

import copy
import csv
import sys
from dataclasses import asdict, replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7h_corpus" / "kornia_repo"
OUT = ROOT / "outputs"
sys.path[:0] = [str(ROOT / "experiments"), str(REPO)]

import torch  # noqa: E402
import kornia  # noqa: E402
import kornia.augmentation as K  # noqa: E402

import autocontract_h7i_lineage_certificate as lineage  # noqa: E402
import autocontract_h7i_kornia_reconfiguration as pilot  # noqa: E402
import autocontract_h7j_auto_leaf_proofs as auto  # noqa: E402
import autocontract_h7k_registered_executor as registered  # noqa: E402
import autocontract_h7l_provenance_token as h7l  # noqa: E402
import autocontract_h7m_batch_lease as h7m  # noqa: E402
import autocontract_h7m_buffered_executor as buffered  # noqa: E402


SAMPLE_ID = "h7m/mixup-batch"


def build_mixup():
    return K.AugmentationSequential(K.RandomMixUpV2(p=1.0))


def row(name: str, passed: bool, detail: str) -> dict[str, object]:
    return {"test": name, "passed": passed, "detail": detail}


def subjects_from_pairs(input_value: torch.Tensor, pairs: torch.Tensor) -> tuple[h7l.SubjectClaim, ...]:
    records = [lineage.digest_payload(input_value[index]) for index in range(len(input_value))]
    subjects: list[h7l.SubjectClaim] = []
    for output_index, partner_index in enumerate(pairs.tolist()):
        subjects.append(h7l.SubjectClaim(f"primary[{output_index}]", str(output_index), records[output_index]))
        subjects.append(h7l.SubjectClaim(f"partner[{output_index}]", str(partner_index), records[partner_index]))
    return tuple(subjects)


def main() -> None:
    torch.set_num_threads(1)
    torch.manual_seed(20260807)
    input_value = torch.rand(4, 3, 32, 32)
    source = build_mixup()
    with torch.no_grad():
        expected_output = source(input_value)
    external_params = copy.deepcopy(source._params)
    pristine_params = copy.deepcopy(source._params)
    pairs = pristine_params[0].data["mixup_pairs"].clone()
    proofs = auto.generate_leaf_proofs(source)
    policy = auto.policy_from_proofs(proofs)
    proof_digest = lineage.digest_payload([asdict(proof) for proof in proofs])
    executor = registered.RegisteredReplayExecutor.register(
        framework="kornia",
        framework_version=kornia.__version__,
        repository_commit=pilot.COMMIT,
        source_operator=source,
        target_factory=build_mixup,
        input_value=input_value,
        params=external_params,
        sample_id=SAMPLE_ID,
        leaf_policy=policy,
        leaf_proof_set_sha256=proof_digest,
        pool_size=1,
        receipt_level="minimal",
    )
    records = {str(index): lineage.digest_payload(input_value[index]) for index in range(len(input_value))}
    expectation = h7l.ProvenanceExpectation(
        run_id="h7m/mixup-run",
        replay_sample_id=SAMPLE_ID,
        dataset_id="h7m-mixup-images",
        dataset_revision="sha256:mixup-rev0",
        split="train",
        dataset_manifest_sha256=h7l.dataset_manifest_digest(records),
        epoch=7,
        sampler_context_sha256=lineage.digest_payload({"sampler": "mixup", "pairs": pairs.tolist()}),
        subjects=subjects_from_pairs(input_value, pairs),
        operator_path="train/input/mixup",
        registration_sha256=executor.registration_receipt.registration_sha256,
        input_content_sha256=lineage.digest_payload(input_value),
    )
    authority = h7m.BatchAuthority.generate()
    verifier = h7m.BatchVerifier(authority.public_key_bytes())
    registry = h7m.SqliteBatchRegistry(
        OUT / "autocontract_h7m_mixup_registry.sqlite", reset=True, persistent_connections=True,
    )
    secured = buffered.BufferedBatchExecutor((executor,), verifier, registry, (expectation,))
    tickets = authority.issue_batch((expectation,), batch_id="h7m/mixup-valid")
    registry.register(tickets[0].root)
    rng_before = torch.get_rng_state().clone()
    outputs, receipt = secured.apply_batch(inputs=(input_value,), tickets=tickets, worker_id="mixup/valid")
    rng_after = torch.get_rng_state().clone()
    tests: list[dict[str, object]] = [
        row(
            "frozen_effectv7_mixup_leaf_proof",
            auto.verify_leaf_proofs(proofs)
            and len(proofs) == 1
            and proofs[0].decision == "admit"
            and proofs[0].public_symbol.endswith("RandomMixUpV2"),
            proof_digest,
        ),
        row("mixup_replay_output_trace", torch.equal(outputs[0], expected_output), receipt.output_sha256),
        row("mixup_replay_rng_unchanged", torch.equal(rng_before, rng_after), lineage.digest_payload(rng_before)),
        row(
            "ordered_subjects_match_parameter_pairs",
            all(
                expectation.subjects[2 * index + 1].sample_key == str(partner)
                for index, partner in enumerate(pairs.tolist())
            ),
            f"pairs={pairs.tolist()},subjects={[item.sample_key for item in expectation.subjects]}",
        ),
    ]

    gradient_tickets = authority.issue_batch((expectation,), batch_id="h7m/mixup-gradient")
    registry.register(gradient_tickets[0].root)
    direct_input = input_value.clone().requires_grad_(True)
    bound_input = input_value.clone().requires_grad_(True)
    direct_output = build_mixup()(direct_input, params=copy.deepcopy(pristine_params))
    bound_output = secured.apply_batch(
        inputs=(bound_input,), tickets=gradient_tickets, worker_id="mixup/gradient",
    )[0][0]
    weight = torch.linspace(0.5, 1.5, direct_output.numel()).reshape_as(direct_output)
    (direct_output * weight).sum().backward()
    (bound_output * weight).sum().backward()
    tests.append(row(
        "mixup_gradient_trace",
        torch.equal(direct_input.grad, bound_input.grad),
        f"direct={lineage.digest_payload(direct_input.grad)},bound={lineage.digest_payload(bound_input.grad)}",
    ))

    wrong_subjects = list(expectation.subjects)
    wrong_subjects[1] = replace(wrong_subjects[1], sample_key=str((int(wrong_subjects[1].sample_key) + 1) % 4))
    wrong_expectation = replace(expectation, subjects=tuple(wrong_subjects))
    wrong_tickets = authority.issue_batch((wrong_expectation,), batch_id="h7m/mixup-wrong-partner")
    registry.register(wrong_tickets[0].root)
    before = executor.stats()
    try:
        secured.apply_batch(inputs=(input_value,), tickets=wrong_tickets, worker_id="mixup/wrong-partner")
        wrong_partner_ok, wrong_partner_detail = False, "not_rejected"
    except h7m.BatchRejected as error:
        after = executor.stats()
        wrong_partner_ok = after.operator_invocations == before.operator_invocations and "leaf_claim_mismatch" in error.reasons
        wrong_partner_detail = ";".join(error.reasons)
    tests.append(row("wrong_partner_mapping_zero_operator_calls", wrong_partner_ok, wrong_partner_detail))

    reordered_input = input_value.flip(0)
    reorder_tickets = authority.issue_batch((expectation,), batch_id="h7m/mixup-input-reorder")
    registry.register(reorder_tickets[0].root)
    before = executor.stats()
    try:
        secured.apply_batch(inputs=(reordered_input,), tickets=reorder_tickets, worker_id="mixup/input-reorder")
        reorder_ok, reorder_detail = False, "not_rejected"
    except h7m.BatchRejected as error:
        after = executor.stats()
        reorder_ok = after.operator_invocations == before.operator_invocations and "leaf_claim_mismatch" in error.reasons
        reorder_detail = ";".join(error.reasons)
    tests.append(row("input_batch_reorder_zero_operator_calls", reorder_ok, reorder_detail))

    with torch.no_grad():
        external_params[0].data["mixup_pairs"].copy_(external_params[0].data["mixup_pairs"].flip(0))
    isolated_tickets = authority.issue_batch((expectation,), batch_id="h7m/mixup-external-mutation")
    registry.register(isolated_tickets[0].root)
    isolated_output = secured.apply_batch(
        inputs=(input_value,), tickets=isolated_tickets, worker_id="mixup/external-mutation",
    )[0][0]
    tests.append(row(
        "external_pair_record_mutation_isolated",
        torch.equal(isolated_output, expected_output),
        lineage.digest_payload(isolated_output),
    ))

    with (OUT / "autocontract_h7m_mixup_tests.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(tests[0]))
        writer.writeheader()
        writer.writerows(tests)
    passed = sum(item["passed"] is True for item in tests)
    report = "\n".join([
        "# H7M Kornia MixUp ordered-partner lineage",
        "",
        f"Posthoc mechanism-extension tests: {passed}/{len(tests)}.",
        f"Recorded mixup_pairs: {pairs.tolist()}.",
        "",
        "| Test | Pass | Detail |",
        "|---|---|---|",
        *[f"| {item['test']} | {item['passed']} | {item['detail']} |" for item in tests],
        "",
        "RandomMixUpV2 was not part of the formal H7H symbol set. This is a posthoc application of the frozen analyzer and H7M lineage mechanism, not a new blind result.",
        "",
    ])
    (OUT / "autocontract_h7m_kornia_mixup_lineage.md").write_text(report, encoding="utf-8")
    print(report)
    registry.close()
    if passed != len(tests):
        raise RuntimeError("H7M MixUp lineage evaluation failed")


if __name__ == "__main__":
    main()
