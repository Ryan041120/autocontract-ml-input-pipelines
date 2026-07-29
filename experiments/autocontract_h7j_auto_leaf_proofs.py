"""Generate Kornia replay leaf proofs from the frozen H7H EffectV7 analyzer."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7h_corpus" / "kornia_repo"
OUT = ROOT / "outputs"
sys.path[:0] = [str(ROOT / "experiments"), str(REPO)]

import kornia.augmentation as K  # noqa: E402

import autocontract_h7h_effect_v7 as v7  # noqa: E402
import autocontract_h7h_kornia as h7h  # noqa: E402
import autocontract_h7i_lineage_certificate as lineage  # noqa: E402


@dataclass(frozen=True)
class LeafReplayProof:
    public_symbol: str
    module_path: str
    configuration: str
    phase: str
    decision: str
    reasons: tuple[str, ...]
    reachable_methods: tuple[str, ...]
    binding_sha256: str
    source_sha256: str
    repository_commit: str
    effect_v7_sha256: str
    adapter_sha256: str
    proof_sha256: str


def type_name(value: object) -> str:
    return f"{value.__class__.__module__}.{value.__class__.__qualname__}"


def is_semantic_container(module: object) -> bool:
    return "Sequential" in module.__class__.__name__ and hasattr(module, "get_submodule")


def leaf_modules(module: object, prefix: str = ""):
    for name, child in module.named_children():  # type: ignore[attr-defined]
        path = f"{prefix}.{name}" if prefix else name
        if is_semantic_container(child):
            yield from leaf_modules(child, path)
        else:
            yield path, child


def _proof_digest(proof: LeafReplayProof) -> str:
    return lineage.digest_payload(asdict(replace(proof, proof_sha256="")))


def generate_leaf_proofs(operator: object) -> tuple[LeafReplayProof, ...]:
    freeze = h7h.verify_freeze()
    classes = h7h.package_classes()
    proofs: list[LeafReplayProof] = []
    seen: set[tuple[str, str]] = set()
    for path, module in leaf_modules(operator):
        symbol = type_name(module)
        key = (path, symbol)
        if key in seen:
            continue
        seen.add(key)
        binding = h7h.public_binding(symbol)
        if binding["status"] != "resolved":
            decision, reasons, methods = "reject", ("unresolved_symbol_binding",), ()
        else:
            analysis = h7h.analyze(binding, classes, "kornia.params_provided")
            validation_reasons = v7.validator_v7(analysis)
            decision = "reject" if validation_reasons else "admit"
            reasons = validation_reasons
            methods = analysis.effect.reachable.methods
        provisional = LeafReplayProof(
            public_symbol=symbol,
            module_path=path,
            configuration="kornia.params_provided",
            phase="replay_apply",
            decision=decision,
            reasons=tuple(reasons),
            reachable_methods=tuple(methods),
            binding_sha256=str(binding.get("binding_sha256") or ""),
            source_sha256=str(binding.get("source_sha256") or ""),
            repository_commit=str(freeze["repository_commit"]),
            effect_v7_sha256=str(freeze["effect_v7_sha256"]),
            adapter_sha256=str(freeze["adapter_sha256"]),
            proof_sha256="",
        )
        proofs.append(replace(provisional, proof_sha256=_proof_digest(provisional)))
    return tuple(proofs)


def verify_leaf_proofs(proofs: tuple[LeafReplayProof, ...]) -> bool:
    return bool(proofs) and all(
        proof.proof_sha256 == _proof_digest(proof)
        and proof.repository_commit == h7h.repository_revision()
        and proof.configuration == "kornia.params_provided"
        and proof.phase == "replay_apply"
        for proof in proofs
    )


def policy_from_proofs(proofs: tuple[LeafReplayProof, ...]) -> dict[str, lineage.Decision]:
    if not verify_leaf_proofs(proofs):
        raise ValueError("invalid leaf proof set")
    policy: dict[str, lineage.Decision] = {}
    for proof in proofs:
        decision: lineage.Decision = "admit" if proof.decision == "admit" else "reject"
        previous = policy.get(proof.public_symbol)
        if previous is not None and previous != decision:
            policy[proof.public_symbol] = "reject"
        else:
            policy[proof.public_symbol] = decision
    return policy


def build_pilot_pipeline():
    return K.AugmentationSequential(
        K.RandomHorizontalFlip(p=0.5),
        K.RandomAffine(15.0, p=1.0),
        K.ColorJiggle(0.1, 0.1, 0.1, 0.1, p=1.0),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT / "autocontract_h7j_leaf_proofs.json")
    args = parser.parse_args()
    proofs = generate_leaf_proofs(build_pilot_pipeline())
    policy = policy_from_proofs(proofs)
    payload = {
        "proofs": [asdict(proof) for proof in proofs],
        "policy": policy,
        "proofs_valid": verify_leaf_proofs(proofs),
        "all_admitted": all(value == "admit" for value in policy.values()),
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if not payload["proofs_valid"] or not payload["all_admitted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
