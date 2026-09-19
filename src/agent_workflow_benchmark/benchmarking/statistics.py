from __future__ import annotations

import hashlib
import random
from statistics import mean
from typing import Iterable


def _seed(label: str) -> int:
    return int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:16], 16)


def paired_bootstrap_interval(
    values: Iterable[float], *, label: str, confidence: float = 0.95, samples: int = 10000
) -> dict[str, float | int | None]:
    observed = [float(item) for item in values]
    if not observed:
        return {"n": 0, "mean": None, "lower": None, "upper": None, "confidence": confidence}
    if len(observed) == 1:
        value = observed[0]
        return {"n": 1, "mean": value, "lower": value, "upper": value, "confidence": confidence}
    generator = random.Random(_seed(label))
    estimates = sorted(
        mean(generator.choice(observed) for _ in observed) for _ in range(samples)
    )
    alpha = (1.0 - confidence) / 2.0
    lower_index = max(0, min(samples - 1, int(alpha * samples)))
    upper_index = max(0, min(samples - 1, int((1.0 - alpha) * samples) - 1))
    return {
        "n": len(observed),
        "mean": round(mean(observed), 6),
        "lower": round(estimates[lower_index], 6),
        "upper": round(estimates[upper_index], 6),
        "confidence": confidence,
    }


def paired_binary_deltas(control: Iterable[bool], workflow: Iterable[bool]) -> list[float]:
    return [float(int(right) - int(left)) for left, right in zip(control, workflow, strict=True)]
