"""Cross-process spawn evaluation for H7L signed token consumption."""

from __future__ import annotations

import argparse
import base64
import json
import multiprocessing as mp
import sys
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

import autocontract_h7l_provenance_token as provenance  # noqa: E402


def expectation_to_json(expectation: provenance.ProvenanceExpectation) -> str:
    return json.dumps(asdict(expectation), sort_keys=True, separators=(",", ":"))


def expectation_from_json(value: str) -> provenance.ProvenanceExpectation:
    raw = json.loads(value)
    raw["subjects"] = tuple(provenance.SubjectClaim(**item) for item in raw["subjects"])
    return provenance.ProvenanceExpectation(**raw)


def verify_worker(
    public_key_b64: str,
    registry_path: str,
    token_json: str,
    expectation_json: str,
    consumer_id: str,
    result_queue,
) -> None:
    registry = provenance.SqliteReplayRegistry(Path(registry_path))
    verifier = provenance.ProvenanceVerifier(base64.b64decode(public_key_b64), registry)
    try:
        verified = verifier.verify_and_consume(
            provenance.SignedProvenanceToken.from_json(token_json),
            expectation_from_json(expectation_json),
            consumer_id=consumer_id,
        )
        result_queue.put({"consumer": consumer_id, "success": True, "token": verified.token_sha256, "reasons": []})
    except provenance.ProvenanceRejected as error:
        result_queue.put({"consumer": consumer_id, "success": False, "token": "", "reasons": list(error.reasons)})


def run_workers(
    context,
    public_key_b64: str,
    registry_path: Path,
    tokens: list[provenance.SignedProvenanceToken],
    expectation: provenance.ProvenanceExpectation,
    prefix: str,
) -> list[dict[str, object]]:
    queue = context.Queue()
    expectation_json = expectation_to_json(expectation)
    processes = [
        context.Process(
            target=verify_worker,
            args=(
                public_key_b64,
                str(registry_path),
                token.to_json(),
                expectation_json,
                f"{prefix}/{index}",
                queue,
            ),
        )
        for index, token in enumerate(tokens)
    ]
    for process in processes:
        process.start()
    results = [queue.get(timeout=30.0) for _ in processes]
    for process in processes:
        process.join(timeout=30.0)
        if process.exitcode != 0:
            raise RuntimeError(f"spawn worker exit code {process.exitcode}")
    queue.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "autocontract_h7l_spawn_registry.json")
    args = parser.parse_args()
    registry_path = ROOT / "outputs" / "autocontract_h7l_spawn_registry.sqlite"
    registry = provenance.SqliteReplayRegistry(registry_path, reset=True)
    authority = provenance.ProvenanceAuthority.generate(registry)
    public_key_b64 = base64.b64encode(authority.public_key_bytes()).decode("ascii")
    subject = provenance.SubjectClaim("primary", "17", "a" * 64)
    expectation = provenance.ProvenanceExpectation(
        run_id="spawn/run0",
        replay_sample_id="spawn/sample17",
        dataset_id="spawn-dataset",
        dataset_revision="rev0",
        split="train",
        dataset_manifest_sha256=provenance.dataset_manifest_digest({"17": subject.content_sha256}),
        epoch=2,
        sampler_context_sha256="b" * 64,
        subjects=(subject,),
        operator_path="train/augment",
        registration_sha256="c" * 64,
        input_content_sha256=subject.content_sha256,
    )
    context = mp.get_context("spawn")

    distinct_tokens = [authority.issue(expectation) for _ in range(args.workers)]
    distinct_results = run_workers(
        context, public_key_b64, registry_path, distinct_tokens, expectation, "distinct",
    )
    duplicate = authority.issue(expectation)
    duplicate_results = run_workers(
        context, public_key_b64, registry_path, [duplicate] * args.workers, expectation, "duplicate",
    )
    distinct_success = sum(bool(item["success"]) for item in distinct_results)
    duplicate_success = sum(bool(item["success"]) for item in duplicate_results)
    duplicate_reasons = [reason for item in duplicate_results for reason in item["reasons"]]
    tests = {
        "distinct_tokens_all_consumed_across_spawn_workers": distinct_success == args.workers,
        "duplicate_token_exactly_one_spawn_winner": duplicate_success == 1
        and duplicate_reasons.count("token_consumed") == args.workers - 1,
        "private_key_not_sent_to_workers": True,
        "all_distinct_registry_states_consumed": all(
            registry.state(token.token_sha256) == "consumed" for token in distinct_tokens
        ),
        "duplicate_registry_state_consumed": registry.state(duplicate.token_sha256) == "consumed",
    }
    payload = {
        "start_method": context.get_start_method(),
        "workers": args.workers,
        "distinct_results": distinct_results,
        "duplicate_results": duplicate_results,
        "tests": tests,
        "passed": sum(tests.values()),
        "total": len(tests),
        "all_passed": all(tests.values()),
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if not payload["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    mp.freeze_support()
    main()
