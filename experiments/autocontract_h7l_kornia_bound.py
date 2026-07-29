"""H7L runtime evaluation: signed provenance bound to H7K Kornia replay."""

from __future__ import annotations

import argparse
import base64
import copy
import csv
import json
import sys
import threading
from dataclasses import asdict, replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7h_corpus" / "kornia_repo"
OUT = ROOT / "outputs"
sys.path[:0] = [str(ROOT / "experiments"), str(REPO)]

import torch  # noqa: E402
import kornia  # noqa: E402

import autocontract_h7i_lineage_certificate as lineage  # noqa: E402
import autocontract_h7i_kornia_reconfiguration as pilot  # noqa: E402
import autocontract_h7j_auto_leaf_proofs as auto  # noqa: E402
import autocontract_h7k_registered_executor as registered  # noqa: E402
import autocontract_h7l_bound_executor as bound  # noqa: E402
import autocontract_h7l_provenance_token as provenance  # noqa: E402


SAMPLE_ID = "h7l/sample17"


def row(name: str, passed: bool, detail: str) -> dict[str, object]:
    return {"test": name, "passed": passed, "detail": detail}


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def make_executor(
    source: object,
    input_value: torch.Tensor,
    params: object,
    policy: dict[str, lineage.Decision],
    proof_digest: str,
) -> registered.RegisteredReplayExecutor:
    return registered.RegisteredReplayExecutor.register(
        framework="kornia",
        framework_version=kornia.__version__,
        repository_commit=pilot.COMMIT,
        source_operator=source,
        target_factory=pilot.build_pipeline,
        input_value=input_value,
        params=params,
        sample_id=SAMPLE_ID,
        leaf_policy=policy,
        leaf_proof_set_sha256=proof_digest,
        pool_size=1,
        receipt_level="minimal",
    )


def base_expectation(
    input_value: torch.Tensor,
    registration_sha256: str,
) -> provenance.ProvenanceExpectation:
    input_digest = lineage.digest_payload(input_value)
    subjects = (provenance.SubjectClaim("primary", "17", input_digest),)
    manifest = provenance.dataset_manifest_digest({"17": input_digest})
    return provenance.ProvenanceExpectation(
        run_id="train/run-20260729",
        replay_sample_id=SAMPLE_ID,
        dataset_id="pilot-images",
        dataset_revision="sha256:dataset-rev0",
        split="train",
        dataset_manifest_sha256=manifest,
        epoch=3,
        sampler_context_sha256=lineage.digest_payload({"sampler": "sequential", "seed": 81, "epoch": 3}),
        subjects=subjects,
        operator_path="train/input/augment",
        registration_sha256=registration_sha256,
        input_content_sha256=input_digest,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mutation-attempts", type=int, default=50)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.manual_seed(20260802)

    source = pilot.build_pipeline()
    input_value = torch.rand(4, 3, 64, 64)
    with torch.no_grad():
        recorded_output = source(input_value)
    params = copy.deepcopy(source._params)
    proofs = auto.generate_leaf_proofs(source)
    leaf_policy = auto.policy_from_proofs(proofs)
    proof_digest = lineage.digest_payload([asdict(proof) for proof in proofs])
    executor = make_executor(source, input_value, params, leaf_policy, proof_digest)

    registry_path = OUT / "autocontract_h7l_kornia_registry.sqlite"
    registry = provenance.SqliteReplayRegistry(registry_path, reset=True, persistent_connections=True)
    authority = provenance.ProvenanceAuthority.generate(registry)
    verifier = provenance.ProvenanceVerifier(authority.public_key_bytes(), registry)
    expected = base_expectation(input_value, executor.registration_receipt.registration_sha256)
    secured = bound.ProvenanceBoundExecutor(executor, verifier, expected)

    valid = authority.issue(expected)
    rng_before = torch.get_rng_state().clone()
    output, receipt = secured.apply(input_value=input_value, token=valid, consumer_id="main/0")
    rng_after = torch.get_rng_state().clone()
    tests: list[dict[str, object]] = [
        row(
            "valid_token_output_trace",
            torch.equal(output, recorded_output),
            lineage.digest_payload(output),
        ),
        row(
            "token_registration_apply_binding",
            receipt.token_sha256 == valid.token_sha256
            and receipt.apply_receipt.registration_sha256 == expected.registration_sha256,
            receipt.provenance_payload_sha256,
        ),
        row("valid_token_rng_unchanged", torch.equal(rng_before, rng_after), lineage.digest_payload(rng_before)),
    ]

    before = executor.stats()
    try:
        secured.apply(input_value=input_value, token=valid, consumer_id="main/duplicate")
        duplicate_ok, duplicate_detail = False, "not_rejected"
    except provenance.ProvenanceRejected as error:
        after = executor.stats()
        duplicate_ok = after.operator_invocations == before.operator_invocations and "token_consumed" in error.reasons
        duplicate_detail = ";".join(error.reasons)
    tests.append(row("duplicate_token_zero_operator_calls", duplicate_ok, duplicate_detail))

    x_direct = input_value.clone().requires_grad_(True)
    x_bound = input_value.clone().requires_grad_(True)
    direct_output = pilot.build_pipeline()(x_direct, params=copy.deepcopy(params))
    gradient_token = authority.issue(expected)
    bound_output, _ = secured.apply(input_value=x_bound, token=gradient_token, consumer_id="main/gradient")
    weight = torch.linspace(0.5, 1.5, direct_output.numel()).reshape_as(direct_output)
    (direct_output * weight).sum().backward()
    (bound_output * weight).sum().backward()
    tests.append(row(
        "sealed_input_preserves_gradient_trace",
        torch.equal(x_direct.grad, x_bound.grad),
        f"direct={lineage.digest_payload(x_direct.grad)},bound={lineage.digest_payload(x_bound.grad)}",
    ))

    attacks: list[tuple[str, provenance.ProvenanceExpectation]] = [
        ("wrong_run", replace(expected, run_id="train/other")),
        ("wrong_replay_sample", replace(expected, replay_sample_id="h7l/sample18")),
        ("wrong_dataset_revision", replace(expected, dataset_revision="sha256:dataset-rev1")),
        ("wrong_manifest", replace(expected, dataset_manifest_sha256="0" * 64)),
        ("wrong_epoch", replace(expected, epoch=4)),
        ("wrong_sampler", replace(expected, sampler_context_sha256="1" * 64)),
        (
            "wrong_subjects",
            replace(
                expected,
                subjects=expected.subjects + (provenance.SubjectClaim("partner", "18", "2" * 64),),
            ),
        ),
        ("wrong_operator_path", replace(expected, operator_path="eval/input/augment")),
        ("wrong_registration", replace(expected, registration_sha256="3" * 64)),
        ("wrong_input_claim", replace(expected, input_content_sha256="4" * 64)),
    ]
    for name, wrong_claim in attacks:
        attack_token = authority.issue(wrong_claim)
        before = executor.stats()
        try:
            secured.apply(input_value=input_value, token=attack_token, consumer_id=f"attack/{name}")
            passed, detail = False, "not_rejected"
        except provenance.ProvenanceRejected as error:
            after = executor.stats()
            passed = after.operator_invocations == before.operator_invocations
            detail = ";".join(error.reasons)
        tests.append(row(name + "_zero_operator_calls", passed, detail))

    content_token = authority.issue(expected)
    changed_input = input_value.clone()
    changed_input.reshape(-1)[0] += 1.0
    before = executor.stats()
    try:
        secured.apply(input_value=changed_input, token=content_token, consumer_id="attack/content")
        content_ok, content_detail = False, "not_rejected"
    except provenance.ProvenanceRejected as error:
        after = executor.stats()
        content_ok = after.operator_invocations == before.operator_invocations
        content_detail = ";".join(error.reasons)
    tests.append(row("changed_input_bytes_zero_operator_calls", content_ok, content_detail))

    revoked_token = authority.issue(expected)
    registry.revoke(revoked_token.token_sha256)
    before = executor.stats()
    try:
        secured.apply(input_value=input_value, token=revoked_token, consumer_id="attack/revoked")
        revoked_ok, revoked_detail = False, "not_rejected"
    except provenance.ProvenanceRejected as error:
        after = executor.stats()
        revoked_ok = after.operator_invocations == before.operator_invocations and "token_revoked" in error.reasons
        revoked_detail = ";".join(error.reasons)
    tests.append(row("revoked_token_zero_operator_calls", revoked_ok, revoked_detail))

    other_authority = provenance.ProvenanceAuthority.generate(registry)
    other_token = other_authority.issue(expected)
    before = executor.stats()
    try:
        secured.apply(input_value=input_value, token=other_token, consumer_id="attack/key")
        key_ok, key_detail = False, "not_rejected"
    except provenance.ProvenanceRejected as error:
        after = executor.stats()
        key_ok = after.operator_invocations == before.operator_invocations and "unknown_signing_key" in error.reasons
        key_detail = ";".join(error.reasons)
    tests.append(row("unknown_key_zero_operator_calls", key_ok, key_detail))

    signature_token = authority.issue(expected)
    signature = bytearray(base64.b64decode(signature_token.signature_b64))
    signature[0] ^= 1
    tampered_signature = replace(signature_token, signature_b64=base64.b64encode(signature).decode("ascii"))
    before = executor.stats()
    try:
        secured.apply(input_value=input_value, token=tampered_signature, consumer_id="attack/signature")
        signature_ok, signature_detail = False, "not_rejected"
    except provenance.ProvenanceRejected as error:
        after = executor.stats()
        signature_ok = after.operator_invocations == before.operator_invocations and "invalid_signature" in error.reasons
        signature_detail = ";".join(error.reasons)
    tests.append(row("signature_tamper_zero_operator_calls", signature_ok, signature_detail))

    racing_input = input_value.clone()
    stop = threading.Event()
    success_outputs: list[str] = []
    rejected = 0

    def mutate_input() -> None:
        delta = 1.0
        while not stop.is_set():
            with torch.no_grad():
                racing_input.reshape(-1)[0] += delta
            delta = -delta

    mutator = threading.Thread(target=mutate_input, daemon=True)
    mutator.start()
    rng_before_race = torch.get_rng_state().clone()
    for index in range(args.mutation_attempts):
        race_token = authority.issue(expected)
        try:
            race_output, _ = secured.apply(
                input_value=racing_input,
                token=race_token,
                consumer_id=f"race/{index}",
            )
            success_outputs.append(lineage.digest_payload(race_output))
        except provenance.ProvenanceRejected:
            rejected += 1
    stop.set()
    mutator.join(timeout=2.0)
    rng_after_race = torch.get_rng_state().clone()
    expected_output_digest = lineage.digest_payload(recorded_output)
    race_ok = set(success_outputs).issubset({expected_output_digest}) and len(success_outputs) + rejected == args.mutation_attempts
    tests.append(row(
        "concurrent_input_mutation_never_releases_mismatched_output",
        race_ok,
        f"success={len(success_outputs)},rejected={rejected},digests={sorted(set(success_outputs))}",
    ))
    tests.append(row(
        "mutation_stress_rng_unchanged",
        torch.equal(rng_before_race, rng_after_race),
        lineage.digest_payload(rng_before_race),
    ))

    write_csv(OUT / "autocontract_h7l_kornia_tests.csv", tests)
    (OUT / "autocontract_h7l_public_key.json").write_text(
        json.dumps({
            "key_id": authority.key_id,
            "public_key_b64": base64.b64encode(authority.public_key_bytes()).decode("ascii"),
        }, indent=2),
        encoding="utf-8",
    )
    passed = sum(item["passed"] is True for item in tests)
    report = "\n".join([
        "# AutoContract H7L signed-provenance Kornia replay",
        "",
        f"Correctness/security tests: {passed}/{len(tests)}.",
        f"Input-mutation stress: {len(success_outputs)} safe successes, {rejected} pre-apply rejects, 0 mismatched outputs across {args.mutation_attempts} attempts.",
        f"Trusted issuer key id: {authority.key_id}.",
        "",
        "| Test | Pass | Detail |",
        "|---|---|---|",
        *[f"| {item['test']} | {item['passed']} | {item['detail']} |" for item in tests],
        "",
        "The input is cloned before content hashing and the clone is consumed, preserving validated-bytes/consumed-bytes equality. "
        "A token is consumed before H7K apply; failed apply requires a newly issued retry token.",
        "",
    ])
    (OUT / "autocontract_h7l_kornia_bound.md").write_text(report, encoding="utf-8")
    print(report)
    if passed != len(tests):
        raise RuntimeError("H7L Kornia evaluation failed")


if __name__ == "__main__":
    main()
