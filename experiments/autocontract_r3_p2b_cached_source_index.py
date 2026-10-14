"""R3-P2b cached measured-source index and hot-sentinel calibration."""

from __future__ import annotations

import contextlib
import copy
import csv
import hashlib
import inspect
import json
import statistics
import sys
import time
import types
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterator


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
PROTOCOL = ROOT / "benchmark" / "final_v1" / "r3_p2b_cached_source_index_protocol.json"
EXPECTED_PROTOCOL_SHA = "12449c5735794285f5b8d2bc4312c8509da52183419fe6532f127ed1adc41242"
sys.path.insert(0, str(ROOT / "experiments"))
sys.path.insert(0, str(ROOT / ".research" / "semantics_safe_reconfiguration" / "h7h_corpus" / "kornia_repo"))

import torch  # noqa: E402
import kornia  # noqa: E402
import kornia.augmentation as K  # noqa: E402

import autocontract_h7i_lineage_certificate as lineage  # noqa: E402
import autocontract_r3_p2_kornia_invalidation as p2  # noqa: E402
import autocontract_r3_source_index as source_index  # noqa: E402


FIXTURE_GLOBAL = 3


@dataclass
class Prediction:
    policy: str
    case_id: str
    decision: str
    reasons: tuple[str, ...]
    elapsed_ms: float


def digest_json(value: object) -> str:
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def fixture_default(value: int, gain: int = 1) -> int:
    return value + gain


def fixture_global(value: int) -> int:
    return value + FIXTURE_GLOBAL


def fixture_base(value: int) -> int:
    return value


def fixture_wrapper_a(value: int) -> int:
    return fixture_base(value)


def fixture_wrapper_b(value: int) -> int:
    return fixture_base(value) + 1


fixture_wrapper_a.__wrapped__ = fixture_base  # type: ignore[attr-defined]
fixture_wrapper_b.__wrapped__ = fixture_base  # type: ignore[attr-defined]


def replacement_augmentation_forward(self: Any, *args: Any, params: Any = None, data_keys: Any = None) -> Any:
    return args[0] + 0.03125


def instance_forward_override(self: Any, *args: Any, params: Any = None, data_keys: Any = None) -> Any:
    return args[0] + 0.0625


class CallableHolder:
    def __init__(self, forward: Callable[..., Any]) -> None:
        self.forward = forward


def make_closure() -> tuple[Callable[[int], int], list[int]]:
    gain = [1]

    def closure(value: int) -> int:
        return value + gain[0]

    return closure, gain


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def v1_reasons(
    operator: Any,
    input_value: torch.Tensor,
    params: Any,
    certificate: lineage.ReplayLineageCertificate,
) -> list[str]:
    context = p2.CaseContext(
        case_id="runtime",
        operator=operator,
        input_value=input_value,
        params=params,
        sample_id="epoch0/sample17",
        framework_version=kornia.__version__,
        repository_commit=p2.EXPECTED_COMMIT,
        certificate=certificate,
    )
    return p2.v1_reasons(context)


def predict_cached(
    case_id: str,
    operator: Any,
    input_value: torch.Tensor,
    params: Any,
    certificate: lineage.ReplayLineageCertificate,
) -> Prediction:
    start = time.perf_counter_ns()
    reasons = v1_reasons(operator, input_value, params, certificate)
    elapsed = (time.perf_counter_ns() - start) / 1e6
    return Prediction("cached_digest_only", case_id, "reject" if reasons else "admit", tuple(reasons), elapsed)


def predict_hot(
    case_id: str,
    operator: Any,
    input_value: torch.Tensor,
    params: Any,
    certificate: lineage.ReplayLineageCertificate,
    sentinel: source_index.HotSentinel,
) -> Prediction:
    start = time.perf_counter_ns()
    reasons = v1_reasons(operator, input_value, params, certificate)
    decision, sentinel_reasons = source_index.compare_hot_sentinel(sentinel, operator)
    reasons.extend(sentinel_reasons)
    if reasons and decision == "admit":
        decision = "reject"
    if reasons and decision not in {"reject", "unknown"}:
        decision = "reject"
    elapsed = (time.perf_counter_ns() - start) / 1e6
    return Prediction("hot_callable_sentinel", case_id, decision, tuple(dict.fromkeys(reasons)), elapsed)


def predict_cold(
    case_id: str,
    operator: Any,
    input_value: torch.Tensor,
    params: Any,
    certificate: lineage.ReplayLineageCertificate,
    registered_index: dict[str, Any],
    registered_head: str,
) -> Prediction:
    start = time.perf_counter_ns()
    reasons = v1_reasons(operator, input_value, params, certificate)
    actual_head = p2.measured_repository_head()
    actual_index = source_index.portable_operator_index(operator, repository_root=p2.REPO)
    if actual_index["status"] != "supported":
        decision = "unknown"
        reasons.append("unsupported_cold_source_index")
    else:
        if actual_head != registered_head:
            reasons.append("measured_repository_head_mismatch")
        if actual_index["sha256"] != registered_index["sha256"]:
            reasons.append("portable_source_index_mismatch")
        decision = "reject" if reasons else "admit"
    elapsed = (time.perf_counter_ns() - start) / 1e6
    return Prediction("cold_reindex", case_id, decision, tuple(dict.fromkeys(reasons)), elapsed)


@contextlib.contextmanager
def no_change(operator: Any, input_value: torch.Tensor, params: Any) -> Iterator[None]:
    yield


@contextlib.contextmanager
def runtime_state_change(operator: Any, input_value: torch.Tensor, params: Any) -> Iterator[None]:
    with torch.no_grad():
        operator(input_value, params=copy.deepcopy(params))
    yield


@contextlib.contextmanager
def class_callable_replacement(operator: Any, input_value: torch.Tensor, params: Any) -> Iterator[None]:
    original = K.AugmentationSequential.forward

    def wrapper(self: Any, *args: Any, params: Any = None, data_keys: Any = None) -> Any:
        return original(self, *args, params=params, data_keys=data_keys) + 0.03125

    wrapper.__wrapped__ = original  # type: ignore[attr-defined]
    K.AugmentationSequential.forward = wrapper
    try:
        yield
    finally:
        K.AugmentationSequential.forward = original


@contextlib.contextmanager
def same_function_code_replacement(operator: Any, input_value: torch.Tensor, params: Any) -> Iterator[None]:
    target = K.AugmentationSequential.forward
    original_code = target.__code__
    target.__code__ = replacement_augmentation_forward.__code__
    try:
        yield
    finally:
        target.__code__ = original_code


@contextlib.contextmanager
def instance_override(operator: Any, input_value: torch.Tensor, params: Any) -> Iterator[None]:
    operator.forward = types.MethodType(instance_forward_override, operator)
    yield


@contextlib.contextmanager
def native_override(operator: Any, input_value: torch.Tensor, params: Any) -> Iterator[None]:
    operator.forward = torch.relu
    yield


def real_cases() -> list[tuple[str, Callable[[Any, torch.Tensor, Any], Any]]]:
    return [
        ("stable_equivalent_instance", no_change),
        ("stable_after_runtime_state", runtime_state_change),
        ("class_callable_replacement_after_deploy", class_callable_replacement),
        ("same_function_code_replacement_after_deploy", same_function_code_replacement),
        ("instance_forward_override_after_deploy", instance_override),
        ("native_callable_override_after_deploy", native_override),
    ]


def fixture_results() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def row(case_id: str, expected: str, actual: str, detail: str) -> None:
        rows.append({"case_id": case_id, "expected": expected, "actual": actual, "passed": expected == actual, "detail": detail})

    formatting_a = "def f(x):\n    # harmless comment\n    return x + 1\n"
    formatting_b = "def f( x ):\n\n    return (x+1)  # same behavior\n"
    doc_a = "def f(x):\n    \"\"\"first documentation\"\"\"\n    return x + 1\n"
    doc_b = "def f(x):\n    \"\"\"second documentation\"\"\"\n    return x + 1\n"
    executable = "def f(x):\n    return x + 2\n"
    row(
        "comment_and_format_only",
        "same",
        "same" if source_index.canonical_source_digest(formatting_a) == source_index.canonical_source_digest(formatting_b) else "different",
        "canonical AST",
    )
    row(
        "docstring_only",
        "same",
        "same" if source_index.canonical_source_digest(doc_a) == source_index.canonical_source_digest(doc_b) else "different",
        "docstrings stripped",
    )
    row(
        "executable_ast_change",
        "different",
        "same" if source_index.canonical_source_digest(formatting_a) == source_index.canonical_source_digest(executable) else "different",
        "return expression changed",
    )

    default_holder = CallableHolder(fixture_default)
    before = source_index.hot_sentinel(default_holder)
    old_defaults = fixture_default.__defaults__
    fixture_default.__defaults__ = (2,)
    after = source_index.hot_sentinel(default_holder)
    fixture_default.__defaults__ = old_defaults
    row("default_argument_change", "different", "different" if before.digest != after.digest else "same", "hot dependency digest")

    closure, gain = make_closure()
    closure_holder = CallableHolder(closure)
    before = source_index.hot_sentinel(closure_holder)
    gain[0] = 2
    after = source_index.hot_sentinel(closure_holder)
    row("closure_cell_change", "different", "different" if before.digest != after.digest else "same", "closure cell value")

    global FIXTURE_GLOBAL
    global_holder = CallableHolder(fixture_global)
    before = source_index.hot_sentinel(global_holder)
    old_global = FIXTURE_GLOBAL
    FIXTURE_GLOBAL = 4
    after = source_index.hot_sentinel(global_holder)
    FIXTURE_GLOBAL = old_global
    row("referenced_global_change", "different", "different" if before.digest != after.digest else "same", "referenced module global")

    wrap_a = source_index.portable_callable_record(fixture_wrapper_a, ROOT)
    wrap_b = source_index.portable_callable_record(fixture_wrapper_b, ROOT)
    row("decorator_wrapper_change", "different", "different" if digest_json(wrap_a) != digest_json(wrap_b) else "same", "outer and wrapped layers recorded")

    namespace_a: dict[str, Any] = {"__name__": "shadow.module", "__file__": str(ROOT / "shadow_a" / "module.py")}
    namespace_b: dict[str, Any] = {"__name__": "shadow.module", "__file__": str(ROOT / "shadow_b" / "module.py")}
    source = "def forward(value):\n    return value + 1\n"
    exec(compile(source, namespace_a["__file__"], "exec"), namespace_a)
    exec(compile(source, namespace_b["__file__"], "exec"), namespace_b)
    origin_a = source_index.portable_callable_record(namespace_a["forward"], ROOT)
    origin_b = source_index.portable_callable_record(namespace_b["forward"], ROOT)
    row("origin_path_shadow", "different", "different" if digest_json(origin_a) != digest_json(origin_b) else "same", "same code, distinct resolved origin")

    native = source_index.portable_callable_record(len, ROOT)
    row("uninspectable_native_callable", "unknown", native["status"], "native callable fails closed")
    return rows


def median_ms(function: Callable[[], Any], iterations: int) -> float:
    samples = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        function()
        samples.append((time.perf_counter_ns() - start) / 1e6)
    return statistics.median(samples)


def policy_summary(policy: str, predictions: list[Prediction], oracle: dict[str, str]) -> dict[str, Any]:
    rows = [item for item in predictions if item.policy == policy]
    controls = [item for item in rows if oracle[item.case_id] == "admit"]
    required = [item for item in rows if oracle[item.case_id] == "reject"]
    unknowns = [item for item in rows if oracle[item.case_id] == "unknown"]
    return {
        "policy": policy,
        "benign_preservation": sum(item.decision == "admit" for item in controls) / len(controls),
        "required_rejection_recall": sum(item.decision == "reject" for item in required) / len(required),
        "unknown_accuracy": sum(item.decision == "unknown" for item in unknowns) / len(unknowns),
        "false_accepts": sum(oracle[item.case_id] != "admit" and item.decision == "admit" for item in rows),
        "median_ms": statistics.median(item.elapsed_ms for item in rows),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    torch.set_num_threads(1)
    torch.manual_seed(20260730)
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    protocol_sha = file_sha(PROTOCOL)
    oracle = {item["id"]: item["expected"] for item in protocol["real_kornia_cases"]}

    base = p2.build_pipeline()
    input_value = torch.rand(2, 3, 32, 32)
    base(input_value)
    params = copy.deepcopy(base._params)
    certificate = lineage.create_certificate(
        framework="kornia",
        framework_version=kornia.__version__,
        repository_commit=p2.EXPECTED_COMMIT,
        operator=base,
        input_value=input_value,
        params=params,
        sample_id="epoch0/sample17",
    )

    registration_start = time.perf_counter_ns()
    registered_head = p2.measured_repository_head()
    registered_index = source_index.portable_operator_index(base, repository_root=p2.REPO)
    registration_ms = (time.perf_counter_ns() - registration_start) / 1e6

    deployment = p2.build_pipeline()
    deployment_start = time.perf_counter_ns()
    deployment_head = p2.measured_repository_head()
    deployment_index = source_index.portable_operator_index(deployment, repository_root=p2.REPO)
    deployment_revalidation_ms = (time.perf_counter_ns() - deployment_start) / 1e6
    sentinel_start = time.perf_counter_ns()
    deployment_sentinel = source_index.hot_sentinel(deployment)
    sentinel_creation_ms = (time.perf_counter_ns() - sentinel_start) / 1e6

    predictions: list[Prediction] = []
    for case_id, manager in real_cases():
        candidate = p2.build_pipeline()
        candidate_index = source_index.portable_operator_index(candidate, repository_root=p2.REPO)
        if candidate_index["status"] != "supported" or candidate_index["sha256"] != registered_index["sha256"]:
            raise RuntimeError(f"case failed deployment validation before mutation: {case_id}")
        sentinel = source_index.hot_sentinel(candidate)
        with manager(candidate, input_value, params):
            predictions.append(predict_cached(case_id, candidate, input_value, params, certificate))
            predictions.append(predict_hot(case_id, candidate, input_value, params, certificate, sentinel))
            predictions.append(predict_cold(case_id, candidate, input_value, params, certificate, registered_index, registered_head))

    fixtures = fixture_results()
    policies = ["cached_digest_only", "hot_callable_sentinel", "cold_reindex"]
    summaries = [policy_summary(policy, predictions, oracle) for policy in policies]

    stable_candidate = p2.build_pipeline()
    stable_sentinel = source_index.hot_sentinel(stable_candidate)
    sentinel_hot_ms = median_ms(lambda: source_index.compare_hot_sentinel(stable_sentinel, stable_candidate), 200)
    lineage_hot_ms = median_ms(lambda: v1_reasons(stable_candidate, input_value, params, certificate), 100)
    cold_reindex_ms = median_ms(
        lambda: (p2.measured_repository_head(), source_index.portable_operator_index(stable_candidate, repository_root=p2.REPO)),
        5,
    )
    forbidden_sources = "\n".join(
        inspect.getsource(item)
        for item in (
            source_index.compare_hot_sentinel,
            source_index.hot_sentinel,
            source_index._hot_layer,
            source_index._fast_value,
        )
    )
    no_cold_ops_in_hot = all(
        token not in forbidden_sources
        for token in ("subprocess", "inspect.getsource", "portable_operator_index(", "canonical_ast(", "ast.parse(")
    )
    by_key = {(item.policy, item.case_id): item for item in predictions}
    hot_summary = next(item for item in summaries if item["policy"] == "hot_callable_sentinel")
    cold_summary = next(item for item in summaries if item["policy"] == "cold_reindex")
    cache_summary = next(item for item in summaries if item["policy"] == "cached_digest_only")
    checks = {
        "protocol_hash_recorded": protocol_sha == EXPECTED_PROTOCOL_SHA,
        "registration_and_deployment_supported": registered_index["status"] == deployment_index["status"] == "supported",
        "deployment_reproduces_registered_index": registered_head == deployment_head and registered_index["sha256"] == deployment_index["sha256"],
        "hot_preserves_benign_controls": hot_summary["benign_preservation"] == 1.0,
        "hot_rejects_supported_mutations": hot_summary["required_rejection_recall"] == 1.0,
        "hot_native_override_is_unknown": by_key[("hot_callable_sentinel", "native_callable_override_after_deploy")].decision == "unknown",
        "cold_reference_matches_oracle": cold_summary["benign_preservation"] == 1.0 and cold_summary["required_rejection_recall"] == 1.0 and cold_summary["unknown_accuracy"] == 1.0,
        "cached_digest_only_falsified": cache_summary["false_accepts"] >= 3,
        "all_source_fixtures_pass": len(fixtures) == 9 and all(item["passed"] for item in fixtures),
        "hot_latency_gate": sentinel_hot_ms <= 10.0 and sentinel_hot_ms <= 0.1 * cold_reindex_ms,
        "hot_path_has_no_cold_index_operations": no_cold_ops_in_hot,
    }
    status = "pass" if all(checks.values()) else "fail"
    portable_bytes = len(json.dumps(registered_index, sort_keys=True).encode("utf-8"))
    costs = {
        "registration_ms": registration_ms,
        "deployment_revalidation_ms": deployment_revalidation_ms,
        "sentinel_creation_ms": sentinel_creation_ms,
        "sentinel_only_hot_median_ms_200": sentinel_hot_ms,
        "lineage_v1_hot_median_ms_100": lineage_hot_ms,
        "cold_reindex_median_ms_5": cold_reindex_ms,
        "portable_index_bytes": portable_bytes,
        "sentinel_entries": deployment_sentinel.entry_count,
    }
    payload = {
        "schema_version": "autocontract.r3-p2b-cached-source-index.v0",
        "artifact_role": "posthoc_cached_source_binding_calibration_not_blind_evidence",
        "protocol_sha256": protocol_sha,
        "environment": {
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "kornia": kornia.__version__,
            "repository_head": registered_head,
            "device": "cpu",
        },
        "costs": costs,
        "summaries": summaries,
        "predictions": [asdict(item) for item in predictions],
        "source_fixture_results": fixtures,
        "checks": checks,
        "passed": sum(checks.values()),
        "total": len(checks),
        "status": status,
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "autocontract_r3_p2b_cached_source_index.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    prediction_rows = [
        {
            "policy": item.policy,
            "case_id": item.case_id,
            "expected": oracle[item.case_id],
            "decision": item.decision,
            "reasons": ";".join(item.reasons) or "none",
            "elapsed_ms": f"{item.elapsed_ms:.4f}",
        }
        for item in predictions
    ]
    write_csv(OUT / "autocontract_r3_p2b_cached_source_index.csv", prediction_rows)
    write_csv(OUT / "autocontract_r3_p2b_source_fixtures.csv", fixtures)

    lines = [
        "# AutoContract R3-P2b cached measured-source index",
        "",
        f"Status: **{status}** ({sum(checks.values())}/{len(checks)} harness checks).",
        "",
        "> Posthoc mechanism calibration on known Kornia plus synthetic source fixtures; not blind evidence.",
        "",
        "## Real Kornia policy comparison",
        "",
        "| Policy | Benign preservation | Required rejection recall | Unknown accuracy | False accepts | Median ms/case |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in summaries:
        lines.append(
            f"| {item['policy']} | {item['benign_preservation']:.1%} | {item['required_rejection_recall']:.1%} | "
            f"{item['unknown_accuracy']:.1%} | {item['false_accepts']} | {item['median_ms']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Cost boundaries",
            "",
            f"- Registration index: {registration_ms:.3f} ms.",
            f"- Deployment revalidation: {deployment_revalidation_ms:.3f} ms.",
            f"- Process-local sentinel creation: {sentinel_creation_ms:.3f} ms ({deployment_sentinel.entry_count} entries).",
            f"- Sentinel-only hot check: {sentinel_hot_ms:.4f} ms median over 200 repetitions.",
            f"- Existing lineage-v1 hot validation: {lineage_hot_ms:.4f} ms median over 100 repetitions.",
            f"- Cold reindex reference: {cold_reindex_ms:.3f} ms median over 5 repetitions.",
            f"- Serialized portable index: {portable_bytes} bytes.",
            "",
            "## Interpretation",
            "",
            "A cached portable digest alone is not a runtime source binding: it admits post-deployment class, code-object, and instance mutations. "
            "The process-local sentinel closes those pre-check mutations on this supported replay slice and returns Unknown for a native override, "
            "while keeping Git/source/AST work outside the hot path. It still does not solve mutation concurrent with execution or native internals.",
            "",
        ]
    )
    (OUT / "autocontract_r3_p2b_cached_source_index.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": status, "passed": sum(checks.values()), "total": len(checks)}))
    if status != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
