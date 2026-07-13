"""
Proof C — API / rate-limit storm (retry thrash)
===============================================
Many clients share one API budget. Storms cut capacity.
Naive clients stampede retries and burn out; engine cools + shields.

Primary metric: goodput = successful calls / n_clients (fixed denom).
(Success-rate alone can look better when half the fleet dies.)

  python run_proof_c.py
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

try:
    import KERNEL_v1 as K
except ImportError:
    print("ERROR: KERNEL_v1.py not found in", ENGINE_ROOT)
    sys.exit(1)

OUT = HERE / "out"
OUT.mkdir(exist_ok=True)


class RateLimitWorld:
    def __init__(self, n_clients: int = 24, budget: float = 12.0, rng: np.random.Generator | None = None):
        self.n_clients = n_clients
        self.base_budget = budget
        self.rng = rng or np.random.default_rng(0)
        self.alive = np.ones(n_clients, dtype=bool)
        self.client_fail = np.zeros(n_clients, dtype=int)
        self.recent_ok: list[int] = []  # per-attempt outcomes
        self.recent_goodput: list[float] = []  # ok / n_clients per step
        self.retries = 0.0  # extra demand multiplier from thrash
        self.ok_total = 0
        self.attempts = 0

    def rolling_success(self) -> float:
        if not self.recent_ok:
            return 0.5
        return float(np.mean(self.recent_ok[-80:]))

    def rolling_goodput(self) -> float:
        if not self.recent_goodput:
            return 0.3
        return float(np.mean(self.recent_goodput[-20:]))

    def step(self, interference: float) -> dict:
        capacity = self.base_budget * max(0.1, 1.0 - 0.30 * interference)
        active = list(np.where(self.alive)[0])
        # Each alive client: 1 base call + retry extras from thrash
        extras = int(round(self.retries * len(active)))
        demand = len(active) + extras
        if demand <= 0:
            self.recent_goodput.append(0.0)
            return {
                "rolling_success": self.rolling_success(),
                "rolling_goodput": self.rolling_goodput(),
                "step_goodput": 0.0,
                "n_alive": 0,
                "retries": self.retries,
                "capacity": capacity,
                "demand": 0,
                "interference": interference,
            }

        serve = int(min(demand, max(0, round(capacity))))
        flake = float(np.clip(0.06 + 0.14 * interference, 0.05, 0.65))

        ok = 0
        fails = 0
        for i in range(demand):
            c = int(active[i % len(active)])
            self.attempts += 1
            if i < serve and self.rng.random() > flake:
                ok += 1
                self.ok_total += 1
                self.client_fail[c] = max(0, self.client_fail[c] - 1)
                self.recent_ok.append(1)
            else:
                fails += 1
                self.client_fail[c] += 1
                self.recent_ok.append(0)
                # stampede: failures raise retries
                self.retries = min(2.5, self.retries + 0.04)
                if self.client_fail[c] >= 7 and self.rng.random() < 0.35:
                    self.alive[c] = False

        # slight cool when clean
        if fails == 0:
            self.retries = max(0.0, self.retries - 0.08)

        if len(self.recent_ok) > 400:
            self.recent_ok = self.recent_ok[-400:]

        step_gp = ok / self.n_clients
        self.recent_goodput.append(step_gp)
        if len(self.recent_goodput) > 80:
            self.recent_goodput = self.recent_goodput[-80:]

        return {
            "rolling_success": self.rolling_success(),
            "rolling_goodput": self.rolling_goodput(),
            "step_goodput": step_gp,
            "n_alive": int(np.sum(self.alive)),
            "retries": self.retries,
            "capacity": capacity,
            "demand": demand,
            "interference": interference,
            "ok": ok,
            "fails": fails,
        }

    def quarantine_worst(self, k: int = 1):
        alive_idx = np.where(self.alive)[0]
        if len(alive_idx) == 0:
            return
        order = sorted(alive_idx, key=lambda i: -self.client_fail[i])
        for i in order[:k]:
            self.alive[i] = False

    def revive(self, k: int = 1):
        dead = np.where(~self.alive)[0]
        for i in dead[:k]:
            self.alive[i] = True
            self.client_fail[i] = 0


def schedule(steps: int, rng: np.random.Generator) -> list[float]:
    spaces = [0.7, 1.3, 1.9, 2.5, 2.95]
    I = 1.2
    out = []
    for _ in range(steps):
        if rng.random() < 0.09:
            I = float(rng.choice(spaces))
        else:
            I = float(np.clip(I + rng.normal(0, 0.07), 0.5, 3.0))
        out.append(I)
    return out


def ingest(goodput: float, env_I: float, retries: float) -> float:
    # low goodput + thrash → high I
    pain = 1.0 - float(np.clip(goodput / 0.55, 0, 1))
    return float(np.clip(0.45 * env_I + 1.5 * pain + 0.25 * retries + 0.2, 0.4, 3.0))


def shield(env_I: float, stab: float, target: float = 0.92) -> float:
    if stab >= target - 0.01:
        return env_I * 0.52
    if stab >= target - 0.05:
        return env_I * 0.70
    if stab >= 0.82:
        return env_I * 0.86
    return env_I


def actuate(world: RateLimitWorld, stab: float, target: float = 0.92):
    gp = world.rolling_goodput()
    # Cool thrash + shed worst offenders when unhealthy
    if gp < 0.28 or stab < target - 0.05:
        world.retries = max(0.0, world.retries * 0.72)
    if gp < 0.18:
        world.quarantine_worst(1)
        world.retries = max(0.0, world.retries * 0.65)
    # Healthy swarm → bring clients back and allow mild traffic
    if stab >= target - 0.02:
        world.revive(2)
        world.retries = max(0.0, world.retries - 0.05)
    elif stab >= 0.88:
        world.revive(1)


def run_pair(seed: int = 13, steps: int = 120):
    rng = np.random.default_rng(seed)
    sch = schedule(steps, rng)

    b = RateLimitWorld(rng=np.random.default_rng(seed))
    base_rows = []
    for env_I in sch:
        base_rows.append(b.step(env_I))

    w = RateLimitWorld(rng=np.random.default_rng(seed + 1))
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
        I = ingest(w.rolling_goodput(), env_I, w.retries)
        for a in agents:
            a.step(I, ambient, k_rng)
        ambient = 0.03 * float(np.mean([a.flux for a in agents]))
        paradox.hive_pair_churn(agents, k_rng)
        paradox.install_drivers(agents)
        stab = K.stability(agents)
        actuate(w, stab)
        eng_rows.append({**m, "kernel_stability": stab, "env_I": env_I, "felt_I": felt})

    def summ(rows, key="rolling_goodput"):
        arr = np.array([r[key] for r in rows], float)
        return {
            "mean": float(np.mean(arr)),
            "late": float(np.mean(arr[-max(1, len(arr) // 5) :])),
            "p10": float(np.percentile(arr, 10)),
            "min": float(np.min(arr)),
        }

    alive_b = float(np.mean([r["n_alive"] for r in base_rows[-24:]]))
    alive_e = float(np.mean([r["n_alive"] for r in eng_rows[-24:]]))
    return (
        base_rows,
        eng_rows,
        summ(base_rows),
        summ(eng_rows),
        summ(eng_rows, "kernel_stability"),
        alive_b,
        alive_e,
    )


def main() -> int:
    print("=" * 64)
    print(" PROOF C — API rate-limit / retry thrash under storms")
    print("=" * 64)
    base_rows, eng_rows, bs, es, ks, alive_b, alive_e = run_pair()
    print(f"  Baseline goodput         : {bs['mean']:.3f}  late {bs['late']:.3f}")
    print(f"  Engine   goodput         : {es['mean']:.3f}  late {es['late']:.3f}")
    print(f"  Improvement (mean)       : {es['mean'] - bs['mean']:+.3f}")
    print(f"  Late clients alive       : base {alive_b:.1f}  eng {alive_e:.1f}")
    print(f"  Kernel late stability    : {ks['late']:.3f}")

    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    fig.patch.set_facecolor("#0b0f14")
    x = np.arange(len(base_rows))
    ax = axes[0]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["rolling_goodput"] for r in base_rows], color="#ff6b8a", label="Baseline goodput")
    ax.plot(x, [r["rolling_goodput"] for r in eng_rows], color="#5dffb0", label="Engine goodput")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_title("Proof C: API clients under rate-limit storms", color="white")
    ax.set_ylabel("Rolling goodput", color="white")
    ax = axes[1]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["env_I"] for r in eng_rows], color="#c090ff", label="Env I")
    ax.plot(x, [r["kernel_stability"] for r in eng_rows], color="#40d0ff", label="Kernel stab")
    ax.plot(x, [r["n_alive"] / 24 for r in eng_rows], color="#ffd060", alpha=0.85, label="Alive frac")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_xlabel("Step", color="white")
    for a in axes:
        for s in a.spines.values():
            s.set_color("#445")
    fig.tight_layout()
    fig.savefig(OUT / "proof_c_comparison.png", dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)

    report = {
        "proof": "C_rate_limit",
        "metric": "rolling_goodput",
        "baseline": bs,
        "engine": es,
        "kernel": ks,
        "late_alive_baseline": alive_b,
        "late_alive_engine": alive_e,
        "improvement_mean": es["mean"] - bs["mean"],
    }
    (OUT / "proof_c_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    better = report["improvement_mean"] > 0.02
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>Proof C — Rate Limit</title>
<style>
body{{margin:0;padding:28px;background:#0b0f14;color:#e8eef7;font-family:Segoe UI,sans-serif;max-width:900px}}
.ok{{color:#5dffb0}} .card{{background:#121a24;border:1px solid #243044;border-radius:12px;padding:16px;margin:12px 0}}
img{{max-width:100%;border-radius:8px}} table{{width:100%;border-collapse:collapse}}
td,th{{padding:8px;border-bottom:1px solid #243044;text-align:left}}
</style></head><body>
<h1>Proof C — API rate-limit / retry thrash</h1>
<p><b>Problem:</b> Shared API budget. Storms cut capacity; retries stampede; clients burn out.</p>
<p><b>Metric:</b> <code>goodput = successes / n_clients</code> (killing clients cannot fake a win).</p>
<p><b>Approach:</b> KERNEL_v1 — shield load, cool retries, quarantine worst, revive when healthy.</p>
<div class="card">
<table>
<tr><th></th><th>Baseline</th><th>Engine</th><th>Δ</th></tr>
<tr><td>Mean goodput</td><td>{bs['mean']:.3f}</td><td class="ok">{es['mean']:.3f}</td>
<td>{report['improvement_mean']:+.3f}</td></tr>
<tr><td>Late goodput</td><td>{bs['late']:.3f}</td><td class="ok">{es['late']:.3f}</td>
<td>{es['late']-bs['late']:+.3f}</td></tr>
<tr><td>p10 floor</td><td>{bs['p10']:.3f}</td><td class="ok">{es['p10']:.3f}</td>
<td>{es['p10']-bs['p10']:+.3f}</td></tr>
<tr><td>Late clients alive</td><td>{alive_b:.1f}</td><td class="ok">{alive_e:.1f}</td>
<td>{alive_e-alive_b:+.1f}</td></tr>
<tr><td>Kernel late</td><td>—</td><td>{ks['late']:.3f}</td><td>target 0.92</td></tr>
</table>
<p>Verdict: <b class="ok">{'ENGINE HELPS' if better else 'NEEDS TUNING'}</b></p>
<img src="proof_c_comparison.png"/>
</div>
</body></html>"""
    (OUT / "proof_c_case_study.html").write_text(html, encoding="utf-8")
    print(f"\n  HTML → {OUT / 'proof_c_case_study.html'}")
    print(f"  Plot → {OUT / 'proof_c_comparison.png'}")
    print("=" * 64)
    return 0 if better else 1


if __name__ == "__main__":
    raise SystemExit(main())
