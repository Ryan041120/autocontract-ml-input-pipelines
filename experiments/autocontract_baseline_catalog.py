"""Public source/context bindings for development pair comparisons."""

from __future__ import annotations

import hashlib
import inspect
import json
import platform
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path

from autocontract_comparison_request import Candidate


def digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class OperatorSource:
    operator_id: str
    module: str
    symbol: str
    source: str
    module_sha256: str
    module_source: str


@dataclass(frozen=True)
class ProbeContext:
    epoch: int
    gain: int


@dataclass(frozen=True)
class PairCase:
    pipeline_id: str
    left: OperatorSource
    right: OperatorSource
    contexts: tuple[ProbeContext, ...] = (
        ProbeContext(0, 1), ProbeContext(1, 1), ProbeContext(0, 2),
    )
    input_domain: str = "exact_builtin_python_int"
    rng_scope: str = "python_random_only"

    def binding(self) -> dict:
        if (not self.pipeline_id or self.left.operator_id == self.right.operator_id or not self.contexts
                or any(type(context.epoch) is not int or type(context.gain) is not int for context in self.contexts)):
            raise ValueError("distinct occurrences and nonempty public contexts required")
        return {
            "case": asdict(self),
            "baseline_order": [self.left.operator_id, self.right.operator_id],
            "position": 0,
            "scope": "pair_only_one_invocation_or_declared_repeated_sequence",
            "observation": "exact_output_definedness_exception_python_rng_object_state",
            "runtime": {"implementation": platform.python_implementation(),
                        "python": platform.python_version()},
        }

    def candidate(self) -> Candidate:
        return Candidate(self.pipeline_id + ":0", 0, digest(self.binding()))


def source_for(operator_id: str, operator_type: type) -> OperatorSource:
    """Read an already imported, trusted development class; never instantiate it.

    Independent selectors can instead construct OperatorSource from source data.
    This helper is not a general portable closure/source verifier.
    """
    if "." in operator_type.__qualname__:
        raise ValueError("development dynamic loader requires top-level classes")
    source_path = inspect.getsourcefile(operator_type)
    if source_path is None:
        raise ValueError("source unavailable")
    module_bytes = Path(source_path).read_bytes()
    return OperatorSource(
        operator_id, operator_type.__module__, operator_type.__name__,
        textwrap.dedent(inspect.getsource(operator_type)),
        hashlib.sha256(module_bytes).hexdigest(),
        module_bytes.decode("utf-8"),
    )
