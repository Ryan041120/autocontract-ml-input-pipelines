"""Public synthetic threat fixtures for H8C-R2.

The parameter values and family membership are fixed in the public protocol.
Oracle safety labels are intentionally not stored in this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import torch
from torch import Tensor


GLOBAL_COUNTS: Dict[str, int] = {}


def reset_global_counts() -> None:
    GLOBAL_COUNTS.clear()


class SafePure:
    def __call__(self, value: int, context: dict) -> int:
        del context
        return value * 2


class SafeModePure:
    def __call__(self, value: int, context: dict) -> int:
        return value * (2 if context["training"] else 2)


class SafeKeyedDeterministic:
    def __call__(self, value: int, context: dict) -> int:
        key = (value * 1103515245 + context["worker_id"] * 12345) & 0x7FFFFFFF
        return value + key % 7


class ExternalFile:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __call__(self, value: int, context: dict) -> int:
        del context
        gain = int(self.path.read_text(encoding="utf-8").strip())
        return value * gain


class RareInputRng:
    def __init__(self, threshold: int) -> None:
        self.threshold = threshold

    def __call__(self, value: int, context: dict) -> int:
        del context
        if value >= self.threshold:
            torch.rand(())
        return value


class PeriodicGlobalState:
    def __init__(self, key: str, period: int) -> None:
        self.key = key
        self.period = period

    def __call__(self, value: int, context: dict) -> int:
        del context
        GLOBAL_COUNTS[self.key] = GLOBAL_COUNTS.get(self.key, 0) + 1
        if GLOBAL_COUNTS[self.key] % self.period == 0:
            torch.rand(())
        return value


class WorkerModeRng:
    def __init__(self, trigger_worker: int) -> None:
        self.trigger_worker = trigger_worker

    def __call__(self, value: int, context: dict) -> int:
        if context["training"] and context["worker_id"] >= self.trigger_worker:
            torch.rand(())
        return value


class GradientDetach:
    def __call__(self, value: Tensor, context: dict) -> Tensor:
        del context
        return value.detach() * 2
