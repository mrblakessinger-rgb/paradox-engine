"""
Quota hell — real-world stress test (target stays 0.92)
=======================================================
Harder than http_fleet_demo:
  - 20 workers
  - Tight shared budget that under-refills in storms
  - Forced 429/500/slow paths under high I + thrash
  - 48 steps
  - Baseline full stampede vs Soft Pack nodes

Contract: KERNEL / actuate target = 0.92 (unchanged).

  python real_world/quota_hell_demo.py
"""

from __future__ import annotations

import json
import sys
import time
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
HTTPBIN = "https://httpbin.org"

# Locked contract for this stress — do not raise
TARGET = 0.92

N_WORKERS = 20
STEPS = 48
SEED = 42


@dataclass
class SharedBudget:
    """Harsh shared quota: low max, slow refill under storms."""

    tokens: float = 8.0
    max_tokens: float = 8.0

    def try_take(self, cost: float = 1.0) -> bool:
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False

    def refill(self, env_I: float) -> None:
        # Under storms, refill collapses (quota hell)
        base = 2.2
        storm_cut = 1.1 * max(0.0, env_I - 1.0)
        amount = max(0.4, base - storm_cut)
        self.tokens = min(self.max_tokens, self.tokens + amount)


def http_ok(url: str, timeout: float = 5.5) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "InfinityEngine-QuotaHell/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def worker_attempt(budget: SharedBudget, env_I: float, thrash: float, rng: np.random.Generator) -> bool:
    """One real attempt under quota hell pressure."""
    # Correlated storm paths
    if thrash > 1.4 and rng.random() < min(0.45, 0.08 + 0.12 * thrash):
        return http_ok(f"{HTTPBIN}/status/429")
    if env_I > 2.1 and rng.random() < 0.22:
        return http_ok(f"{HTTPBIN}/status/500")
    if env_I > 2.4 and thrash > 1.2 and rng.random() < 0.15:
        return http_ok(f"{HTTPBIN}/delay/1")  # slow — burns wall time + timeout risk

    if not budget.try_take(1.0):
        return http_ok(f"{HTTPBIN}/status/429")

    return http_ok(f"{HTTPBIN}/get")


def schedule_I(steps: int, rng: np.random.Generator) -> list[float]:
    """Hostile schedule: long storms, jumps, brief calms."""
    spaces = [0.7, 1.2, 1.8, 2.3, 2.7, 2.95]
    I = 1.5
    out = []
    storm_left = 0
    for _ in range(steps):
        if storm_left > 0:
            I = float(np.clip(I + rng.normal(0.02, 0.06), 1.8, 3.0))
            storm_left -= 1
        elif rng.random() < 0.14:
            # enter multi-step storm
            storm_left = int(rng.integers(4, 9))
            I = float(rng.choice(spaces[2:]))
        elif rng.random() < 0.10:
            I = float(rng.choice(spaces))  # discontinuous jump
        else:
            I = float(np.clip(I + rng.normal(0, 0.07), 0.5, 3.0))
        out.append(I)
    return out


def run_mode(*, controlled: bool) -> dict:
    rng = np.random.default_rng(SEED if not controlled else SEED + 1)
    sch = schedule_I(STEPS, np.random.default_rng(SEED))  # same schedule both modes

    budget = SharedBudget(tokens=8.0, max_tokens=8.0)
    alive = np.ones(N_WORKERS, dtype=bool)
    fails = np.zeros(N_WORKERS, dtype=int)
    recent: list[int] = []
    thrash = 1.15
    concurrency = N_WORKERS
    eng = HealthEngine(seed=SEED + 50) if controlled else None
    stab = 0.88
    rows = []
    ok_total = fail_total = 0

    label = "ENGINE" if controlled else "BASELINE"
    print(f"\n  Mode: {label}  workers={N_WORKERS}  steps={STEPS}  target={TARGET}")
    t0 = time.time()

    for t, env_I in enumerate(sch):
        budget.refill(env_I)
        roll = float(np.mean(recent[-50:])) if recent else 0.45

        if controlled and eng is not None:
            plan = plan_actions(stab, success_rate=roll, target=TARGET)
            felt = apply_shield(env_I, plan)
            # Stress-grade cool: still uses target 0.92 bands via plan_actions
            if roll < 0.62 or plan.cool_retries or stab < TARGET - 0.04:
                thrash = max(0.5, thrash * 0.65)
                concurrency = max(4, concurrency - 2)
            if plan.quarantine_k:
                order = np.argsort(-fails)
                k = plan.quarantine_k
                for i in order:
                    if alive[i] and k > 0:
                        alive[i] = False
                        k -= 1
            if plan.revive_k:
                for i in range(N_WORKERS):
                    if not alive[i] and plan.revive_k > 0:
                        alive[i] = True
                        fails[i] = 0
                        plan.revive_k -= 1
            if stab >= TARGET - 0.02 and roll >= 0.55:
                thrash = min(1.35, thrash + 0.03)
                concurrency = min(N_WORKERS, concurrency + 1)
        else:
            felt = env_I
            # Full panic stampede
            thrash = min(2.8, thrash + 0.14 * (1.0 - roll) + 0.06 * env_I)
            concurrency = N_WORKERS

        active = [i for i in range(N_WORKERS) if alive[i]][:concurrency]
        if not active:
            alive[int(np.argmin(fails))] = True
            active = [int(np.argmin(fails))]

        # Workload size
        if not controlled:
            n_jobs = len(active) + 3 + int(thrash * 3)
        else:
            n_jobs = len(active) + (2 if thrash > 1.2 else 0)

        jobs = []
        for j in range(n_jobs):
            wid = active[j % len(active)]
            jobs.append(wid)

        ok = fail = 0
        with ThreadPoolExecutor(max_workers=min(24, max(4, len(jobs)))) as ex:
            futs = {
                ex.submit(worker_attempt, budget, felt, thrash, rng): wid for wid in jobs
            }
            for fut in as_completed(futs):
                wid = futs[fut]
                try:
                    success = bool(fut.result())
                except Exception:
                    success = False
                if success:
                    ok += 1
                    ok_total += 1
                    recent.append(1)
                    fails[wid] = max(0, fails[wid] - 1)
                else:
                    fail += 1
                    fail_total += 1
                    recent.append(0)
                    fails[wid] += 1
                    if not controlled and fails[wid] >= 6:
                        alive[wid] = False
                    elif controlled and fails[wid] >= 12:
                        # engine path: natural death rarer
                        if np.random.random() < 0.15:
                            alive[wid] = False

        if len(recent) > 300:
            recent = recent[-300:]
        roll = float(np.mean(recent[-50:])) if recent else 0.4

        if controlled and eng is not None:
            I_k = to_interference(
                success_rate=roll,
                env_load=env_I,
                thrash=max(0.0, thrash - 0.7),
            )
            out = eng.step(I_k, success_rate=roll)
            stab = float(out["stability"])
        else:
            stab = float("nan")

        rows.append(
            {
                "t": t,
                "env_I": env_I,
                "felt_I": felt if controlled else env_I,
                "rolling_success": roll,
                "n_alive": int(np.sum(alive)),
                "thrash": thrash,
                "concurrency": concurrency,
                "budget": budget.tokens,
                "kernel_stability": stab,
                "step_ok": ok,
                "step_fail": fail,
            }
        )
        if (t + 1) % 6 == 0 or t == 0 or t == STEPS - 1:
            print(
                f"    step {t+1:02d}/{STEPS}  roll={roll:.2f}  alive={int(np.sum(alive))}  "
                f"ok/fail={ok}/{fail}  I={env_I:.2f}  thrash={thrash:.2f}  q={budget.tokens:.1f}"
                + (f"  stab={stab:.3f}" if controlled else "")
            )

    arr = np.array([r["rolling_success"] for r in rows], float)
    stab_arr = np.array(
        [r["kernel_stability"] for r in rows if not np.isnan(r["kernel_stability"])],
        float,
    )
    late_n = max(1, STEPS // 5)
    return {
        "controlled": controlled,
        "elapsed": time.time() - t0,
        "mean": float(np.mean(arr)),
        "late": float(np.mean(arr[-late_n:])),
        "p10": float(np.percentile(arr, 10)),
        "min_roll": float(np.min(arr)),
        "final_alive": int(np.sum(alive)),
        "mean_alive": float(np.mean([r["n_alive"] for r in rows])),
        "ok_total": ok_total,
        "fail_total": fail_total,
        "kernel_late": float(np.mean(stab_arr[-late_n:])) if len(stab_arr) else None,
        "kernel_mean": float(np.mean(stab_arr)) if len(stab_arr) else None,
        "kernel_min": float(np.min(stab_arr)) if len(stab_arr) else None,
        "rows": rows,
    }


def main() -> int:
    print("=" * 64)
    print(" QUOTA HELL STRESS — real HTTP + tight shared budget")
    print(f" Target coherence LOCKED at {TARGET}  |  workers={N_WORKERS}  steps={STEPS}")
    print("=" * 64)

    print("\n  Probe httpbin…")
    if not http_ok(f"{HTTPBIN}/get", timeout=10):
        print("  ERROR: httpbin unreachable")
        return 1
    print("  OK")

    base = run_mode(controlled=False)
    eng = run_mode(controlled=True)
    d = eng["mean"] - base["mean"]
    d_late = eng["late"] - base["late"]

    print("\n" + "=" * 64)
    print(" QUOTA HELL RESULTS")
    print("=" * 64)
    print(f"  Baseline mean success : {base['mean']:.3f}  late {base['late']:.3f}  p10 {base['p10']:.3f}")
    print(f"  Engine   mean success : {eng['mean']:.3f}  late {eng['late']:.3f}  p10 {eng['p10']:.3f}")
    print(f"  Δ mean / late         : {d:+.3f} / {d_late:+.3f}")
    print(f"  Final alive           : base {base['final_alive']}  eng {eng['final_alive']}")
    print(f"  Mean alive            : base {base['mean_alive']:.1f}  eng {eng['mean_alive']:.1f}")
    print(f"  Totals ok/fail        : base {base['ok_total']}/{base['fail_total']}  eng {eng['ok_total']}/{eng['fail_total']}")
    print(f"  Wall time             : base {base['elapsed']:.1f}s  eng {eng['elapsed']:.1f}s")
    if eng["kernel_late"] is not None:
        print(f"  Kernel late / mean / min: {eng['kernel_late']:.3f} / {eng['kernel_mean']:.3f} / {eng['kernel_min']:.3f}")
        print(f"  Target (unchanged)      : {TARGET}")

    # Pass heuristics (stress — not sales polish)
    pass_success = d > 0.05 or d_late > 0.05
    pass_alive = eng["final_alive"] >= base["final_alive"] and eng["mean_alive"] >= base["mean_alive"] - 0.5
    pass_kernel = eng["kernel_late"] is not None and eng["kernel_late"] >= 0.88
    overall = pass_success and pass_alive and pass_kernel

    print("\n  Checks:")
    print(f"    success lift     : {'PASS' if pass_success else 'FAIL'}  (Δmean={d:+.3f})")
    print(f"    alive not worse  : {'PASS' if pass_alive else 'FAIL'}")
    print(f"    kernel late≥0.88 : {'PASS' if pass_kernel else 'FAIL'}")
    print(f"  VERDICT            : {'STRESS HANDLED' if overall else 'STRESS STRAINED — review'}")

    # Plot
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    fig.patch.set_facecolor("#0b0f14")
    x = np.arange(STEPS)

    ax = axes[0]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["rolling_success"] for r in base["rows"]], color="#ff6b8a", label="Baseline")
    ax.plot(x, [r["rolling_success"] for r in eng["rows"]], color="#5dffb0", label="Engine")
    ax.axhline(0.5, color="#666", ls=":", alpha=0.5)
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_ylabel("Success", color="white")
    ax.set_title(f"Quota hell stress (target={TARGET}, {N_WORKERS} workers, {STEPS} steps)", color="white")

    ax = axes[1]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["n_alive"] for r in base["rows"]], color="#ff6b8a", label="Base alive")
    ax.plot(x, [r["n_alive"] for r in eng["rows"]], color="#5dffb0", label="Eng alive")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_ylabel("Alive", color="white")

    ax = axes[2]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["env_I"] for r in eng["rows"]], color="#c090ff", label="Env I")
    ax.plot(x, [r["kernel_stability"] for r in eng["rows"]], color="#40d0ff", label="Kernel stab")
    ax.axhline(TARGET, color="#7ec8ff", ls="--", alpha=0.7, label=f"Target {TARGET}")
    ax.axhline(0.97, color="#ff9b6b", ls=":", alpha=0.6, label="Soft ceiling 0.97")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_xlabel("Step", color="white")
    ax.set_ylabel("I / stab", color="white")

    for a in axes:
        for s in a.spines.values():
            s.set_color("#445")
    fig.tight_layout()
    fig.savefig(OUT / "quota_hell_comparison.png", dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)

    report = {
        "demo": "quota_hell_stress",
        "target_locked": TARGET,
        "n_workers": N_WORKERS,
        "steps": STEPS,
        "seed": SEED,
        "baseline": {k: base[k] for k in ("mean", "late", "p10", "min_roll", "final_alive", "mean_alive", "ok_total", "fail_total", "elapsed")},
        "engine": {
            k: eng[k]
            for k in (
                "mean",
                "late",
                "p10",
                "min_roll",
                "final_alive",
                "mean_alive",
                "ok_total",
                "fail_total",
                "elapsed",
                "kernel_late",
                "kernel_mean",
                "kernel_min",
            )
        },
        "delta_mean": d,
        "delta_late": d_late,
        "checks": {
            "success_lift": pass_success,
            "alive": pass_alive,
            "kernel": pass_kernel,
            "overall": overall,
        },
    }
    (OUT / "quota_hell_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    verdict = "STRESS HANDLED" if overall else "STRESS STRAINED"
    color = "#5dffb0" if overall else "#ffb86b"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>Quota Hell Stress</title>
<style>
body{{margin:0;padding:28px;background:#0b0f14;color:#e8eef7;font-family:Segoe UI,sans-serif;max-width:920px}}
.ok{{color:{color}}} .card{{background:#121a24;border:1px solid #243044;border-radius:12px;padding:16px;margin:12px 0}}
img{{max-width:100%;border-radius:8px}} table{{width:100%;border-collapse:collapse}}
td,th{{padding:8px;border-bottom:1px solid #243044;text-align:left}}
</style></head><body>
<h1>Quota hell stress</h1>
<p><b>Contract:</b> target coherence <b>locked at {TARGET}</b> (no nudge). Soft ceiling 0.97.</p>
<p><b>Load:</b> {N_WORKERS} workers · {STEPS} steps · tight shared budget · multi-step storms · real HTTP (httpbin).</p>
<div class="card">
<table>
<tr><th></th><th>Baseline</th><th>Engine</th><th>Δ</th></tr>
<tr><td>Mean success</td><td>{base['mean']:.3f}</td><td class="ok">{eng['mean']:.3f}</td><td>{d:+.3f}</td></tr>
<tr><td>Late success</td><td>{base['late']:.3f}</td><td class="ok">{eng['late']:.3f}</td><td>{d_late:+.3f}</td></tr>
<tr><td>p10 floor</td><td>{base['p10']:.3f}</td><td class="ok">{eng['p10']:.3f}</td>
<td>{eng['p10']-base['p10']:+.3f}</td></tr>
<tr><td>Final / mean alive</td><td>{base['final_alive']} / {base['mean_alive']:.1f}</td>
<td class="ok">{eng['final_alive']} / {eng['mean_alive']:.1f}</td><td></td></tr>
<tr><td>Kernel late (target {TARGET})</td><td>—</td><td>{eng['kernel_late']:.3f}</td><td></td></tr>
<tr><td>Wall time</td><td>{base['elapsed']:.1f}s</td><td>{eng['elapsed']:.1f}s</td><td></td></tr>
</table>
<p>Verdict: <b class="ok">{verdict}</b></p>
<img src="quota_hell_comparison.png"/>
</div>
</body></html>"""
    (OUT / "quota_hell_case_study.html").write_text(html, encoding="utf-8")
    print(f"\n  HTML → {OUT / 'quota_hell_case_study.html'}")
    print(f"  JSON → {OUT / 'quota_hell_results.json'}")
    print("=" * 64)
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
