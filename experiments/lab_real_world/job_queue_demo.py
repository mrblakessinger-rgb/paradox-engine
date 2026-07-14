"""
Real-world demo 3 — Job / worker queue (real HTTP jobs)
=======================================================
Jobs are real HTTP fetches. Failures re-queue (retry storm).
Baseline vs Soft Pack nodes (cool concurrency, quarantine, revive).

  python real_world/job_queue_demo.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodes.actuate import apply_shield, plan_actions
from nodes.engine_loop import HealthEngine
from nodes.ingest import from_queue

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
HTTPBIN = "https://httpbin.org"

JOB_URLS = [
    f"{HTTPBIN}/get",
    f"{HTTPBIN}/uuid",
    f"{HTTPBIN}/bytes/64",
    f"{HTTPBIN}/status/200",
]


def do_job(url: str, env_I: float, rng: np.random.Generator) -> bool:
    """Execute one job = real HTTP. Storms may rewrite to fail URLs."""
    if env_I > 2.0 and rng.random() < 0.2:
        url = f"{HTTPBIN}/status/500"
    elif env_I > 1.5 and rng.random() < 0.12:
        url = f"{HTTPBIN}/status/429"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "InfinityEngine-JobQueue/1.0"})
        with urllib.request.urlopen(req, timeout=6.0) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def run_mode(*, controlled: bool, steps: int = 18, n_workers: int = 10, seed: int = 33) -> dict:
    rng = np.random.default_rng(seed)
    queue: list[str] = [rng.choice(JOB_URLS) for _ in range(30)]
    alive = np.ones(n_workers, dtype=bool)
    fails = np.zeros(n_workers, dtype=int)
    recent: list[int] = []
    concurrency = n_workers
    thrash_retries = 0.0
    completed = 0
    eng = HealthEngine(seed=seed + 7) if controlled else None
    stab = 0.88
    rows = []

    I = 1.2
    sch = []
    for _ in range(steps):
        if rng.random() < 0.12:
            I = float(rng.choice([0.8, 1.5, 2.1, 2.7]))
        else:
            I = float(np.clip(I + rng.normal(0, 0.08), 0.5, 2.95))
        sch.append(I)

    label = "ENGINE" if controlled else "BASELINE"
    print(f"\n  Mode: {label}  workers={n_workers}  steps={steps}")
    t0 = time.time()

    for t, env_I in enumerate(sch):
        # keep queue fed
        if len(queue) < 8:
            queue.extend(rng.choice(JOB_URLS) for _ in range(int(rng.integers(10, 18))))

        roll = float(np.mean(recent[-50:])) if recent else 0.55
        if controlled and eng is not None:
            plan = plan_actions(stab, success_rate=roll)
            felt = apply_shield(env_I, plan)
            if roll < 0.65 or plan.cool_retries or stab < 0.90:
                thrash_retries = max(0.0, thrash_retries * 0.6)
                concurrency = max(3, concurrency - 1)
            if plan.quarantine_k:
                order = np.argsort(-fails)
                k = plan.quarantine_k
                for i in order:
                    if alive[i] and k > 0:
                        alive[i] = False
                        k -= 1
            if plan.revive_k:
                for i in range(n_workers):
                    if not alive[i] and plan.revive_k > 0:
                        alive[i] = True
                        fails[i] = 0
                        plan.revive_k -= 1
            if stab >= 0.91 and roll >= 0.6:
                concurrency = min(n_workers, concurrency + 1)
                thrash_retries = max(0.0, thrash_retries - 0.1)
        else:
            felt = env_I
            thrash_retries = min(3.0, thrash_retries + 0.15 * (1.0 - roll) + 0.05 * env_I)
            concurrency = n_workers

        active = [i for i in range(n_workers) if alive[i]][:concurrency]
        if not active:
            alive[0] = True
            active = [0]

        # Pull jobs
        batch = []
        for wid in active:
            if not queue:
                queue.append(str(rng.choice(JOB_URLS)))
            batch.append((wid, queue.pop(0)))

        # Baseline: re-queue noise (stampede)
        extras = int(thrash_retries * 2) if not controlled else (1 if thrash_retries > 0.5 else 0)
        for _ in range(extras):
            batch.append((-1, str(rng.choice(JOB_URLS))))

        ok = fail = 0
        with ThreadPoolExecutor(max_workers=max(1, len(batch))) as ex:
            futs = {
                ex.submit(do_job, url, felt, rng): wid for wid, url in batch
            }
            for fut in as_completed(futs):
                wid = futs[fut]
                success = bool(fut.result())
                if success:
                    ok += 1
                    completed += 1
                    recent.append(1)
                    if wid >= 0:
                        fails[wid] = max(0, fails[wid] - 1)
                else:
                    fail += 1
                    recent.append(0)
                    # retry: put job back
                    queue.append(str(rng.choice(JOB_URLS)))
                    if not controlled:
                        thrash_retries = min(3.0, thrash_retries + 0.08)
                    if wid >= 0:
                        fails[wid] += 1
                        if not controlled and fails[wid] >= 5:
                            alive[wid] = False

        if len(recent) > 250:
            recent = recent[-250:]
        roll = float(np.mean(recent[-50:])) if recent else 0.5

        if controlled and eng is not None:
            I_k = from_queue(roll, env_I, queue_depth=len(queue), capacity=40)
            out = eng.step(I_k, success_rate=roll)
            stab = float(out["stability"])
        else:
            stab = float("nan")

        rows.append(
            {
                "rolling_success": roll,
                "env_I": env_I,
                "queue": len(queue),
                "n_alive": int(np.sum(alive)),
                "thrash": thrash_retries,
                "kernel_stability": stab,
                "completed": completed,
            }
        )
        print(
            f"    step {t+1:02d}/{steps}  roll={roll:.2f}  q={len(queue)}  "
            f"alive={int(np.sum(alive))}  ok/fail={ok}/{fail}"
            + (f"  stab={stab:.3f}" if controlled else "")
        )

    arr = np.array([r["rolling_success"] for r in rows], float)
    return {
        "elapsed": time.time() - t0,
        "mean": float(np.mean(arr)),
        "late": float(np.mean(arr[-max(1, len(arr) // 5) :])),
        "p10": float(np.percentile(arr, 10)),
        "final_alive": int(np.sum(alive)),
        "completed": completed,
        "final_queue": len(queue),
        "rows": rows,
    }


def main() -> int:
    print("=" * 64)
    print(" REAL-WORLD JOB QUEUE — workers + real HTTP jobs")
    print("=" * 64)
    print("  Checking network…")
    try:
        urllib.request.urlopen(f"{HTTPBIN}/get", timeout=10)
        print("  OK")
    except Exception:
        print("  ERROR: httpbin unreachable")
        return 1

    base = run_mode(controlled=False)
    eng = run_mode(controlled=True)
    d = eng["mean"] - base["mean"]

    print("\n" + "=" * 64)
    print(" RESULTS")
    print("=" * 64)
    print(f"  Baseline mean : {base['mean']:.3f}  late {base['late']:.3f}  alive {base['final_alive']}")
    print(f"  Engine   mean : {eng['mean']:.3f}  late {eng['late']:.3f}  alive {eng['final_alive']}")
    print(f"  Δ mean        : {d:+.3f}")
    print(f"  Completed jobs: base {base['completed']}  eng {eng['completed']}")
    print(f"  Wall time     : base {base['elapsed']:.1f}s  eng {eng['elapsed']:.1f}s")

    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    fig.patch.set_facecolor("#0b0f14")
    x = np.arange(len(base["rows"]))
    ax = axes[0]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["rolling_success"] for r in base["rows"]], color="#ff6b8a", label="Baseline")
    ax.plot(x, [r["rolling_success"] for r in eng["rows"]], color="#5dffb0", label="Soft Pack nodes")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_title("Real-world job queue (HTTP jobs + retry re-queue)", color="white")
    ax.set_ylabel("Rolling success", color="white")
    ax = axes[1]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["queue"] for r in base["rows"]], color="#ff6b8a", alpha=0.7, label="Base queue")
    ax.plot(x, [r["queue"] for r in eng["rows"]], color="#5dffb0", alpha=0.7, label="Eng queue")
    ax.plot(x, [r["kernel_stability"] for r in eng["rows"]], color="#40d0ff", label="Kernel stab")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_xlabel("Step", color="white")
    for a in axes:
        for s in a.spines.values():
            s.set_color("#445")
    fig.tight_layout()
    fig.savefig(OUT / "job_queue_comparison.png", dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)

    report = {
        "demo": "real_world_job_queue",
        "baseline": {k: base[k] for k in ("mean", "late", "p10", "final_alive", "completed", "elapsed")},
        "engine": {k: eng[k] for k in ("mean", "late", "p10", "final_alive", "completed", "elapsed")},
        "improvement_mean": d,
    }
    (OUT / "job_queue_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>Real-world job queue</title>
<style>
body{{margin:0;padding:28px;background:#0b0f14;color:#e8eef7;font-family:Segoe UI,sans-serif;max-width:900px}}
.ok{{color:#5dffb0}} .card{{background:#121a24;border:1px solid #243044;border-radius:12px;padding:16px}}
img{{max-width:100%;border-radius:8px}} table{{width:100%;border-collapse:collapse}}
td,th{{padding:8px;border-bottom:1px solid #243044;text-align:left}}
</style></head><body>
<h1>Real-world job queue</h1>
<p>Workers pull jobs that are <b>real HTTP fetches</b>. Failures re-queue (retry storm).
Soft Pack nodes cool concurrency and quarantine bad workers.</p>
<div class="card">
<table>
<tr><th></th><th>Baseline</th><th>Engine</th><th>Δ</th></tr>
<tr><td>Mean success</td><td>{base['mean']:.3f}</td><td class="ok">{eng['mean']:.3f}</td><td>{d:+.3f}</td></tr>
<tr><td>Late success</td><td>{base['late']:.3f}</td><td class="ok">{eng['late']:.3f}</td>
<td>{eng['late']-base['late']:+.3f}</td></tr>
<tr><td>Workers alive</td><td>{base['final_alive']}</td><td class="ok">{eng['final_alive']}</td>
<td>{eng['final_alive']-base['final_alive']:+d}</td></tr>
<tr><td>Jobs completed</td><td>{base['completed']}</td><td class="ok">{eng['completed']}</td>
<td>{eng['completed']-base['completed']:+d}</td></tr>
</table>
<img src="job_queue_comparison.png"/>
</div>
</body></html>"""
    (OUT / "job_queue_case_study.html").write_text(html, encoding="utf-8")
    print(f"\n  HTML → {OUT / 'job_queue_case_study.html'}")
    print("=" * 64)
    return 0 if d > 0.02 else 1


if __name__ == "__main__":
    raise SystemExit(main())
