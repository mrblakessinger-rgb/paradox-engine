"""
Ingest node — map real-world health signals → kernel interference I.

Buyer surface: "your metrics in." No DNA, no hive, no Paradox.
"""

from __future__ import annotations

import numpy as np


def to_interference(
    *,
    success_rate: float | None = None,
    failure_rate: float | None = None,
    env_load: float = 1.0,
    thrash: float = 0.0,
    queue_pressure: float = 0.0,
    w_env: float = 0.50,
    w_fail: float = 1.55,
    w_thrash: float = 0.30,
    w_queue: float = 0.25,
    bias: float = 0.20,
    lo: float = 0.4,
    hi: float = 3.0,
) -> float:
    """
    Convert observed system health into kernel interference I.

    Parameters
    ----------
    success_rate : 0..1 rolling success (if given, failure = 1 - success)
    failure_rate : 0..1 alternative to success_rate
    env_load : external storm / demand score (same units as env I in proofs, ~0.4..3)
    thrash : retry / stampede intensity (0 = calm, 1+ = bad)
    queue_pressure : backlog stress 0..1+ (optional)

    Returns
    -------
    float I in [lo, hi]
    """
    if success_rate is not None:
        fail = 1.0 - float(np.clip(success_rate, 0.0, 1.0))
    elif failure_rate is not None:
        fail = float(np.clip(failure_rate, 0.0, 1.0))
    else:
        fail = 0.35  # neutral prior

    env = float(max(0.0, env_load))
    thr = float(max(0.0, thrash))
    qp = float(max(0.0, queue_pressure))

    raw = w_env * env + w_fail * fail + w_thrash * thr + w_queue * qp + bias
    return float(np.clip(raw, lo, hi))


def from_fleet(success_rate: float, env_I: float) -> float:
    """Proof-A shaped convenience (matches portfolio demos)."""
    return to_interference(success_rate=success_rate, env_load=env_I, w_env=0.50, w_fail=1.6, bias=0.25)


def from_queue(success_rate: float, env_I: float, queue_depth: float = 0.0, capacity: float = 80.0) -> float:
    """Proof-B shaped: optional backlog pressure."""
    pressure = float(queue_depth) / max(1.0, capacity)
    return to_interference(
        success_rate=success_rate,
        env_load=env_I,
        queue_pressure=pressure,
        w_env=0.50,
        w_fail=1.7,
        w_queue=0.35,
        bias=0.20,
    )


def from_api(goodput: float, env_I: float, retries: float = 0.0, goodput_ref: float = 0.55) -> float:
    """Proof-C shaped: goodput + retry thrash."""
    pain = 1.0 - float(np.clip(goodput / max(1e-6, goodput_ref), 0.0, 1.0))
    return to_interference(
        failure_rate=pain,
        env_load=env_I,
        thrash=retries,
        w_env=0.45,
        w_fail=1.5,
        w_thrash=0.25,
        bias=0.20,
    )
