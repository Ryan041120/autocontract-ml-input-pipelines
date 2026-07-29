"""Lightweight CPU/memory stress process used by local benchmarks."""

from __future__ import annotations

import argparse

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    rng = np.random.default_rng(args.seed)
    data = rng.random(2_000_000, dtype=np.float32)
    iteration = 0
    while True:
        np.multiply(data, np.float32(1.000001), out=data)
        np.add(data, np.float32(iteration % 7) * np.float32(1e-7), out=data)
        _ = float(data[::64].sum())
        iteration += 1


if __name__ == "__main__":
    main()
