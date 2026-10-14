#!/usr/bin/env python3
"""Create the one-time, review-anchored P5S confirm/aggregate launcher."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "experiments" / "autocontract_p5s_div2k_e2e.py"
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5s_div2k_e2e_protocol.json"
FREEZE = ROOT / "benchmark" / "final_v1" / "p5s_div2k_execution_freeze.json"
LAUNCHER = ROOT / "experiments" / "autocontract_p5s_frozen_launcher.py"
HEX64 = set("0123456789abcdef")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def is_sha256(value: str) -> bool:
    return len(value) == 64 and set(value) <= HEX64


def launcher_source(runner_sha: str, protocol_sha: str, freeze_sha: str) -> str:
    return f'''#!/usr/bin/env python3
"""Review-anchored launcher; generated once by autocontract_p5s_frozen_launcher_generator.py."""
from __future__ import annotations

import argparse, hashlib, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "experiments" / "autocontract_p5s_div2k_e2e.py"
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5s_div2k_e2e_protocol.json"
FREEZE = ROOT / "benchmark" / "final_v1" / "p5s_div2k_execution_freeze.json"
EXPECTED_RUNNER_SHA = "{runner_sha}"
EXPECTED_PROTOCOL_SHA = "{protocol_sha}"
EXPECTED_FREEZE_SHA = "{freeze_sha}"

def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cedar-root", required=True)
    parser.add_argument("--mode", required=True, choices=("confirm", "aggregate"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--profile-output")
    parser.add_argument("--fold", choices=("A", "B"))
    parser.add_argument("--confirm-output", action="append")
    args = parser.parse_args()
    if sha(RUNNER) != EXPECTED_RUNNER_SHA or sha(PROTOCOL) != EXPECTED_PROTOCOL_SHA or sha(FREEZE) != EXPECTED_FREEZE_SHA:
        raise SystemExit("frozen launcher anchor mismatch")
    command = [sys.executable, str(RUNNER), "--cedar-root", args.cedar_root, "--mode", args.mode, "--output", args.output, "--expected-freeze-sha", EXPECTED_FREEZE_SHA, "--launcher-path", str(Path(__file__).resolve()), "--launcher-sha", sha(Path(__file__).resolve())]
    if args.profile_output is not None: command += ["--profile-output", args.profile_output]
    if args.fold is not None: command += ["--fold", args.fold]
    for path in args.confirm_output or []: command += ["--confirm-output", path]
    return subprocess.run(command, check=False).returncode

if __name__ == "__main__": raise SystemExit(main())
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-freeze-sha", required=True)
    args = parser.parse_args()
    require(is_sha256(args.approved_freeze_sha), "approved_freeze_sha_invalid")
    require(FREEZE.is_file() and sha(FREEZE) == args.approved_freeze_sha, "approved_freeze_sha_not_current")
    require(not LAUNCHER.exists(), "canonical_launcher_already_exists")
    LAUNCHER.write_text(launcher_source(sha(RUNNER), sha(PROTOCOL), args.approved_freeze_sha), encoding="utf-8")
    print(sha(LAUNCHER))
    return 0


if __name__ == "__main__": raise SystemExit(main())
