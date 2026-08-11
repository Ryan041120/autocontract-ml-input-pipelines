"""R3-P3d ReplayCapabilityV1 composition calibration."""

from __future__ import annotations

import csv
import hashlib
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
PROTOCOL = ROOT / "benchmark" / "final_v1" / "r3_p3d_replay_capability_protocol.json"
P3A = OUT / "autocontract_r3_p3a_cross_framework_context.json"
P3B = OUT / "autocontract_r3_p3b_cross_framework_runtime.json"
P3C_PROTOCOL = ROOT / "benchmark" / "final_v1" / "r3_p3c_canonical_source_index_protocol_v1.json"
P3C = OUT / "autocontract_r3_p3c_canonical_source_index.json"
V1 = ROOT / "experiments" / "autocontract_r3_source_index_v1.py"
MANIFEST = OUT / "autocontract_r3_p3b_runtime_manifest.json"
LOCK = OUT / "autocontract_r3_p3b_runtime_lock.txt"
EXPECTED = {
    "protocol": "263c1a09a663623780a697160cc71dec1a6270c0ad4fafb71bd2b10bba6378c6",
    "p3a": "b9986a154a653e7242e09554e9527af1571d2690b9fccbe702cae51ecee0f74c",
    "p3b": "7b578086772df053d347bd23ece51f26cb2bd06aa91927ad01dbc4cb8c827d02",
    "p3c_protocol": "bec7be39dda3640c106a11aef38a4d167df765db8f114f6dc39a6236d8518dd4",
    "p3c": "d66a3ef26bf9e9874c023dbbceb5e4ed197587217c038c1f73f3ff2bf63232ca",
    "v1": "7e6251c0388fce23c115919258ac43fb9d620ea38f8902082fe6da7cfbb5238c",
    "manifest": "ec784c445453fb2bb55ce4a30422f865a0d1309bcefe56838a58e3a9f941bff0",
    "lock": "a7df261bf1a8e747b0dc3bec27fc2e837e99f71ccdc0230319c47d152fdd3bdb",
}

sys.path.insert(0, str(ROOT / "experiments"))
import autocontract_r3_p3b_cross_framework_runtime as p3b  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_value(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(p3b.structural(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def verify_freeze() -> dict[str, bool]:
    paths = {
        "protocol": PROTOCOL,
        "p3a": P3A,
        "p3b": P3B,
        "p3c_protocol": P3C_PROTOCOL,
        "p3c": P3C,
        "v1": V1,
        "manifest": MANIFEST,
        "lock": LOCK,
    }
    checks = {name: sha256(path) == EXPECTED[name] for name, path in paths.items()}
    checks["python_3_9_19"] = sys.version_info[:3] == (3, 9, 19)
    if not all(checks.values()):
        raise RuntimeError(f"freeze check failed: {checks}")
    return checks


def compose(semantic: str, capability: str, source: str) -> tuple[str, str]:
    if semantic == "reject":
        return "reject", "semantic_reject"
    if semantic != "admit":
        return "unknown", "semantic_unknown"
    if capability in ("unsupported", "supported_target_dependent_unbound"):
        reason = (
            "target_dependent_operand_not_lineage_bound"
            if capability == "supported_target_dependent_unbound"
            else "framework_replay_capability_unsupported"
        )
        return "unsupported", reason
    if capability != "supported":
        return "unknown", "capability_unknown"
    if source != "supported":
        return "unknown", "source_binding_unknown"
    return "admit", "all_contract_layers_satisfied"


def lineage(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        name: {
            "digest": digest_value(value),
            "structure": p3b.structural(value),
        }
        for name, value in kwargs.items()
    }


def imgaug_capability(spec: dict[str, Any], deployment: dict[str, Any]) -> dict[str, Any]:
    image, second, _ = p3b.fixture()
    start = time.perf_counter_ns()
    replay = p3b.replay_test(spec, deployment)
    receipt = {
        "schema": "autocontract.replay-capability.v1",
        "mechanism": "rng_state_restoration",
        "deterministic": bool(getattr(deployment["pipeline"], "deterministic", False)),
        "public_callable": callable(deployment["pipeline"]),
        "record_serialization": "not_applicable",
        "exact_replay": replay["equivalent"],
        "caller_rng_drift": replay["caller_rng_drift"],
        "lineage": lineage({"image_0": image, "image_1": second}),
        "error": replay["error"],
    }
    supported = (
        receipt["deterministic"]
        and receipt["public_callable"]
        and receipt["exact_replay"]
        and not receipt["caller_rng_drift"]
        and len(receipt["lineage"]) == 2
    )
    receipt["status"] = "supported" if supported else "unknown"
    receipt["reason"] = "all_family_obligations_satisfied" if supported else "rng_restoration_capability_unresolved"
    receipt["probe_ms"] = (time.perf_counter_ns() - start) / 1_000_000
    receipt["bytes"] = len(json.dumps(receipt, sort_keys=True, ensure_ascii=True))
    return receipt


def albumentations_capability(spec: dict[str, Any], deployment: dict[str, Any]) -> dict[str, Any]:
    image, _, reference = p3b.fixture()
    kwargs: dict[str, Any] = {"image": image.copy()}
    if spec["symbol"].endswith("HistogramMatching"):
        kwargs["hm_metadata"] = [reference.copy()]
    leaf = deployment["leaf"]
    target_names = list(getattr(leaf, "targets_as_params", []) or [])
    bound_lineage = lineage(kwargs)
    start = time.perf_counter_ns()
    random.seed(1729)
    np.random.seed(1729)
    before = p3b.caller_rng_digest()
    record_generated = False
    stored_leaf_params = False
    restore_completed = False
    outputs: list[Any] = []
    record_digest: str | None = None
    error: dict[str, str] | None = None
    try:
        recorded = deployment["pipeline"](**kwargs)
        record_generated = isinstance(recorded.get("replay"), dict)
        replay_record = recorded["replay"]
        record_digest = digest_value(replay_record)
        children = replay_record.get("transforms", [])
        stored_leaf_params = len(children) == 1 and children[0].get("params") is not None
        p3b.A.ReplayCompose._restore_for_replay(replay_record)
        restore_completed = True
        outputs.append(recorded["image"])
        for _ in range(3):
            replay_kwargs = {
                key: ([item.copy() for item in value] if isinstance(value, list) else value.copy())
                for key, value in kwargs.items()
            }
            outputs.append(p3b.A.ReplayCompose.replay(replay_record, **replay_kwargs)["image"])
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    after = p3b.caller_rng_digest()
    exact = bool(outputs) and all(p3b.exact_equal(outputs[0], output) for output in outputs[1:])
    target_bound = all(name in bound_lineage for name in target_names)
    framework_prohibition = error is not None and error["type"] == "NotImplementedError"
    supported = (
        record_generated
        and stored_leaf_params
        and restore_completed
        and exact
        and before == after
        and target_bound
    )
    if supported:
        status, reason = "supported", "all_family_obligations_satisfied"
    elif framework_prohibition:
        status, reason = "unsupported", "framework_public_replay_serialization_not_supported"
    elif not target_bound:
        status, reason = "unsupported", "target_dependent_operand_not_lineage_bound"
    else:
        status, reason = "unknown", "public_replay_capability_unresolved"
    receipt = {
        "schema": "autocontract.replay-capability.v1",
        "mechanism": "stored_parameter_record",
        "status": status,
        "reason": reason,
        "record_generated": record_generated,
        "stored_leaf_params": stored_leaf_params,
        "restore_completed": restore_completed,
        "exact_replay": exact,
        "outputs_compared": len(outputs),
        "caller_rng_drift": before != after,
        "target_names": target_names,
        "all_target_operands_lineage_bound": target_bound,
        "lineage": bound_lineage,
        "record_digest": record_digest,
        "error": error,
        "probe_ms": (time.perf_counter_ns() - start) / 1_000_000,
    }
    receipt["bytes"] = len(json.dumps(receipt, sort_keys=True, ensure_ascii=True))
    return receipt


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    freeze_checks = verify_freeze()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    p3a = json.loads(P3A.read_text(encoding="utf-8"))
    p3c = json.loads(P3C.read_text(encoding="utf-8"))
    semantic_by_symbol = {
        item["public_symbol"]: item
        for item in p3a["eligible_predictions"]
        if item["actual"] == "admit"
    }
    source_by_symbol = {item["symbol"]: item for item in p3c["units"]}
    details: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for index, spec in enumerate(p3b.unit_specs()):
        deployment = p3b.construct(spec, index)
        semantic = semantic_by_symbol[spec["symbol"]]["actual"]
        source_record = source_by_symbol[spec["symbol"]]
        source = (
            "supported"
            if source_record["v1"]["status"] == "supported" and source_record["three_process_stable"]
            else "unknown"
        )
        capability = (
            imgaug_capability(spec, deployment)
            if spec["framework"] == "imgaug"
            else albumentations_capability(spec, deployment)
        )
        final, reason = compose(semantic, capability["status"], source)
        detail = {
            "framework": spec["framework"],
            "symbol": spec["symbol"],
            "semantic": {"status": semantic, "configuration": semantic_by_symbol[spec["symbol"]]["configuration"], "phase": semantic_by_symbol[spec["symbol"]]["phase"]},
            "capability": capability,
            "source": {"status": source, "sha256": source_record["v1"]["sha256"], "three_process_stable": source_record["three_process_stable"]},
            "final": {"status": final, "reason": reason},
        }
        details.append(detail)
        rows.append(
            {
                "framework": spec["framework"],
                "symbol": spec["symbol"],
                "semantic": semantic,
                "capability": capability["status"],
                "capability_reason": capability["reason"],
                "source": source,
                "final": final,
                "final_reason": reason,
                "exact_replay": capability["exact_replay"],
                "caller_rng_drift": capability["caller_rng_drift"],
                "lineage_operands": ";".join(capability["lineage"]),
                "receipt_bytes": capability["bytes"],
                "probe_ms": capability["probe_ms"],
            }
        )

    truth_rows = []
    for item in protocol["composition_truth_table"]:
        actual, reason = compose(item["semantic"], item["capability"], item["source"])
        truth_rows.append({**item, "actual": actual, "reason": reason, "passed": actual == item["expected"]})

    histogram = "albumentations.augmentations.mixing.domain_adaptation.HistogramMatching"
    capability_counts = {status: sum(item["capability"]["status"] == status for item in details) for status in ("supported", "unsupported", "unknown")}
    final_counts = {status: sum(item["final"]["status"] == status for item in details) for status in ("admit", "unsupported", "unknown", "reject")}
    histogram_row = next(item for item in details if item["symbol"] == histogram)
    admitted = [item for item in details if item["final"]["status"] == "admit"]
    gates = {
        "all_11_semantic_admit_unchanged": len(details) == 11 and all(item["semantic"]["status"] == "admit" for item in details),
        "all_11_source_supported_and_stable": all(item["source"]["status"] == "supported" and item["source"]["three_process_stable"] for item in details),
        "capability_exactly_10_supported_1_histogram_unsupported": capability_counts == {"supported": 10, "unsupported": 1, "unknown": 0} and histogram_row["capability"]["status"] == "unsupported" and histogram_row["capability"]["reason"] == "framework_public_replay_serialization_not_supported",
        "final_exactly_10_admit_1_unsupported": final_counts == {"admit": 10, "unsupported": 1, "unknown": 0, "reject": 0} and histogram_row["final"]["status"] == "unsupported",
        "all_10_admits_exact_rng_and_lineage": len(admitted) == 10 and all(item["capability"]["exact_replay"] and not item["capability"]["caller_rng_drift"] and bool(item["capability"]["lineage"]) for item in admitted),
        "composition_truth_table_8_of_8": len(truth_rows) == 8 and all(item["passed"] for item in truth_rows),
        "frozen_inputs_unchanged": all(freeze_checks.values()),
    }
    result = {
        "schema_version": "autocontract.r3-p3d-replay-capability-result.v0",
        "artifact_role": "posthoc_capability_composition_not_blind_evidence",
        "protocol_sha256": EXPECTED["protocol"],
        "runner_sha256": sha256(Path(__file__).resolve()),
        "status": "pass" if all(gates.values()) else "fail",
        "freeze_checks": freeze_checks,
        "counts": {"capability": capability_counts, "final": final_counts},
        "gates": gates,
        "units": details,
        "composition_truth_table": truth_rows,
    }
    result_path = OUT / "autocontract_r3_p3d_replay_capability.json"
    csv_path = OUT / "autocontract_r3_p3d_replay_capability.csv"
    truth_path = OUT / "autocontract_r3_p3d_composition_truth_table.csv"
    report_path = OUT / "autocontract_r3_p3d_replay_capability.md"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(csv_path, rows)
    write_csv(truth_path, truth_rows)
    probe_times = [item["capability"]["probe_ms"] for item in details]
    receipt_bytes = [item["capability"]["bytes"] for item in details]
    lines = [
        "# AutoContract R3-P3d ReplayCapabilityV1",
        "",
        f"Preregistered status: **{result['status']}** ({sum(gates.values())}/{len(gates)} gates).",
        "",
        f"- Semantic: Admit={sum(item['semantic']['status'] == 'admit' for item in details)}/11 (unchanged EffectV7).",
        f"- Capability: Supported={capability_counts['supported']}, Unsupported={capability_counts['unsupported']}, Unknown={capability_counts['unknown']}.",
        f"- Final: Admit={final_counts['admit']}, Unsupported={final_counts['unsupported']}, Unknown={final_counts['unknown']}, Reject={final_counts['reject']}.",
        f"- Capability probe median={float(np.median(probe_times)):.3f} ms; receipt median={int(np.median(receipt_bytes)):,} bytes.",
        "",
        "## Layered result",
        "",
        "| Unit | Semantic | Capability | Source | Final |",
        "|---|---|---|---|---|",
    ]
    for item in details:
        lines.append(f"| `{item['symbol']}` | {item['semantic']['status']} | {item['capability']['status']} | {item['source']['status']} | {item['final']['status']} |")
    lines.extend(["", "## Gates", ""])
    for name, passed in gates.items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} `{name}`")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "HistogramMatching remains conditionally semantic-Admit under EffectV7, but the public framework operation is Unsupported because replay record serialization is explicitly prohibited. This separation prevents a feasibility failure from being mislabeled as a semantic effect and prevents semantic Admit from becoming deployment Admit by itself.",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "gates_passed": sum(gates.values()), "gates_total": len(gates), "capability": capability_counts, "final": final_counts}))


if __name__ == "__main__":
    main()
