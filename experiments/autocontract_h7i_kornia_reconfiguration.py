"""Runtime H7I pilot: certified Kornia parameter replay and child composition."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import statistics
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7h_corpus" / "kornia_repo"
OUT = ROOT / "outputs"
sys.path.insert(0, str(REPO))

import torch  # noqa: E402
import kornia  # noqa: E402
import kornia.augmentation as K  # noqa: E402

import autocontract_h7i_lineage_certificate as cert  # noqa: E402


COMMIT = "d6bb4bf0d8a043c2bb8cef0c346a1b006d100930"
LEAF_POLICY: dict[str, cert.Decision] = {
    "kornia.augmentation._2d.geometric.horizontal_flip.RandomHorizontalFlip": "admit",
    "kornia.augmentation._2d.geometric.affine.RandomAffine": "admit",
    "kornia.augmentation._2d.intensity.color_jiggle.ColorJiggle": "admit",
}


def build_pipeline(*, affine_degrees: float = 15.0, reverse: bool = False):
    modules = [
        K.RandomHorizontalFlip(p=0.5),
        K.RandomAffine(affine_degrees, p=1.0),
        K.ColorJiggle(0.1, 0.1, 0.1, 0.1, p=1.0),
    ]
    if reverse:
        modules.reverse()
    return K.AugmentationSequential(*modules)


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


def result_row(name: str, passed: bool, detail: str) -> dict[str, object]:
    return {"test": name, "passed": passed, "detail": detail}


def timed(callable_obj, iterations: int) -> tuple[float, list[float]]:
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        callable_obj()
        samples.append((time.perf_counter_ns() - start) / 1e6)
    return statistics.median(samples), samples


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.manual_seed(20260729)

    pipeline = build_pipeline()
    equivalent = build_pipeline()
    input_value = torch.rand(4, 3, 64, 64)
    recorded_output = pipeline(input_value)
    params = copy.deepcopy(pipeline._params)
    certificate = cert.create_certificate(
        framework="kornia",
        framework_version=kornia.__version__,
        repository_commit=COMMIT,
        operator=pipeline,
        input_value=input_value,
        params=params,
        sample_id="epoch0/sample17",
    )
    common: dict[str, Any] = {
        "framework": "kornia",
        "framework_version": kornia.__version__,
        "repository_commit": COMMIT,
        "operator": equivalent,
        "input_value": input_value,
        "params": params,
        "sample_id": "epoch0/sample17",
    }

    validation = cert.validate_certificate(certificate, **common)
    composite = cert.compose_child_contracts(equivalent, params, LEAF_POLICY)
    replay_output = equivalent(input_value, params=params)
    tests: list[dict[str, object]] = [
        result_row("valid_lineage_certificate", validation.decision == "admit", ";".join(validation.reasons) or "none"),
        result_row("child_contract_composition", composite.decision == "admit", ";".join(composite.reasons) or "none"),
        result_row("reconfigured_output_trace", torch.equal(recorded_output, replay_output), f"record={cert.digest_payload(recorded_output)},replay={cert.digest_payload(replay_output)}"),
    ]

    rng_before = torch.get_rng_state().clone()
    _ = equivalent(input_value, params=params)
    rng_after = torch.get_rng_state().clone()
    tests.append(result_row("replay_rng_state_unchanged", torch.equal(rng_before, rng_after), cert.digest_payload(rng_before)))

    x1 = input_value.clone().requires_grad_(True)
    x2 = input_value.clone().requires_grad_(True)
    weight = torch.linspace(0.5, 1.5, replay_output.numel(), dtype=replay_output.dtype).reshape_as(replay_output)
    y1 = pipeline(x1, params=params)
    y2 = equivalent(x2, params=params)
    (y1 * weight).sum().backward(); (y2 * weight).sum().backward()
    grad_equal = torch.equal(x1.grad, x2.grad)
    tests.append(result_row("reconfigured_gradient_trace", grad_equal, f"left={cert.digest_payload(x1.grad)},right={cert.digest_payload(x2.grad)}"))

    attacks: list[tuple[str, dict[str, Any]]] = [
        ("reject_wrong_sample", {**common, "sample_id": "epoch0/sample18"}),
        ("reject_wrong_framework_version", {**common, "framework_version": "0.8.2"}),
        ("reject_wrong_repository_commit", {**common, "repository_commit": "0" * 40}),
        ("reject_changed_operator_config", {**common, "operator": build_pipeline(affine_degrees=30.0)}),
        ("reject_reordered_children", {**common, "operator": build_pipeline(reverse=True)}),
        ("reject_changed_input_schema", {**common, "input_value": torch.rand(4, 3, 32, 32)}),
    ]
    for name, kwargs in attacks:
        outcome = cert.validate_certificate(certificate, **kwargs)
        tests.append(result_row(name, outcome.decision == "reject", ";".join(outcome.reasons)))

    mutated = copy.deepcopy(params)
    mutated_ok = mutate_first_tensor(mutated)
    mutated_result = cert.validate_certificate(certificate, **{**common, "params": mutated})
    tests.append(result_row("reject_mutated_parameter_record", mutated_ok and mutated_result.decision == "reject", ";".join(mutated_result.reasons)))

    missing = copy.deepcopy(params[:-1])
    missing_validation = cert.validate_certificate(certificate, **{**common, "params": missing})
    missing_composite = cert.compose_child_contracts(equivalent, missing, LEAF_POLICY)
    tests.append(result_row("reject_missing_child_record", missing_validation.decision == "reject" and missing_composite.decision == "reject", ";".join((*missing_validation.reasons, *missing_composite.reasons))))

    reordered_params = copy.deepcopy(list(reversed(params)))
    reordered_composite = cert.compose_child_contracts(equivalent, reordered_params, LEAF_POLICY)
    tests.append(result_row("reject_reordered_child_record", reordered_composite.decision == "reject", ";".join(reordered_composite.reasons)))

    duplicate_params = copy.deepcopy([params[0], params[0], *params[2:]])
    duplicate_composite = cert.compose_child_contracts(equivalent, duplicate_params, LEAF_POLICY)
    tests.append(result_row("reject_duplicate_child_binding", duplicate_composite.decision == "reject", ";".join(duplicate_composite.reasons)))

    tampered = replace(certificate, sample_id="epoch0/sample18")
    tampered_result = cert.validate_certificate(tampered, **common)
    tests.append(result_row("reject_tampered_certificate", tampered_result.decision == "reject", ";".join(tampered_result.reasons)))

    unsupported = K.AugmentationSequential(torch.nn.Identity(), K.RandomHorizontalFlip(p=1.0))
    unsupported_params = unsupported.forward_parameters(input_value.shape)
    unsupported_composite = cert.compose_child_contracts(unsupported, unsupported_params, LEAF_POLICY)
    tests.append(result_row("reject_unsupported_child_effect", unsupported_composite.decision == "reject", ";".join(unsupported_composite.reasons)))

    for _ in range(5):
        pipeline(input_value)
        equivalent(input_value, params=params)
        cert.validate_certificate(certificate, **common)
    with torch.no_grad():
        sample_ms, sample_times = timed(lambda: pipeline(input_value), args.iterations)
        replay_ms, replay_times = timed(lambda: equivalent(input_value, params=params), args.iterations)
        validate_ms, validate_times = timed(lambda: cert.validate_certificate(certificate, **common), args.iterations)
    performance = [
        {"operation": "sample_apply", "iterations": args.iterations, "median_ms": sample_ms, "mean_ms": statistics.mean(sample_times)},
        {"operation": "replay_apply", "iterations": args.iterations, "median_ms": replay_ms, "mean_ms": statistics.mean(replay_times)},
        {"operation": "certificate_validate", "iterations": args.iterations, "median_ms": validate_ms, "mean_ms": statistics.mean(validate_times)},
    ]

    write_csv(OUT / "autocontract_h7i_runtime_tests.csv", tests)
    write_csv(OUT / "autocontract_h7i_performance.csv", performance)
    (OUT / "autocontract_h7i_certificate.json").write_text(json.dumps(asdict(certificate), indent=2), encoding="utf-8")
    passed = sum(row["passed"] is True for row in tests)
    speedup = sample_ms / replay_ms
    validation_share = validate_ms / replay_ms
    report = "\n".join(
        [
            "# AutoContract H7I certified Kornia reconfiguration pilot",
            "",
            f"Runtime: Python {sys.version.split()[0]}, Torch {torch.__version__}, Kornia {kornia.__version__}, device=CPU.",
            f"Correctness/adversarial tests: {passed}/{len(tests)}.",
            f"Median sample+apply: {sample_ms:.3f} ms; replay+apply: {replay_ms:.3f} ms; speedup: {speedup:.3f}x.",
            f"Median certificate validation: {validate_ms:.3f} ms ({validation_share:.1%} of replay time).",
            "",
            "| Test | Pass | Detail |",
            "|---|---|---|",
            *[f"| {row['test']} | {row['passed']} | {row['detail']} |" for row in tests],
            "",
            "| Operation | Median ms | Mean ms |",
            "|---|---:|---:|",
            *[f"| {row['operation']} | {row['median_ms']:.3f} | {row['mean_ms']:.3f} |" for row in performance],
            "",
            "The certificate is an integrity/lineage mechanism, not a malicious-party signature. "
            "The child composition result is scoped to the three leaf types explicitly admitted by the frozen H7H calibration policy.",
            "",
        ]
    )
    (OUT / "autocontract_h7i_kornia_reconfiguration.md").write_text(report, encoding="utf-8")
    print(report)
    if passed != len(tests):
        raise RuntimeError("H7I runtime pilot failed")


if __name__ == "__main__":
    main()
