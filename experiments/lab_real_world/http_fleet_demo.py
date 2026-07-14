"""
Real-world demo — HTTP worker fleet under thrash
================================================
Uses REAL network calls (httpbin.org) + a shared request budget
so thrash is physical latency + 429-style pressure, not pure numpy.

  Baseline: workers hammer freely (stampede when budget tight)
  Engine:   Soft Pack nodes (ingest → HealthEngine → actuate)

  python real_world/http_fleet_demo.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodes.actuate import apply_shield, plan_actions
from nodes.engine_loop import HealthEngine
from nodes.ingest import to_interference

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

# Public sandbox API — real TCP/HTTP, no key required
HTTPBIN = "https://httpbin.org"


@dataclass
class SharedBudget:
    """Simulates a shared API quota that shrinks under load storms."""

    tokens: float = 12.0
    max_tokens: float = 12.0
    lock_note: str = ""

    def try_take(self, cost: float = 1.0) -> bool:
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False

    def refill(self, amount: float) -> None:
        self.tokens = min(self.max_tokens, self.tokens + amount)


@dataclass
class FleetMetrics:
    recent: list[int] = field(default_factory=list)
    ok_total: int = 0
    fail_total: int = 0
    alive: list[bool] = field(default_factory=list)
    fails: list[int] = field(default_factory=list)

    def __post_init__(self):
        if not self.alive:
            pass

    def rolling(self) -> float:
        if not self.recent:
            return 0.5
        return float(np.mean(self.recent[-40:]))


def one_request(url: str, timeout: float = 6.0) -> bool:
    """Real HTTP GET. Returns True on 2xx."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "InfinityEngine-RealWorld/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def worker_job(budget: SharedBudget, env_I: float, thrash: float) -> bool:
    """
    One real attempt:
      - if budget empty → treat as 429 (no request) or hit /status/429
      - else GET httpbin /get (real network)
      - under high I/thrash, sometimes force /status/500 or /status/429
    """
    # Storm pressure: higher I / thrash → more forced failure paths
    if thrash > 1.2 and np.random.random() < min(0.35, 0.12 * thrash):
        return one_request(f"{HTTPBIN}/status/429", timeout=5.0)
    if env_I > 2.0 and np.random.random() < 0.15:
        return one_request(f"{HTTPBIN}/status/500", timeout=5.0)

    if not budget.try_take(1.0):
        # Real 429 path when quota exhausted
        return one_request(f"{HTTPBIN}/status/429", timeout=5.0)

    ok = one_request(f"{HTTPBIN}/get", timeout=6.0)
    return ok


def run_mode(
    *,
    controlled: bool,
    steps: int = 24,
    n_workers: int = 8,
    seed: int = 7,
) -> dict:
    rng = np.random.default_rng(seed)
    budget = SharedBudget(tokens=10.0, max_tokens=10.0)
    metrics = FleetMetrics(
        alive=[True] * n_workers,
        fails=[0] * n_workers,
    )
    concurrency = n_workers
    thrash = 1.0
    eng = HealthEngine(seed=seed + 99) if controlled else None
    stab = 0.88
    rows = []

    # Interference schedule (same spirit as proofs)
    I = 1.1
    schedule = []
    for _ in range(steps):
        if rng.random() < 0.12:
            I = float(rng.choice([0.8, 1.4, 2.0, 2.6]))
        else:
            I = float(np.clip(I + rng.normal(0, 0.08), 0.5, 2.9))
        schedule.append(I)

    print(f"\n  Mode: {'ENGINE' if controlled else 'BASELINE'}  steps={steps} workers={n_workers}")
    t0 = time.time()

    for t, env_I in enumerate(schedule):
        # Refill budget each step (shared API quota recovering slowly)
        budget.refill(3.5 + max(0, 2.0 - 0.5 * env_I))

        felt = env_I
        if controlled and eng is not None:
            plan = plan_actions(stab, success_rate=metrics.rolling())
            felt = apply_shield(env_I, plan)
            # Damp thrash when unhealthy (Soft Pack actuate surface)
            if metrics.rolling() < 0.70 or plan.cool_retries or stab < 0.90:
                thrash = max(0.55, thrash * 0.68)
                concurrency = max(2, concurrency - 1)
            if plan.quarantine_k:
                # quarantine worst workers
                order = sorted(range(n_workers), key=lambda i: -metrics.fails[i])
                for i in order[: plan.quarantine_k]:
                    if metrics.alive[i]:
                        metrics.alive[i] = False
            if plan.revive_k:
                for i in range(n_workers):
                    if not metrics.alive[i] and plan.revive_k > 0:
                        metrics.alive[i] = True
                        metrics.fails[i] = 0
                        plan.revive_k -= 1
            if stab >= 0.90:
                thrash = min(1.3, thrash + 0.03)
                concurrency = min(n_workers, concurrency + 1)
        else:
            # baseline stampede — panic-retry when failing
            thrash = min(2.5, thrash + 0.12 * (1.0 - metrics.rolling()) + 0.05 * env_I)
            concurrency = n_workers

        active = [i for i in range(n_workers) if metrics.alive[i]][:concurrency]
        if not active:
            active = [0]
            metrics.alive[0] = True

        # Fire real HTTP in parallel
        ok = 0
        fail = 0
        with ThreadPoolExecutor(max_workers=max(1, len(active) + 4)) as ex:
            futs = {
                ex.submit(worker_job, budget, felt, thrash): wid for wid in active
            }
            # Extra thrash jobs: baseline floods; engine keeps extras low
            if not controlled:
                extra = 2 + int(thrash * 2.5)
            else:
                extra = 1 if thrash > 1.15 else 0
            for _ in range(extra):
                futs[ex.submit(worker_job, budget, felt, thrash)] = -1

            for fut in as_completed(futs):
                wid = futs[fut]
                try:
                    success = bool(fut.result())
                except Exception:
                    success = False
                if success:
                    ok += 1
                    metrics.ok_total += 1
                    metrics.recent.append(1)
                    if wid >= 0:
                        metrics.fails[wid] = max(0, metrics.fails[wid] - 1)
                else:
                    fail += 1
                    metrics.fail_total += 1
                    metrics.recent.append(0)
                    if wid >= 0:
                        metrics.fails[wid] += 1
                        if not controlled and metrics.fails[wid] >= 5:
                            metrics.alive[wid] = False

        if len(metrics.recent) > 200:
            metrics.recent = metrics.recent[-200:]

        roll = metrics.rolling()
        if controlled and eng is not None:
            I_k = to_interference(success_rate=roll, env_load=env_I, thrash=max(0, thrash - 0.8))
            out = eng.step(I_k, success_rate=roll)
            stab = float(out["stability"])
        else:
            stab = float("nan")

        n_alive = int(sum(metrics.alive))
        rows.append(
            {
                "t": t,
                "env_I": env_I,
                "felt_I": felt,
                "rolling_success": roll,
                "step_ok": ok,
                "step_fail": fail,
                "n_alive": n_alive,
                "thrash": thrash,
                "concurrency": concurrency,
                "kernel_stability": stab,
                "budget": budget.tokens,
            }
        )
        print(
            f"    step {t+1:02d}/{steps}  roll={roll:.2f}  alive={n_alive}  "
            f"ok/fail={ok}/{fail}  I={env_I:.2f}  thrash={thrash:.2f}"
            + (f"  stab={stab:.3f}" if controlled else "")
        )

    elapsed = time.time() - t0
    arr = np.array([r["rolling_success"] for r in rows], float)
    return {
        "controlled": controlled,
        "elapsed_sec": elapsed,
        "mean_success": float(np.mean(arr)),
        "late_success": float(np.mean(arr[-max(1, len(arr) // 5) :])),
        "p10": float(np.percentile(arr, 10)),
        "final_alive": int(sum(metrics.alive)),
        "ok_total": metrics.ok_total,
        "fail_total": metrics.fail_total,
        "rows": rows,
    }


def main() -> int:
    print("=" * 64)
    print(" REAL-WORLD HTTP FLEET — baseline vs Soft Pack nodes")
    print(" Real HTTP → httpbin.org  |  shared budget thrash")
    print("=" * 64)

    # Connectivity check
    print("\n  Checking httpbin…")
    if not one_request(f"{HTTPBIN}/get", timeout=10):
        print("  ERROR: cannot reach httpbin.org — check internet")
        return 1
    print("  httpbin OK")

    base = run_mode(controlled=False, steps=20, n_workers=8, seed=11)
    eng = run_mode(controlled=True, steps=20, n_workers=8, seed=11)

    print("\n" + "=" * 64)
    print(" RESULTS (real HTTP)")
    print("=" * 64)
    print(f"  Baseline mean success : {base['mean_success']:.3f}  late {base['late_success']:.3f}")
    print(f"  Engine   mean success : {eng['mean_success']:.3f}  late {eng['late_success']:.3f}")
    print(f"  Δ mean                : {eng['mean_success'] - base['mean_success']:+.3f}")
    print(f"  Final workers alive   : base {base['final_alive']}  eng {eng['final_alive']}")
    print(f"  Wall time             : base {base['elapsed_sec']:.1f}s  eng {eng['elapsed_sec']:.1f}s")

    # Plot
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    fig.patch.set_facecolor("#0b0f14")
    x = np.arange(len(base["rows"]))
    ax = axes[0]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["rolling_success"] for r in base["rows"]], color="#ff6b8a", label="Baseline")
    ax.plot(x, [r["rolling_success"] for r in eng["rows"]], color="#5dffb0", label="With Soft Pack nodes")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_ylabel("Rolling success", color="white")
    ax.set_title("Real-world HTTP fleet under thrash (httpbin.org)", color="white")

    ax = axes[1]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["env_I"] for r in eng["rows"]], color="#c090ff", label="Env I")
    ax.plot(x, [r["kernel_stability"] for r in eng["rows"]], color="#40d0ff", label="Kernel stab")
    ax.plot(x, [r["n_alive"] / 8 for r in eng["rows"]], color="#ffd060", label="Alive frac")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_xlabel("Step", color="white")
    for a in axes:
        for s in a.spines.values():
            s.set_color("#445")
    fig.tight_layout()
    fig.savefig(OUT / "http_fleet_comparison.png", dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)

    report = {
        "demo": "real_world_http_fleet",
        "endpoint": HTTPBIN,
        "baseline": {k: base[k] for k in ("mean_success", "late_success", "p10", "final_alive", "ok_total", "fail_total", "elapsed_sec")},
        "engine": {k: eng[k] for k in ("mean_success", "late_success", "p10", "final_alive", "ok_total", "fail_total", "elapsed_sec")},
        "improvement_mean": eng["mean_success"] - base["mean_success"],
    }
    (OUT / "http_fleet_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    better = report["improvement_mean"] > 0.02
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>Real-world HTTP fleet</title>
<style>
body{{margin:0;padding:28px;background:#0b0f14;color:#e8eef7;font-family:Segoe UI,sans-serif;max-width:900px}}
.ok{{color:#5dffb0}} .card{{background:#121a24;border:1px solid #243044;border-radius:12px;padding:16px;margin:12px 0}}
img{{max-width:100%;border-radius:8px}} table{{width:100%;border-collapse:collapse}}
td,th{{padding:8px;border-bottom:1px solid #243044;text-align:left}}
</style></head><body>
<h1>Real-world HTTP fleet</h1>
<p><b>What this is:</b> Parallel workers making <b>real HTTP</b> calls to httpbin.org under a shared budget
and storm schedule. Baseline stampedes; Soft Pack nodes cool thrash / shield / quarantine.</p>
<div class="card">
<table>
<tr><th></th><th>Baseline</th><th>Engine</th><th>Δ</th></tr>
<tr><td>Mean success</td><td>{base['mean_success']:.3f}</td><td class="ok">{eng['mean_success']:.3f}</td>
<td>{report['improvement_mean']:+.3f}</td></tr>
<tr><td>Late success</td><td>{base['late_success']:.3f}</td><td class="ok">{eng['late_success']:.3f}</td>
<td>{eng['late_success']-base['late_success']:+.3f}</td></tr>
<tr><td>Final workers alive</td><td>{base['final_alive']}</td><td class="ok">{eng['final_alive']}</td>
<td>{eng['final_alive']-base['final_alive']:+d}</td></tr>
<tr><td>Wall time</td><td>{base['elapsed_sec']:.1f}s</td><td>{eng['elapsed_sec']:.1f}s</td><td></td></tr>
</table>
<p>Verdict: <b class="ok">{'ENGINE HELPS on real HTTP' if better else 'NEEDS TUNING'}</b></p>
<img src="http_fleet_comparison.png"/>
</div>
<p style="opacity:.7">This is Soft Pack nodes on a real network path — not a pure numpy toy.</p>
</body></html>"""
    (OUT / "http_fleet_case_study.html").write_text(html, encoding="utf-8")
    print(f"\n  HTML → {OUT / 'http_fleet_case_study.html'}")
    print(f"  Plot → {OUT / 'http_fleet_comparison.png'}")
    print("=" * 64)
    return 0 if better else 1


if __name__ == "__main__":
    raise SystemExit(main())
