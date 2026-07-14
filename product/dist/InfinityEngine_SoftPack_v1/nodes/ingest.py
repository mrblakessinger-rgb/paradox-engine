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
    empty_tool_rate: float = 0.0,
    budget_remaining: float | None = None,
    latency_p95: float | None = None,
    latency_ref: float = 1.0,
    w_env: float = 0.50,
    w_fail: float = 1.55,
    w_thrash: float = 0.30,
    w_queue: float = 0.25,
    w_empty: float = 0.40,
    w_budget: float = 0.35,
    w_latency: float = 0.20,
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
    env_load : external storm / demand score (same units as env I in proofs, ~0.4..3+)
    thrash : retry / stampede intensity (0 = calm, 1+ = bad)
    queue_pressure : backlog stress 0..1+ (optional)
    empty_tool_rate : fraction of tool calls empty/error (fail-closed signal)
    budget_remaining : 0..1 shared API/token budget left (None = ignore)
    latency_p95 : optional tail latency; compared to latency_ref
    hi : default 3.0 for kernel contract; raise only if your loop supports it

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
    empty = float(np.clip(empty_tool_rate, 0.0, 1.0))

    raw = w_env * env + w_fail * fail + w_thrash * thr + w_queue * qp + bias
    raw += w_empty * empty

    if budget_remaining is not None:
        br = float(np.clip(budget_remaining, 0.0, 1.0))
        # empty budget → higher I (starve / thrash risk)
        raw += w_budget * (1.0 - br)

    if latency_p95 is not None and latency_ref > 0:
        lat_pain = float(np.clip((float(latency_p95) / float(latency_ref)) - 1.0, 0.0, 3.0))
        raw += w_latency * lat_pain

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


def from_api(
    goodput: float,
    env_I: float,
    retries: float = 0.0,
    goodput_ref: float = 0.55,
    budget_remaining: float | None = None,
) -> float:
    """Proof-C shaped: goodput + retry thrash (+ optional budget)."""
    pain = 1.0 - float(np.clip(goodput / max(1e-6, goodput_ref), 0.0, 1.0))
    return to_interference(
        failure_rate=pain,
        env_load=env_I,
        thrash=retries,
        budget_remaining=budget_remaining,
        w_env=0.45,
        w_fail=1.5,
        w_thrash=0.25,
        bias=0.20,
    )
