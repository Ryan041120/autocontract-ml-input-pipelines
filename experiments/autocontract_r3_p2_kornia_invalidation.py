"""R3-P2: decision-equivalent invalidation calibration on a real Kornia replay pipeline.

This is an internal, posthoc adversarial calibration.  A passing harness does
not mean every evaluated policy is correct; policy false accepts are results.
"""

from __future__ import annotations

import ast
import copy
import csv
import hashlib
import inspect
import json
import statistics
import subprocess
import sys
import textwrap
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterator


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7h_corpus" / "kornia_repo"
OUT = ROOT / "outputs"
PROTOCOL = ROOT / "benchmark" / "final_v1" / "r3_p2_kornia_invalidation_protocol.json"
EXPECTED_COMMIT = "d6bb4bf0d8a043c2bb8cef0c346a1b006d100930"
sys.path.insert(0, str(REPO))

import torch  # noqa: E402
import kornia  # noqa: E402
import kornia.augmentation as K  # noqa: E402

import autocontract_h7i_lineage_certificate as lineage  # noqa: E402


LEAF_POLICY: dict[str, lineage.Decision] = {
    "kornia.augmentation._2d.geometric.horizontal_flip.RandomHorizontalFlip": "admit",
    "kornia.augmentation._2d.geometric.affine.RandomAffine": "admit",
    "kornia.augmentation._2d.intensity.color_jiggle.ColorJiggle": "admit",
}
CALLABLE_NAMES = (
    "forward",
    "forward_parameters",
    "generate_parameters",
    "compute_transformation",
    "apply_transform",
    "transform_inputs",
    "transform_masks",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measured_repository_head() -> str:
    return subprocess.check_output(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True, encoding="utf-8"
    ).strip()


def build_pipeline(*, affine_degrees: float = 15.0, reverse: bool = False) -> Any:
    modules = [
        K.RandomHorizontalFlip(p=0.5),
        K.RandomAffine(affine_degrees, p=1.0),
        K.ColorJiggle(0.1, 0.1, 0.1, 0.1, p=1.0),
    ]
    if reverse:
        modules.reverse()
    return K.AugmentationSequential(*modules)


def normalized_ast(source: str) -> str:
    tree = ast.parse(textwrap.dedent(source))
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


def semantic_source_text_digest(source: str) -> str:
    return hashlib.sha256(normalized_ast(source).encode("utf-8")).hexdigest()


def callable_record(value: Callable[..., Any]) -> dict[str, Any]:
    target = inspect.unwrap(value)
    target = getattr(target, "__func__", target)
    identity = {
        "module": getattr(target, "__module__", ""),
        "qualname": getattr(target, "__qualname__", repr(target)),
    }
    try:
        source = inspect.getsource(target)
        return {**identity, "kind": "ast", "semantic_ast": normalized_ast(source)}
    except (OSError, TypeError, IndentationError, SyntaxError):
        code = getattr(target, "__code__", None)
        if code is None:
            return {**identity, "kind": "unsupported", "repr": repr(target)}
        return {
            **identity,
            "kind": "code_object",
            "bytecode_sha256": hashlib.sha256(code.co_code).hexdigest(),
            "constants": repr(code.co_consts),
            "names": list(code.co_names),
        }


def executable_source_record(operator: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    modules = operator.named_modules() if hasattr(operator, "named_modules") else [("", operator)]
    for path, module in modules:
        methods: dict[str, Any] = {}
        for name in CALLABLE_NAMES:
            candidate = getattr(module, name, None)
            if callable(candidate):
                methods[name] = callable_record(candidate)
        for name, candidate in vars(module).items():
            if callable(candidate):
                methods[f"instance:{name}"] = callable_record(candidate)
        records.append(
            {
                "path": str(path),
                "type": f"{module.__class__.__module__}.{module.__class__.__qualname__}",
                "mro": [f"{item.__module__}.{item.__qualname__}" for item in module.__class__.__mro__],
                "methods": methods,
            }
        )
    return records


def executable_source_digest(operator: Any) -> str:
    return lineage.digest_payload(executable_source_record(operator))


def mutate_first_tensor(value: object) -> bool:
    if isinstance(value, torch.Tensor) and value.numel():
        with torch.no_grad():
            flat = value.reshape(-1)
            if value.dtype == torch.bool:
                flat[0] = ~flat[0]
            else:
                flat[0] += 1
        return True
    if isinstance(value, dict):
        return any(mutate_first_tensor(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(mutate_first_tensor(item) for item in value)
    if hasattr(value, "data"):
        return mutate_first_tensor(value.data)
    return False


@dataclass(frozen=True)
class SourceBoundV2:
    lineage_v1: lineage.ReplayLineageCertificate
    measured_repository_head: str
    executable_source_sha256: str


@dataclass
class CaseContext:
    case_id: str
    operator: Any
    input_value: torch.Tensor
    params: Any
    sample_id: str
    framework_version: str
    repository_commit: str
    certificate: lineage.ReplayLineageCertificate


@dataclass
class Prediction:
    policy: str
    case_id: str
    admitted: bool
    outcome: str
    reasons: tuple[str, ...]
    elapsed_ms: float
    calls: int


def invoke(context: CaseContext) -> torch.Tensor:
    with torch.no_grad():
        return context.operator(context.input_value, params=copy.deepcopy(context.params))


def predict_dynamic(context: CaseContext, *, expected_output_digest: str | None = None) -> Prediction:
    start = time.perf_counter_ns()
    calls = 0
    reasons: list[str] = []
    outputs: list[str] = []
    rng_before = torch.get_rng_state().clone()
    try:
        for _ in range(4):
            outputs.append(lineage.digest_payload(invoke(context)))
            calls += 1
    except Exception as exc:  # runtime rejection remains in the denominator
        reasons.append("runtime_crash:" + type(exc).__name__)
        outcome = "crash"
    else:
        outcome = "classified"
        if len(set(outputs)) != 1:
            reasons.append("same_context_output_changed")
        if not torch.equal(rng_before, torch.get_rng_state()):
            reasons.append("runtime_rng_changed")
        if expected_output_digest is not None and outputs[0] != expected_output_digest:
            reasons.append("registered_output_mismatch")
    elapsed = (time.perf_counter_ns() - start) / 1e6
    name = "output_snapshot_guard" if expected_output_digest is not None else "dynamic_reprobe"
    return Prediction(name, context.case_id, not reasons, outcome, tuple(reasons), elapsed, calls)


def v1_reasons(context: CaseContext) -> list[str]:
    validation = lineage.validate_certificate(
        context.certificate,
        framework="kornia",
        framework_version=context.framework_version,
        repository_commit=context.repository_commit,
        operator=context.operator,
        input_value=context.input_value,
        params=context.params,
        sample_id=context.sample_id,
    )
    reasons = list(validation.reasons)
    try:
        composite = lineage.compose_child_contracts(context.operator, context.params, LEAF_POLICY)
        reasons.extend(composite.reasons)
    except Exception as exc:
        reasons.append("composition_crash:" + type(exc).__name__)
    return list(dict.fromkeys(reasons))


def predict_v1(context: CaseContext) -> Prediction:
    start = time.perf_counter_ns()
    reasons = v1_reasons(context)
    elapsed = (time.perf_counter_ns() - start) / 1e6
    return Prediction("lineage_v1", context.case_id, not reasons, "classified", tuple(reasons), elapsed, 0)


def predict_v2(context: CaseContext, registered: SourceBoundV2) -> Prediction:
    start = time.perf_counter_ns()
    reasons = v1_reasons(context)
    current_head = measured_repository_head()
    if current_head != registered.measured_repository_head:
        reasons.append("measured_repository_head_mismatch")
    if executable_source_digest(context.operator) != registered.executable_source_sha256:
        reasons.append("executable_source_mismatch")
    reasons = list(dict.fromkeys(reasons))
    elapsed = (time.perf_counter_ns() - start) / 1e6
    return Prediction("measured_source_v2_candidate", context.case_id, not reasons, "classified", tuple(reasons), elapsed, 0)


@contextmanager
def patched_affine_forward() -> Iterator[None]:
    cls = K.RandomAffine
    original = cls.forward

    def drifted_forward(self: Any, input: Any, *args: Any, **kwargs: Any) -> Any:
        result = original(self, input, *args, **kwargs)
        return result + 0.03125

    cls.forward = drifted_forward
    try:
        yield
    finally:
        cls.forward = original


def case_contexts(
    base_operator: Any,
    input_value: torch.Tensor,
    params: Any,
    certificate: lineage.ReplayLineageCertificate,
) -> list[tuple[CaseContext, Callable[[], Any]]]:
    def make(case_id: str, **changes: Any) -> CaseContext:
        values = {
            "operator": build_pipeline(),
            "input_value": input_value,
            "params": copy.deepcopy(params),
            "sample_id": "epoch0/sample17",
            "framework_version": kornia.__version__,
            "repository_commit": EXPECTED_COMMIT,
            "certificate": certificate,
        }
        values.update(changes)
        return CaseContext(case_id=case_id, **values)

    mutated = copy.deepcopy(params)
    if not mutate_first_tensor(mutated):
        raise RuntimeError("could not create parameter drift")
    missing = copy.deepcopy(params[:-1])
    unsupported = K.AugmentationSequential(torch.nn.Identity(), K.RandomHorizontalFlip(p=1.0))
    unsupported_params = unsupported.forward_parameters(input_value.shape)
    cases = [
        (make("stable_same_instance", operator=base_operator), lambda: _null_context()),
        (make("stable_equivalent_instance"), lambda: _null_context()),
        (make("honest_framework_version_drift", framework_version="0.8.2"), lambda: _null_context()),
        (make("honest_repository_commit_drift", repository_commit="0" * 40), lambda: _null_context()),
        (make("sample_lineage_drift", sample_id="epoch0/sample18"), lambda: _null_context()),
        (make("operator_configuration_drift", operator=build_pipeline(affine_degrees=30.0)), lambda: _null_context()),
        (make("child_order_drift", operator=build_pipeline(reverse=True)), lambda: _null_context()),
        (make("input_schema_drift", input_value=torch.rand(2, 3, 24, 24)), lambda: _null_context()),
        (make("parameter_record_drift", params=mutated), lambda: _null_context()),
        (make("missing_child_record", params=missing), lambda: _null_context()),
        (make("unsupported_child_effect", operator=unsupported, params=unsupported_params), lambda: _null_context()),
        (make("tampered_certificate", certificate=replace(certificate, sample_id="epoch0/sample18")), lambda: _null_context()),
        (make("silent_same_commit_callable_patch"), patched_affine_forward),
    ]
    return cases


@contextmanager
def _null_context() -> Iterator[None]:
    yield


def summarize(policy: str, predictions: list[Prediction], oracle: dict[str, str]) -> dict[str, Any]:
    rows = [item for item in predictions if item.policy == policy]
    tp = sum(oracle[row.case_id] == "admit" and row.admitted for row in rows)
    fp = sum(oracle[row.case_id] == "reject" and row.admitted for row in rows)
    fn = sum(oracle[row.case_id] == "admit" and not row.admitted for row in rows)
    tn = sum(oracle[row.case_id] == "reject" and not row.admitted for row in rows)
    unsafe = sum(value == "reject" for value in oracle.values())
    safe = sum(value == "admit" for value in oracle.values())
    return {
        "policy": policy,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "required_invalidation_recall": tn / unsafe,
        "benign_preservation": tp / safe,
        "reason_coverage": sum(bool(row.reasons) for row in rows if oracle[row.case_id] == "reject") / unsafe,
        "median_ms": statistics.median(row.elapsed_ms for row in rows),
        "total_calls": sum(row.calls for row in rows),
        "crashes": sum(row.outcome == "crash" for row in rows),
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
    protocol_sha = sha256_file(PROTOCOL)
    actual_head = measured_repository_head()
    if actual_head != EXPECTED_COMMIT:
        raise RuntimeError(f"repository drift: {actual_head}")

    base = build_pipeline()
    input_value = torch.rand(2, 3, 32, 32)
    recorded_output = base(input_value)
    params = copy.deepcopy(base._params)
    certificate = lineage.create_certificate(
        framework="kornia",
        framework_version=kornia.__version__,
        repository_commit=EXPECTED_COMMIT,
        operator=base,
        input_value=input_value,
        params=params,
        sample_id="epoch0/sample17",
    )
    registered_v2 = SourceBoundV2(certificate, actual_head, executable_source_digest(base))
    expected_output_digest = lineage.digest_payload(recorded_output)
    oracle = {item["id"]: item["expected"] for item in protocol["cases"]}

    predictions: list[Prediction] = []
    cases = case_contexts(base, input_value, params, certificate)
    for context, manager_factory in cases:
        with manager_factory():
            predictions.append(predict_dynamic(context))
            predictions.append(predict_dynamic(context, expected_output_digest=expected_output_digest))
            predictions.append(predict_v1(context))
            predictions.append(predict_v2(context, registered_v2))

    policies = ["dynamic_reprobe", "output_snapshot_guard", "lineage_v1", "measured_source_v2_candidate"]
    summaries = [summarize(policy, predictions, oracle) for policy in policies]
    by_key = {(item.policy, item.case_id): item for item in predictions}
    formatting_a = "def f(x):\n    # harmless comment\n    return x + 1\n"
    formatting_b = "def f( x ):\n\n    return (x+1)  # same behavior\n"
    executable_change = "def f(x):\n    return x + 2\n"
    checks = {
        "protocol_hash_recorded": protocol_sha == "2a3d60162afe06fb2bb9210d22f0f9d7d19da9cc43e4b484b37731f5096ae28c",
        "repository_commit_verified": actual_head == EXPECTED_COMMIT,
        "thirteen_cases_accounted": len(cases) == 13 and set(oracle) == {item[0].case_id for item in cases},
        "all_policy_predictions_accounted": len(predictions) == 13 * 4,
        "lineage_v1_silent_drift_exposed": by_key[("lineage_v1", "silent_same_commit_callable_patch")].admitted,
        "measured_v2_rejects_silent_drift": not by_key[("measured_source_v2_candidate", "silent_same_commit_callable_patch")].admitted,
        "measured_v2_preserves_benign_controls": next(row for row in summaries if row["policy"] == "measured_source_v2_candidate")["benign_preservation"] == 1.0,
        "canonical_digest_ignores_formatting_comments": semantic_source_text_digest(formatting_a) == semantic_source_text_digest(formatting_b),
        "canonical_digest_detects_executable_change": semantic_source_text_digest(formatting_a) != semantic_source_text_digest(executable_change),
    }
    status = "pass" if all(checks.values()) else "fail"

    certificate_bytes = len(json.dumps(asdict(certificate), sort_keys=True).encode("utf-8"))
    artifact_bytes = {
        "dynamic_reprobe": 0,
        "output_snapshot_guard": len(expected_output_digest.encode("ascii")),
        "lineage_v1": certificate_bytes,
        "measured_source_v2_candidate": certificate_bytes + 40 + 64,
    }
    payload = {
        "schema_version": "autocontract.r3-p2-kornia-invalidation.v0",
        "artifact_role": "posthoc_real_source_invalidation_calibration_not_blind_evidence",
        "protocol_sha256": protocol_sha,
        "environment": {
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "kornia": kornia.__version__,
            "device": "cpu",
            "repository_head": actual_head,
        },
        "artifact_bytes": artifact_bytes,
        "summaries": summaries,
        "predictions": [asdict(item) for item in predictions],
        "checks": checks,
        "passed": sum(checks.values()),
        "total": len(checks),
        "status": status,
    }
    OUT.mkdir(exist_ok=True)
    json_path = OUT / "autocontract_r3_p2_kornia_invalidation.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    csv_rows = []
    for item in predictions:
        csv_rows.append(
            {
                "policy": item.policy,
                "case_id": item.case_id,
                "expected": oracle[item.case_id],
                "predicted": "admit" if item.admitted else "reject",
                "outcome": item.outcome,
                "reasons": ";".join(item.reasons) or "none",
                "elapsed_ms": f"{item.elapsed_ms:.4f}",
                "calls": item.calls,
            }
        )
    write_csv(OUT / "autocontract_r3_p2_kornia_invalidation.csv", csv_rows)

    lines = [
        "# AutoContract R3-P2 Kornia contract invalidation calibration",
        "",
        f"Status: **{status}** ({sum(checks.values())}/{len(checks)} harness checks).",
        "",
        "> Posthoc/adversarial calibration on the known H7I pipeline; not blind evidence.",
        "",
        "## Policy comparison",
        "",
        "| Policy | TP | FP | FN | TN | Invalidation recall | Benign preservation | Median ms | Calls |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            f"| {row['policy']} | {row['tp']} | {row['fp']} | {row['fn']} | {row['tn']} | "
            f"{row['required_invalidation_recall']:.1%} | {row['benign_preservation']:.1%} | "
            f"{row['median_ms']:.3f} | {row['total_calls']} |"
        )
    lines.extend(
        [
            "",
            "## Silent executable drift",
            "",
            f"- lineage_v1: {'ADMIT (false accept)' if by_key[('lineage_v1', 'silent_same_commit_callable_patch')].admitted else 'reject'}.",
            f"- measured_source_v2_candidate: {'admit' if by_key[('measured_source_v2_candidate', 'silent_same_commit_callable_patch')].admitted else 'REJECT'}; reasons="
            + ",".join(by_key[("measured_source_v2_candidate", "silent_same_commit_callable_patch")].reasons)
            + ".",
            "- AST canonicalization control ignores formatting/comments and detects an executable expression change.",
            "",
            "## Interpretation",
            "",
            "The v1 lineage certificate is metadata/graph/record-bound, but it is not yet measured-executable-source-bound: "
            "a same-commit callable replacement can retain the operator repr and pass v1. Any stronger source-bound wording must be withdrawn. "
            "The v2 result is a candidate repair demonstrated on this known pipeline, not a frozen or cross-framework contribution.",
            "",
        ]
    )
    (OUT / "autocontract_r3_p2_kornia_invalidation.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": status, "passed": sum(checks.values()), "total": len(checks)}))
    if status != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
