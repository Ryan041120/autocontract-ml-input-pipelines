#!/usr/bin/env python3
"""Review-anchored launcher; generated once by autocontract_p5s_frozen_launcher_generator.py."""
from __future__ import annotations

import argparse, hashlib, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "experiments" / "autocontract_p5s_div2k_e2e.py"
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5s_div2k_e2e_protocol.json"
FREEZE = ROOT / "benchmark" / "final_v1" / "p5s_div2k_execution_freeze.json"
EXPECTED_RUNNER_SHA = "5453de6a8b5c97e6b30999aabbc3a6030b3c586cc6e96b013f10b0ccc501d7cc"
EXPECTED_PROTOCOL_SHA = "d78c1a6c6e662b374dea5624fe2804baeac50564f2505c919d57a26e33e6a77a"
EXPECTED_FREEZE_SHA = "be805691ba027f24d4b1681cb1f8a94635bb365baac9a645dd6dc6481d22b0da"

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
