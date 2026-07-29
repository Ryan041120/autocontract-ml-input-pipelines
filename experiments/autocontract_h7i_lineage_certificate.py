"""Replay-record lineage certificates and child-contract composition.

The certificate protects against accidental/stale record reuse.  It is an
integrity digest, not an authentication signature against a malicious party.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal, Mapping


Decision = Literal["admit", "reject"]
SCHEMA_VERSION = "autocontract.replay-lineage.v1"


def _type_name(value: object) -> str:
    cls = value.__class__
    return f"{cls.__module__}.{cls.__qualname__}"


def _tensor_record(value: object) -> dict[str, object] | None:
    """Return a portable digest record for torch-like tensors without importing torch."""
    if not all(hasattr(value, name) for name in ("detach", "cpu", "contiguous", "numpy", "shape", "dtype")):
        return None
    tensor = value.detach().cpu().contiguous()  # type: ignore[attr-defined]
    raw = tensor.numpy().tobytes()  # type: ignore[attr-defined]
    return {
        "kind": "tensor",
        "type": _type_name(value),
        "shape": list(value.shape),  # type: ignore[attr-defined]
        "dtype": str(value.dtype),  # type: ignore[attr-defined]
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }


def canonical_record(value: object) -> object:
    tensor = _tensor_record(value)
    if tensor is not None:
        return tensor
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"kind": "bytes", "sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if isinstance(value, Mapping):
        return {str(key): canonical_record(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if hasattr(value, "_asdict"):
        return {"kind": "namedtuple", "type": _type_name(value), "fields": canonical_record(value._asdict())}  # type: ignore[attr-defined]
    if isinstance(value, (list, tuple)):
        return {"kind": type(value).__name__, "items": [canonical_record(item) for item in value]}
    return {"kind": "object", "type": _type_name(value), "repr": repr(value)}


def digest_payload(value: object) -> str:
    rendered = json.dumps(canonical_record(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def input_schema(value: object) -> dict[str, object]:
    shape = list(getattr(value, "shape", ()))
    return {
        "type": _type_name(value),
        "shape": shape,
        "rank": len(shape),
        "dtype": str(getattr(value, "dtype", "unknown")),
        "layout": str(getattr(value, "layout", "unknown")),
    }


def operator_graph(module: object) -> list[dict[str, object]]:
    if not hasattr(module, "named_modules"):
        return [{"path": "", "type": _type_name(module), "semantic_repr": repr(module)}]
    records: list[dict[str, object]] = []
    for path, child in module.named_modules():  # type: ignore[attr-defined]
        records.append(
            {
                "path": str(path),
                "type": _type_name(child),
                "semantic_repr": " ".join(repr(child).split()),
                "direct_children": [name for name, _ in child.named_children()],
            }
        )
    return records


def child_sequence(params: object) -> tuple[str, ...]:
    if not isinstance(params, (list, tuple)):
        return ()
    result: list[str] = []
    for item in params:
        name = getattr(item, "name", None)
        if not isinstance(name, str):
            raise ValueError("container parameter item has no string name")
        result.append(name)
    return tuple(result)


@dataclass(frozen=True)
class ReplayLineageCertificate:
    schema_version: str
    framework: str
    framework_version: str
    repository_commit: str
    record_phase: str
    replay_phase: str
    sample_id: str
    operator_graph_sha256: str
    input_schema_sha256: str
    params_sha256: str
    child_sequence: tuple[str, ...]
    certificate_sha256: str


@dataclass(frozen=True)
class ValidationResult:
    decision: Decision
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ChildContract:
    path: str
    operator_type: str
    params_sha256: str
    decision: Decision
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CompositeContract:
    decision: Decision
    reasons: tuple[str, ...]
    child_contracts: tuple[ChildContract, ...]


def _certificate_digest(certificate: ReplayLineageCertificate) -> str:
    payload = asdict(replace(certificate, certificate_sha256=""))
    return digest_payload(payload)


def create_certificate(
    *,
    framework: str,
    framework_version: str,
    repository_commit: str,
    operator: object,
    input_value: object,
    params: object,
    sample_id: str,
) -> ReplayLineageCertificate:
    provisional = ReplayLineageCertificate(
        schema_version=SCHEMA_VERSION,
        framework=framework,
        framework_version=framework_version,
        repository_commit=repository_commit,
        record_phase="sample_apply",
        replay_phase="replay_apply",
        sample_id=sample_id,
        operator_graph_sha256=digest_payload(operator_graph(operator)),
        input_schema_sha256=digest_payload(input_schema(input_value)),
        params_sha256=digest_payload(params),
        child_sequence=child_sequence(params),
        certificate_sha256="",
    )
    return replace(provisional, certificate_sha256=_certificate_digest(provisional))


def validate_certificate(
    certificate: ReplayLineageCertificate,
    *,
    framework: str,
    framework_version: str,
    repository_commit: str,
    operator: object,
    input_value: object,
    params: object,
    sample_id: str,
) -> ValidationResult:
    reasons: list[str] = []
    if certificate.schema_version != SCHEMA_VERSION:
        reasons.append("certificate_schema_mismatch")
    if certificate.certificate_sha256 != _certificate_digest(certificate):
        reasons.append("certificate_integrity_mismatch")
    if certificate.framework != framework:
        reasons.append("framework_mismatch")
    if certificate.framework_version != framework_version:
        reasons.append("framework_version_mismatch")
    if certificate.repository_commit != repository_commit:
        reasons.append("repository_commit_mismatch")
    if certificate.record_phase != "sample_apply" or certificate.replay_phase != "replay_apply":
        reasons.append("phase_mismatch")
    if certificate.sample_id != sample_id:
        reasons.append("sample_lineage_mismatch")
    if certificate.operator_graph_sha256 != digest_payload(operator_graph(operator)):
        reasons.append("operator_graph_mismatch")
    if certificate.input_schema_sha256 != digest_payload(input_schema(input_value)):
        reasons.append("input_schema_mismatch")
    if certificate.params_sha256 != digest_payload(params):
        reasons.append("parameter_record_mismatch")
    try:
        sequence = child_sequence(params)
    except ValueError:
        sequence = ()
        reasons.append("invalid_child_sequence")
    if certificate.child_sequence != sequence:
        reasons.append("child_sequence_mismatch")
    unique = tuple(dict.fromkeys(sequence))
    if len(unique) != len(sequence):
        reasons.append("duplicate_child_binding")
    return ValidationResult("reject" if reasons else "admit", tuple(dict.fromkeys(reasons)))


def compose_child_contracts(
    container: object,
    params: object,
    leaf_policy: Mapping[str, Decision],
    path: str = "",
) -> CompositeContract:
    """Bind ParamItem records to child modules and recursively compose contracts."""
    if not isinstance(params, (list, tuple)):
        return CompositeContract("reject", ("container_params_not_sequence",), ())
    names: list[str] = []
    contracts: list[ChildContract] = []
    reasons: list[str] = []
    direct_names = [name for name, _ in container.named_children()] if hasattr(container, "named_children") else []
    for item in params:
        name = getattr(item, "name", None)
        data = getattr(item, "data", None)
        if not isinstance(name, str):
            reasons.append("invalid_child_binding")
            continue
        names.append(name)
        child_path = f"{path}.{name}" if path else name
        try:
            child = container.get_submodule(name)  # type: ignore[attr-defined]
        except (AttributeError, KeyError, IndexError):
            reasons.append("unknown_child_binding:" + child_path)
            continue
        child_type = _type_name(child)
        if isinstance(data, (list, tuple)) and hasattr(child, "get_submodule"):
            nested = compose_child_contracts(child, data, leaf_policy, child_path)
            contracts.extend(nested.child_contracts)
            if nested.decision == "reject":
                reasons.extend(nested.reasons)
            continue
        decision = leaf_policy.get(child_type, "reject")
        child_reasons = () if decision == "admit" else ("unsupported_child_effect",)
        contracts.append(ChildContract(child_path, child_type, digest_payload(data), decision, child_reasons))
        reasons.extend(f"{reason}:{child_path}" for reason in child_reasons)
    if len(set(names)) != len(names):
        reasons.append("duplicate_child_binding")
    random_apply = bool(getattr(container, "random_apply", False))
    if not random_apply and names != direct_names:
        reasons.append("incomplete_or_reordered_child_sequence")
    return CompositeContract("reject" if reasons else "admit", tuple(dict.fromkeys(reasons)), tuple(contracts))


class _FakeTensor:
    def __init__(self, data: bytes, shape: tuple[int, ...], dtype: str = "float32") -> None:
        self._data = data
        self.shape = shape
        self.dtype = dtype
        self.layout = "strided"

    def detach(self) -> "_FakeTensor": return self
    def cpu(self) -> "_FakeTensor": return self
    def contiguous(self) -> "_FakeTensor": return self
    def numpy(self) -> "_FakeArray": return _FakeArray(self._data)


class _FakeArray:
    def __init__(self, data: bytes) -> None: self.data = data
    def tobytes(self) -> bytes: return self.data


class _FakeModule:
    def __init__(self, name: str, config: str = "x") -> None:
        self.name, self.config = name, config

    def __repr__(self) -> str: return f"FakeModule(name={self.name},config={self.config})"
    def named_modules(self): yield "", self
    def named_children(self): return iter(())


def self_test() -> dict[str, bool]:
    operator = _FakeModule("op")
    input_value = _FakeTensor(b"input", (1, 3, 4, 4))
    params = {"gain": _FakeTensor(b"params", (1,))}
    certificate = create_certificate(framework="fake", framework_version="1", repository_commit="abc", operator=operator, input_value=input_value, params=params, sample_id="s0")
    common = dict(framework="fake", framework_version="1", repository_commit="abc", operator=operator, input_value=input_value, params=params, sample_id="s0")
    tests = {
        "valid": validate_certificate(certificate, **common).decision == "admit",
        "wrong_sample": validate_certificate(certificate, **{**common, "sample_id": "s1"}).decision == "reject",
        "wrong_shape": validate_certificate(certificate, **{**common, "input_value": _FakeTensor(b"input", (1, 3, 8, 8))}).decision == "reject",
        "mutated_params": validate_certificate(certificate, **{**common, "params": {"gain": _FakeTensor(b"changed", (1,))}}).decision == "reject",
        "changed_operator": validate_certificate(certificate, **{**common, "operator": _FakeModule("op", "changed")}).decision == "reject",
        "wrong_version": validate_certificate(certificate, **{**common, "framework_version": "2"}).decision == "reject",
        "tampered_certificate": validate_certificate(replace(certificate, sample_id="s1"), **common).decision == "reject",
    }
    return tests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.self_test:
        parser.error("--self-test is required")
    tests = self_test()
    payload = {"tests": tests, "passed": sum(tests.values()), "total": len(tests), "all_passed": all(tests.values())}
    rendered = json.dumps(payload, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not payload["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
