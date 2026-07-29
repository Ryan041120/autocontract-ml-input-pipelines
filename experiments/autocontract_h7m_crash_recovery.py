"""Process-crash and lost-ack evaluation for H7M fenced batch leases."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

import autocontract_h7m_batch_lease as batch  # noqa: E402


def lease_from_file(path: Path) -> batch.BatchLease:
    return batch.BatchLease(**json.loads(path.read_text(encoding="utf-8")))


def worker_mode(args) -> None:
    registry = batch.SqliteBatchRegistry(args.registry)
    lease = registry.claim(args.batch_id, args.worker_id)
    args.lease_file.write_text(json.dumps(asdict(lease)), encoding="utf-8")
    if args.commit_digest:
        registry.commit(lease, args.commit_digest)
        os._exit(23)  # committed, acknowledgement intentionally never returned
    os._exit(17)  # claimed, computation/commit never happened


def launch_worker(
    registry_path: Path,
    batch_id: str,
    worker_id: str,
    lease_file: Path,
    *,
    commit_digest: str = "",
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--registry",
        str(registry_path),
        "--batch-id",
        batch_id,
        "--worker-id",
        worker_id,
        "--lease-file",
        str(lease_file),
    ]
    if commit_digest:
        command.extend(["--commit-digest", commit_digest])
    kwargs = {"capture_output": True, "text": True, "timeout": 30.0}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(command, **kwargs)  # type: ignore[arg-type]


def main_mode(args) -> None:
    output_dir = ROOT / "outputs"
    registry_path = output_dir / "autocontract_h7m_crash_registry.sqlite"
    registry = batch.SqliteBatchRegistry(registry_path, reset=True, persistent_connections=True)
    authority = batch.BatchAuthority.generate()

    before_tickets = authority.issue_batch(batch._expectations(4), batch_id="crash/before-commit")
    registry.register(before_tickets[0].root)
    before_file = output_dir / "autocontract_h7m_crash_before_lease.json"
    before_process = launch_worker(
        registry_path, "crash/before-commit", "dead-before", before_file,
    )
    before_lease = lease_from_file(before_file)
    state_after_crash = registry.state("crash/before-commit")
    registry.recover(before_lease)
    replacement = registry.claim("crash/before-commit", "replacement")
    try:
        registry.commit(before_lease, "a" * 64)
        stale_rejected, stale_detail = False, "not_rejected"
    except batch.BatchRejected as error:
        stale_rejected = "stale_or_invalid_lease" in error.reasons
        stale_detail = ";".join(error.reasons)
    replacement_commit = registry.commit(replacement, "a" * 64)

    ack_tickets = authority.issue_batch(batch._expectations(4), batch_id="crash/after-commit")
    registry.register(ack_tickets[0].root)
    ack_file = output_dir / "autocontract_h7m_crash_after_lease.json"
    ack_digest = "b" * 64
    ack_process = launch_worker(
        registry_path,
        "crash/after-commit",
        "dead-after",
        ack_file,
        commit_digest=ack_digest,
    )
    ack_lease = lease_from_file(ack_file)
    state_after_ack_loss = registry.state("crash/after-commit")
    idempotent_retry = registry.commit(ack_lease, ack_digest)
    try:
        registry.commit(ack_lease, "c" * 64)
        conflicting_retry_rejected, conflict_detail = False, "not_rejected"
    except batch.BatchRejected as error:
        conflicting_retry_rejected = "committed_batch_conflict" in error.reasons
        conflict_detail = ";".join(error.reasons)

    tests = {
        "process_exited_after_claim_before_commit": before_process.returncode == 17
        and state_after_crash is not None
        and state_after_crash["state"] == "leased",
        "coordinator_recovery_and_replacement_commit": replacement.generation > before_lease.generation
        and not replacement_commit.idempotent,
        "stale_generation_commit_rejected": stale_rejected,
        "process_exited_after_commit_before_ack": ack_process.returncode == 23
        and state_after_ack_loss is not None
        and state_after_ack_loss["state"] == "committed",
        "lost_ack_retry_is_idempotent": idempotent_retry.idempotent,
        "lost_ack_conflicting_digest_rejected": conflicting_retry_rejected,
    }
    payload = {
        "tests": tests,
        "before_commit_exit_code": before_process.returncode,
        "before_commit_state": state_after_crash,
        "stale_commit_detail": stale_detail,
        "after_commit_exit_code": ack_process.returncode,
        "after_commit_state": state_after_ack_loss,
        "conflict_detail": conflict_detail,
        "passed": sum(tests.values()),
        "total": len(tests),
        "all_passed": all(tests.values()),
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    registry.close()
    if not payload["all_passed"]:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--batch-id")
    parser.add_argument("--worker-id")
    parser.add_argument("--lease-file", type=Path)
    parser.add_argument("--commit-digest", default="")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "autocontract_h7m_crash_recovery.json")
    args = parser.parse_args()
    if args.worker:
        worker_mode(args)
    else:
        main_mode(args)


if __name__ == "__main__":
    main()
