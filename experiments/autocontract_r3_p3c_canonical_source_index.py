"""R3-P3c recursive constant canonicalization calibration."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
import types
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
PROTOCOL = ROOT / "benchmark" / "final_v1" / "r3_p3c_canonical_source_index_protocol_v1.json"
P3B_RUNNER = ROOT / "experiments" / "autocontract_r3_p3b_cross_framework_runtime.py"
P3B_RESULT = OUT / "autocontract_r3_p3b_cross_framework_runtime.json"
V0_PATH = ROOT / "experiments" / "autocontract_r3_source_index.py"
V1_PATH = ROOT / "experiments" / "autocontract_r3_source_index_v1.py"
MANIFEST = OUT / "autocontract_r3_p3b_runtime_manifest.json"
LOCK = OUT / "autocontract_r3_p3b_runtime_lock.txt"

EXPECTED = {
    "protocol": "bec7be39dda3640c106a11aef38a4d167df765db8f114f6dc39a6236d8518dd4",
    "p3b_runner": "63f3a191ff3454e478e0dccb567e904cd45d971faf784e10a254249866b0bbb3",
    "p3b_result": "7b578086772df053d347bd23ece51f26cb2bd06aa91927ad01dbc4cb8c827d02",
    "v0": "02a10103e26cb4a55f646428d7e24f14bdf73b133149e29c220a78f38829ab2b",
    "v1": "7e6251c0388fce23c115919258ac43fb9d620ea38f8902082fe6da7cfbb5238c",
    "manifest": "ec784c445453fb2bb55ce4a30422f865a0d1309bcefe56838a58e3a9f941bff0",
    "lock": "a7df261bf1a8e747b0dc3bec27fc2e837e99f71ccdc0230319c47d152fdd3bdb",
}

os.environ["NO_ALBUMENTATIONS_UPDATE"] = "1"
sys.path.insert(0, str(ROOT / "experiments"))

import autocontract_r3_p3b_cross_framework_runtime as p3b  # noqa: E402
import autocontract_r3_source_index as v0  # noqa: E402
import autocontract_r3_source_index_v1 as v1  # noqa: E402


FIXTURE_GLOBAL = 7


def nested_code_fixture(values: list[int]) -> list[int]:
    return [value + 1 for value in values]


def frozenset_fixture(value: str) -> bool:
    return value in frozenset({"masks", "masks3d"})


def default_fixture(value: int, gain: int = 1) -> int:
    return value * gain


def global_fixture(value: int) -> int:
    return value + FIXTURE_GLOBAL


def wrapped_base(value: int) -> int:
    return value + 1


def wrapper_a(value: int) -> int:
    return wrapped_base(value)


def wrapper_b(value: int) -> int:
    return wrapped_base(value) + 1


wrapper_a.__wrapped__ = wrapped_base  # type: ignore[attr-defined]
wrapper_b.__wrapped__ = wrapped_base  # type: ignore[attr-defined]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def verify_freeze() -> dict[str, bool]:
    actual = {
        "protocol": sha256(PROTOCOL),
        "p3b_runner": sha256(P3B_RUNNER),
        "p3b_result": sha256(P3B_RESULT),
        "v0": sha256(V0_PATH),
        "v1": sha256(V1_PATH),
        "manifest": sha256(MANIFEST),
        "lock": sha256(LOCK),
    }
    checks = {name: actual[name] == EXPECTED[name] for name in EXPECTED}
    checks["python_3_9_19"] = sys.version_info[:3] == (3, 9, 19)
    if not all(checks.values()):
        raise RuntimeError(f"freeze check failed: {checks}; actual={actual}")
    return checks


def portable_bundle(spec: dict[str, Any], deployment: dict[str, Any], module: Any) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    supported = True
    coverage = True
    for name, target, slots in deployment["components"]:
        present = [slot for slot in slots if callable(getattr(target, slot, None))]
        missing = [slot for slot in slots if slot not in present]
        record = module.portable_operator_index(
            target,
            repository_root=deployment["repository_root"],
            callable_names=slots,
        )
        nonempty = bool(present) and bool(record["entries"])
        supported &= record["status"] == "supported" and nonempty
        coverage &= nonempty
        components.append(
            {
                "name": name,
                "requested_slots": list(slots),
                "present_slots": present,
                "missing_slots": missing,
                "index": record,
            }
        )
    payload = {
        "schema": "autocontract.cross-framework-executable-source-bundle.v1",
        "framework": spec["framework"],
        "symbol": spec["symbol"],
        "configuration_sha256": digest_json({"factory": spec["factory"]}),
        "components": components,
    }
    return {
        "status": "supported" if supported else "unknown",
        "coverage": "complete_registered_components" if coverage else "missing_registered_component",
        "sha256": digest_json(payload),
        "payload": payload,
    }


def fixture_digests() -> dict[str, Any]:
    return {
        "nested_code": digest_json(v1.portable_callable_record(nested_code_fixture, ROOT)),
        "frozenset": digest_json(v1.portable_callable_record(frozenset_fixture, ROOT)),
    }


def make_snapshot() -> dict[str, Any]:
    units = []
    for index, spec in enumerate(p3b.unit_specs()):
        deployment = p3b.construct(spec, index)
        first = portable_bundle(spec, deployment, v1)
        second = portable_bundle(spec, deployment, v1)
        units.append(
            {
                "framework": spec["framework"],
                "symbol": spec["symbol"],
                "portable": first,
                "same_process_stable": first["sha256"] == second["sha256"],
            }
        )
    return {
        "schema": "autocontract.r3-p3c-source-index-v1-snapshot.v0",
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", "not_set"),
        "units": units,
        "fixture_digests": fixture_digests(),
    }


def portable_decision(baseline: dict[str, Any], current: dict[str, Any]) -> str:
    if baseline["status"] != "supported" or current["status"] != "supported":
        return "unknown"
    return "admit" if baseline["sha256"] == current["sha256"] else "reject"


_MISSING = object()


def mutation_results(spec: dict[str, Any], deployment: dict[str, Any], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    leaf = deployment["leaf"]
    slot = deployment["mutation_slot"]
    cls = leaf.__class__
    rows: list[dict[str, Any]] = []

    original = getattr(cls, slot)
    previous = cls.__dict__.get(slot, _MISSING)

    def class_delegate_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        return original(self, *args, **kwargs)

    try:
        setattr(cls, slot, class_delegate_wrapper)
        current = portable_bundle(spec, deployment, v1)
        rows.append(
            {
                "attack": "class_delegate_wrapper",
                "decision": portable_decision(baseline, current),
                "raw_drift": current["sha256"] != baseline["sha256"],
                "current_status": current["status"],
            }
        )
    finally:
        if previous is _MISSING:
            delattr(cls, slot)
        else:
            setattr(cls, slot, previous)
        rows[-1]["restored"] = portable_bundle(spec, deployment, v1) == baseline

    previous = leaf.__dict__.get(slot, _MISSING)
    original_bound = getattr(leaf, slot)

    def instance_delegate_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        return original_bound(*args, **kwargs)

    try:
        setattr(leaf, slot, types.MethodType(instance_delegate_wrapper, leaf))
        current = portable_bundle(spec, deployment, v1)
        rows.append(
            {
                "attack": "instance_delegate_wrapper",
                "decision": portable_decision(baseline, current),
                "raw_drift": current["sha256"] != baseline["sha256"],
                "current_status": current["status"],
            }
        )
    finally:
        if previous is _MISSING:
            delattr(leaf, slot)
        else:
            setattr(leaf, slot, previous)
        rows[-1]["restored"] = portable_bundle(spec, deployment, v1) == baseline

    previous = leaf.__dict__.get(slot, _MISSING)
    try:
        setattr(leaf, slot, len)
        current = portable_bundle(spec, deployment, v1)
        rows.append(
            {
                "attack": "instance_native_override",
                "decision": portable_decision(baseline, current),
                "raw_drift": current["sha256"] != baseline["sha256"],
                "current_status": current["status"],
            }
        )
    finally:
        if previous is _MISSING:
            delattr(leaf, slot)
        else:
            setattr(leaf, slot, previous)
        rows[-1]["restored"] = portable_bundle(spec, deployment, v1) == baseline
    return rows


def source_fixtures() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(case: str, expected: str, observed: str) -> None:
        rows.append({"case": case, "expected": expected, "observed": observed, "passed": expected == observed})

    formatting_a = "def f(x):\n    # harmless\n    return x + 1\n"
    formatting_b = "def f( x ):\n\n    return (x+1)\n"
    docstring = 'def f(x):\n    """ignored"""\n    return x + 1\n'
    changed = "def f(x):\n    return x + 2\n"
    base_digest = v1.canonical_source_digest(formatting_a)
    add("format_comment_only", "same", "same" if base_digest == v1.canonical_source_digest(formatting_b) else "different")
    add("docstring_only", "same", "same" if base_digest == v1.canonical_source_digest(docstring) else "different")
    add("executable_ast", "different", "same" if base_digest == v1.canonical_source_digest(changed) else "different")

    before = digest_json(v1.portable_callable_record(default_fixture, ROOT))
    old_defaults = default_fixture.__defaults__
    default_fixture.__defaults__ = (2,)
    after = digest_json(v1.portable_callable_record(default_fixture, ROOT))
    default_fixture.__defaults__ = old_defaults
    add("default_change", "different", "same" if before == after else "different")

    cell = [1]

    def closure(value: int) -> int:
        return value + cell[0]

    before = digest_json(v1.portable_callable_record(closure, ROOT))
    cell[0] = 2
    after = digest_json(v1.portable_callable_record(closure, ROOT))
    add("closure_change", "different", "same" if before == after else "different")

    global FIXTURE_GLOBAL
    before = digest_json(v1.portable_callable_record(global_fixture, ROOT))
    old_global = FIXTURE_GLOBAL
    FIXTURE_GLOBAL = 8
    after = digest_json(v1.portable_callable_record(global_fixture, ROOT))
    FIXTURE_GLOBAL = old_global
    add("referenced_global", "different", "same" if before == after else "different")

    add(
        "wrapper_change",
        "different",
        "same"
        if digest_json(v1.portable_callable_record(wrapper_a, ROOT))
        == digest_json(v1.portable_callable_record(wrapper_b, ROOT))
        else "different",
    )
    namespace_a: dict[str, Any] = {}
    namespace_b: dict[str, Any] = {}
    exec(compile("def forward(x):\n    return x + 1\n", "C:/shadow/a.py", "exec"), namespace_a)
    exec(compile("def forward(x):\n    return x + 1\n", "C:/shadow/b.py", "exec"), namespace_b)
    add(
        "origin_shadow",
        "different",
        "same"
        if digest_json(v1.portable_callable_record(namespace_a["forward"], ROOT))
        == digest_json(v1.portable_callable_record(namespace_b["forward"], ROOT))
        else "different",
    )
    add("native_unknown", "unknown", v1.portable_callable_record(len, ROOT)["status"])
    return rows


def time_index(spec: dict[str, Any], deployment: dict[str, Any], module: Any) -> dict[str, float]:
    samples = []
    for _ in range(5):
        start = time.perf_counter_ns()
        portable_bundle(spec, deployment, module)
        samples.append((time.perf_counter_ns() - start) / 1_000_000)
    return {"median_ms": statistics.median(samples), "min_ms": min(samples), "max_ms": max(samples)}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-only", type=Path)
    args = parser.parse_args()
    freeze_checks = verify_freeze()
    snapshot_parent = make_snapshot()
    if args.snapshot_only is not None:
        args.snapshot_only.write_text(json.dumps(snapshot_parent, indent=2, ensure_ascii=False), encoding="utf-8")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    process_paths = {
        "seed1": OUT / "autocontract_r3_p3c_source_index_v1_process_seed1.json",
        "seed2": OUT / "autocontract_r3_p3c_source_index_v1_process_seed2.json",
    }
    snapshots = {"parent": snapshot_parent}
    for seed, path in (("1", process_paths["seed1"]), ("2", process_paths["seed2"])):
        env = {**os.environ, "PYTHONHASHSEED": seed, "NO_ALBUMENTATIONS_UPDATE": "1"}
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--snapshot-only", str(path)], check=True, env=env)
        snapshots[f"seed{seed}"] = json.loads(path.read_text(encoding="utf-8"))

    by_process = {
        process: {item["symbol"]: item for item in snapshot["units"]}
        for process, snapshot in snapshots.items()
    }
    rows: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for index, spec in enumerate(p3b.unit_specs()):
        deployment = p3b.construct(spec, index)
        old = portable_bundle(spec, deployment, v0)
        candidate = portable_bundle(spec, deployment, v1)
        old_counts = [len(item["index"]["entries"]) for item in old["payload"]["components"]]
        candidate_counts = [len(item["index"]["entries"]) for item in candidate["payload"]["components"]]
        stable = all(
            by_process[process][spec["symbol"]]["portable"]["sha256"] == candidate["sha256"]
            for process in ("parent", "seed1", "seed2")
        )
        mutations = mutation_results(spec, deployment, candidate)
        v0_timing = time_index(spec, deployment, v0)
        v1_timing = time_index(spec, deployment, v1)
        detail = {
            "framework": spec["framework"],
            "symbol": spec["symbol"],
            "v0": {"status": old["status"], "entry_counts": old_counts, "bytes": len(json.dumps(old, sort_keys=True))},
            "v1": {
                "status": candidate["status"],
                "coverage": candidate["coverage"],
                "sha256": candidate["sha256"],
                "entry_counts": candidate_counts,
                "bytes": len(json.dumps(candidate, sort_keys=True)),
            },
            "no_entry_drop": all(new >= prior for prior, new in zip(old_counts, candidate_counts)),
            "same_process_stable": by_process["parent"][spec["symbol"]]["same_process_stable"],
            "three_process_stable": stable,
            "process_digests": {
                process: by_process[process][spec["symbol"]]["portable"]["sha256"] for process in by_process
            },
            "mutations": mutations,
            "timing": {"v0": v0_timing, "v1": v1_timing},
        }
        details.append(detail)
        rows.append(
            {
                "framework": spec["framework"],
                "symbol": spec["symbol"],
                "v0_status": old["status"],
                "v1_status": candidate["status"],
                "no_entry_drop": detail["no_entry_drop"],
                "same_process_stable": detail["same_process_stable"],
                "three_process_stable": detail["three_process_stable"],
                "v0_bytes": detail["v0"]["bytes"],
                "v1_bytes": detail["v1"]["bytes"],
                "v0_median_ms": v0_timing["median_ms"],
                "v1_median_ms": v1_timing["median_ms"],
                "mutation_reject": sum(item["decision"] == "reject" for item in mutations),
                "mutation_unknown": sum(item["decision"] == "unknown" for item in mutations),
                "mutation_admit": sum(item["decision"] == "admit" for item in mutations),
                "all_restored": all(item["restored"] for item in mutations),
            }
        )

    fixtures = source_fixtures()
    cross_fixture_stable = all(
        snapshots["parent"]["fixture_digests"] == snapshots[process]["fixture_digests"]
        for process in ("seed1", "seed2")
    )
    all_mutations = [mutation for item in details for mutation in item["mutations"]]
    gates = {
        "all_11_complete_component_coverage": all(item["v1"]["coverage"] == "complete_registered_components" for item in details),
        "all_11_supported_and_no_v0_entry_drop": all(
            item["v1"]["status"] == "supported" and item["no_entry_drop"] for item in details
        ),
        "all_11_same_and_three_process_stable": all(
            item["same_process_stable"] and item["three_process_stable"] for item in details
        ),
        "portable_mutations_22_reject_11_unknown_0_admit": (
            sum(item["decision"] == "reject" for item in all_mutations) == 22
            and sum(item["decision"] == "unknown" for item in all_mutations) == 11
            and sum(item["decision"] == "admit" for item in all_mutations) == 0
        ),
        "all_33_restore_baseline": len(all_mutations) == 33 and all(item["restored"] for item in all_mutations),
        "all_source_and_constant_fixtures": all(item["passed"] for item in fixtures) and cross_fixture_stable,
        "frozen_inputs_unchanged": all(freeze_checks.values()),
    }
    result = {
        "schema_version": "autocontract.r3-p3c-canonical-source-index-result.v0",
        "protocol_sha256": EXPECTED["protocol"],
        "runner_sha256": sha256(Path(__file__).resolve()),
        "candidate_v1_sha256": EXPECTED["v1"],
        "status": "pass" if all(gates.values()) else "fail",
        "freeze_checks": freeze_checks,
        "gates": gates,
        "units": details,
        "fixtures": fixtures,
        "cross_process_fixture_stable": cross_fixture_stable,
        "process_artifacts": {
            name: {"path": path.name, "sha256": sha256(path)} for name, path in process_paths.items()
        },
    }
    result_path = OUT / "autocontract_r3_p3c_canonical_source_index.json"
    csv_path = OUT / "autocontract_r3_p3c_canonical_source_index.csv"
    fixtures_path = OUT / "autocontract_r3_p3c_source_fixtures.csv"
    report_path = OUT / "autocontract_r3_p3c_canonical_source_index.md"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(csv_path, rows)
    write_csv(fixtures_path, fixtures)

    v0_bytes = sum(item["v0"]["bytes"] for item in details)
    v1_bytes = sum(item["v1"]["bytes"] for item in details)
    v0_times = [item["timing"]["v0"]["median_ms"] for item in details]
    v1_times = [item["timing"]["v1"]["median_ms"] for item in details]
    lines = [
        "# AutoContract R3-P3c canonical SourceIndexV1",
        "",
        f"Preregistered status: **{result['status']}** ({sum(gates.values())}/{len(gates)} gates).",
        "",
        f"- Three-process stable: {sum(item['three_process_stable'] for item in details)}/11 (V0 was 3/11).",
        f"- Supported/no entry drop: {sum(item['v1']['status'] == 'supported' and item['no_entry_drop'] for item in details)}/11.",
        f"- Portable mutation decisions: Reject={sum(item['decision'] == 'reject' for item in all_mutations)}, Unknown={sum(item['decision'] == 'unknown' for item in all_mutations)}, Admit={sum(item['decision'] == 'admit' for item in all_mutations)}.",
        f"- Synthetic fixtures: {sum(item['passed'] for item in fixtures)}/{len(fixtures)}; cross-process constant fixtures={cross_fixture_stable}.",
        f"- Aggregate serialized bytes: V0={v0_bytes:,}, V1={v1_bytes:,} ({v1_bytes / v0_bytes:.3f}x).",
        f"- Per-unit cold-index median of medians: V0={statistics.median(v0_times):.3f} ms, V1={statistics.median(v1_times):.3f} ms.",
        "",
        "## Gates",
        "",
    ]
    for name, passed in gates.items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} `{name}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "P3c repairs deployment-artifact determinism only. It does not change the P3b HistogramMatching replay failure, the frozen EffectV7 decision, native Unknown handling, or concurrent TOCTOU scope.",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": result["status"],
                "gates_passed": sum(gates.values()),
                "gates_total": len(gates),
                "stable": sum(item["three_process_stable"] for item in details),
                "reject": sum(item["decision"] == "reject" for item in all_mutations),
                "unknown": sum(item["decision"] == "unknown" for item in all_mutations),
                "admit": sum(item["decision"] == "admit" for item in all_mutations),
            }
        )
    )


if __name__ == "__main__":
    main()
