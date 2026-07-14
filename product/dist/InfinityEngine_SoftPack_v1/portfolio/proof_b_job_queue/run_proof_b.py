"""
Proof B — Job / worker queue under retry storms
===============================================
Open-source-shaped problem: parallel workers process jobs.
Failures + retry stampedes raise load. Compare baseline vs KERNEL_v1.

  python run_proof_b.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
ENGINE_ROOT = HERE.parents[1]
sys.path.insert(0, str(ENGINE_ROOT))
sys.path.insert(0, str(HERE))

try:
    import KERNEL_v1 as K
except ImportError:
    print("ERROR: KERNEL_v1.py not found in", ENGINE_ROOT)
    sys.exit(1)

OUT = HERE / "out"
OUT.mkdir(exist_ok=True)


class JobQueueWorld:
    """N workers pulling from a job queue; failures cause retries (stampede risk)."""

    def __init__(self, n_workers: int = 16, rng: np.random.Generator | None = None):
        self.n_workers = n_workers
        self.rng = rng or np.random.default_rng(0)
        self.queue = 40
        self.completed = 0
        self.failed_attempts = 0
        self.attempts = 0
        self.alive = np.ones(n_workers, dtype=bool)
        self.worker_fail = np.zeros(n_workers, dtype=int)
        self.recent: list[int] = []
        self.concurrency = n_workers

    def rolling_success(self) -> float:
        if not self.recent:
            return 0.7
        return float(np.mean(self.recent[-50:]))

    def step(self, interference: float) -> dict:
        p_fail = float(np.clip(0.06 + 0.16 * interference + 0.03 * interference**1.3, 0.05, 0.9))
        # backlog pressure
        if self.queue > 80:
            p_fail = min(0.95, p_fail + 0.1)

        active = np.where(self.alive)[0][: max(1, self.concurrency)]
        ok = 0
        tries = 0
        for w in active:
            if self.queue <= 0:
                # refill so the sim keeps stressing workers
                self.queue += int(self.rng.integers(8, 20))
            self.queue -= 1
            self.attempts += 1
            tries += 1
            if self.rng.random() < p_fail:
                self.failed_attempts += 1
                self.worker_fail[w] += 1
                self.recent.append(0)
                # retry storm: put job back + extra junk
                self.queue += 1 + int(self.rng.random() < 0.5)
                if self.worker_fail[w] >= 7 and self.rng.random() < 0.3:
                    self.alive[w] = False
            else:
                self.completed += 1
                self.worker_fail[w] = 0
                self.recent.append(1)
                ok += 1
        if len(self.recent) > 250:
            self.recent = self.recent[-250:]

        return {
            "step_success": (ok / tries) if tries else 0.0,
            "rolling_success": self.rolling_success(),
            "queue": self.queue,
            "n_alive": int(np.sum(self.alive)),
            "completed": self.completed,
            "p_fail": p_fail,
            "interference": interference,
        }

    def quarantine_worst(self, k: int = 1):
        alive_idx = np.where(self.alive)[0]
        if len(alive_idx) == 0:
            return
        order = sorted(alive_idx, key=lambda i: -self.worker_fail[i])
        for i in order[:k]:
            self.alive[i] = False

    def revive(self, k: int = 1):
        dead = np.where(~self.alive)[0]
        for i in dead[:k]:
            self.alive[i] = True
            self.worker_fail[i] = 0


def schedule(steps: int, rng: np.random.Generator) -> list[float]:
    spaces = [0.7, 1.3, 1.9, 2.5, 2.95]
    I = 1.2
    out = []
    for _ in range(steps):
        if rng.random() < 0.07:
            I = float(rng.choice(spaces))
        else:
            I = float(np.clip(I + rng.normal(0, 0.06), 0.5, 3.0))
        out.append(I)
    return out


def ingest(roll_sr: float, env_I: float) -> float:
    fail = 1.0 - roll_sr
    return float(np.clip(0.5 * env_I + 1.7 * fail + 0.2, 0.4, 3.0))


def shield(env_I: float, stab: float, target: float = 0.92) -> float:
    if stab >= target - 0.01:
        return env_I * 0.52
    if stab >= target - 0.05:
        return env_I * 0.70
    if stab >= 0.82:
        return env_I * 0.85
    return env_I


def actuate(world: JobQueueWorld, stab: float, target: float = 0.92):
    gap = target - stab
    if gap > 0.10 and world.rolling_success() < 0.5:
        world.quarantine_worst(1)
        world.concurrency = max(4, world.concurrency - 1)
    if stab >= target - 0.02:
        world.revive(2)
        world.concurrency = min(world.n_workers, world.concurrency + 1)
    elif stab >= 0.88:
        world.revive(1)


def run_pair(seed: int = 7, steps: int = 120):
    rng = np.random.default_rng(seed)
    sch = schedule(steps, rng)

    # baseline
    b = JobQueueWorld(rng=np.random.default_rng(seed))
    base_rows = []
    for env_I in sch:
        base_rows.append(b.step(env_I))

    # engine
    w = JobQueueWorld(rng=np.random.default_rng(seed + 1))
    k_rng = np.random.default_rng(seed + 50)
    agents = K.make_swarm(k_rng)
    paradox = K.Paradox(K.PROMOTED_DNA)
    paradox.install_drivers(agents)
    ambient = 0.0
    stab = 0.88
    eng_rows = []
    for env_I in sch:
        felt = shield(env_I, stab)
        m = w.step(felt)
        I = ingest(w.rolling_success(), env_I)
        for a in agents:
            a.step(I, ambient, k_rng)
        ambient = 0.03 * float(np.mean([a.flux for a in agents]))
        paradox.hive_pair_churn(agents, k_rng)
        paradox.install_drivers(agents)
        stab = K.stability(agents)
        actuate(w, stab)
        eng_rows.append({**m, "kernel_stability": stab, "env_I": env_I, "felt_I": felt})

    def summ(rows, key="rolling_success"):
        arr = np.array([r[key] for r in rows], float)
        return {
            "mean": float(np.mean(arr)),
            "late": float(np.mean(arr[-max(1, len(arr) // 5) :])),
            "p10": float(np.percentile(arr, 10)),
            "min": float(np.min(arr)),
        }

    return base_rows, eng_rows, summ(base_rows), summ(eng_rows), summ(eng_rows, "kernel_stability")


def main():
    print("=" * 64)
    print(" PROOF B — Job queue / worker fleet under retry storms")
    print("=" * 64)
    base_rows, eng_rows, bs, es, ks = run_pair()
    print(f"  Baseline rolling success : {bs['mean']:.3f}  late {bs['late']:.3f}")
    print(f"  Engine   rolling success : {es['mean']:.3f}  late {es['late']:.3f}")
    print(f"  Improvement (mean)       : {es['mean'] - bs['mean']:+.3f}")
    print(f"  Kernel late stability    : {ks['late']:.3f}")

    # plot
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    fig.patch.set_facecolor("#0b0f14")
    x = np.arange(len(base_rows))
    ax = axes[0]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["rolling_success"] for r in base_rows], color="#ff6b8a", label="Baseline")
    ax.plot(x, [r["rolling_success"] for r in eng_rows], color="#5dffb0", label="With Engine")
    ax.axhline(0.92, color="#7ec8ff", ls="--", alpha=0.6)
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_title("Proof B: job workers under storms/jumps", color="white")
    ax.set_ylabel("Rolling success", color="white")
    ax = axes[1]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["env_I"] for r in eng_rows], color="#c090ff", label="Env I")
    ax.plot(x, [r["kernel_stability"] for r in eng_rows], color="#40d0ff", label="Kernel stab")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_xlabel("Step", color="white")
    for a in axes:
        for s in a.spines.values():
            s.set_color("#445")
    fig.tight_layout()
    fig.savefig(OUT / "proof_b_comparison.png", dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)

    report = {
        "proof": "B_job_queue",
        "baseline": bs,
        "engine": es,
        "kernel": ks,
        "improvement_mean": es["mean"] - bs["mean"],
    }
    (OUT / "proof_b_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    better = report["improvement_mean"] > 0.03
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>Proof B — Job Queue</title>
<style>
body{{margin:0;padding:28px;background:#0b0f14;color:#e8eef7;font-family:Segoe UI,sans-serif;max-width:900px}}
.ok{{color:#5dffb0}} .card{{background:#121a24;border:1px solid #243044;border-radius:12px;padding:16px;margin:12px 0}}
img{{max-width:100%;border-radius:8px}} table{{width:100%;border-collapse:collapse}}
td,th{{padding:8px;border-bottom:1px solid #243044;text-align:left}}
</style></head><body>
<h1>Proof B — Job / worker queue</h1>
<p><b>Problem:</b> Parallel workers process jobs. Failures retry and stampede the queue under storms/jumps.</p>
<p><b>Approach:</b> KERNEL_v1 health layer — shield load when stable, quarantine worst workers, revive when healthy.</p>
<div class="card">
<table>
<tr><th></th><th>Baseline</th><th>Engine</th><th>Δ</th></tr>
<tr><td>Mean success</td><td>{bs['mean']:.3f}</td><td class="ok">{es['mean']:.3f}</td>
<td>{report['improvement_mean']:+.3f}</td></tr>
<tr><td>Late success</td><td>{bs['late']:.3f}</td><td class="ok">{es['late']:.3f}</td>
<td>{es['late']-bs['late']:+.3f}</td></tr>
<tr><td>p10 floor</td><td>{bs['p10']:.3f}</td><td class="ok">{es['p10']:.3f}</td>
<td>{es['p10']-bs['p10']:+.3f}</td></tr>
<tr><td>Kernel late</td><td>—</td><td>{ks['late']:.3f}</td><td>target 0.92</td></tr>
</table>
<p>Verdict: <b class="ok">{'ENGINE HELPS' if better else 'NEEDS TUNING'}</b></p>
<img src="proof_b_comparison.png"/>
</div>
</body></html>"""
    (OUT / "proof_b_case_study.html").write_text(html, encoding="utf-8")
    print(f"\n  HTML → {OUT / 'proof_b_case_study.html'}")
    print(f"  Plot → {OUT / 'proof_b_comparison.png'}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
