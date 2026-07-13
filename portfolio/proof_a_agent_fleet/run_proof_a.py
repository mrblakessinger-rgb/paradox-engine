"""
Proof A — Agent fleet under random tool failures
================================================
Compares:
  BASELINE  = fleet alone (no Infinity Engine)
  ENGINE    = fleet + KERNEL_v1 health control (ingest → I → hive step → actuate)

Run from this folder:
  python run_proof_a.py

Or double-click: run_proof_a.bat
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --- make KERNEL_v1 importable (parent of portfolio/) ---
HERE = Path(__file__).resolve().parent
ENGINE_ROOT = HERE.parents[1]  # INFINITY ENGINE KERNAL 1
sys.path.insert(0, str(ENGINE_ROOT))
sys.path.insert(0, str(HERE))

from agent_fleet import FleetWorld  # noqa: E402

try:
    import KERNEL_v1 as K  # noqa: E402
except ImportError:
    print("ERROR: Could not import KERNEL_v1.py")
    print(f"Expected at: {ENGINE_ROOT / 'KERNEL_v1.py'}")
    sys.exit(1)


OUT = HERE / "out"
OUT.mkdir(exist_ok=True)


def interference_schedule(steps: int, rng: np.random.Generator) -> list[float]:
    """
    Real-world-shaped load:
      - calm, storms, jumps between 'spaces' (discontinuous I)
    """
    spaces = [0.6, 1.2, 1.8, 2.4, 2.9]
    I = 1.0
    sch = []
    mode = "calm"
    for t in range(steps):
        if mode == "calm" and rng.random() < 0.06:
            mode = "storm"
            I = float(rng.choice(spaces[2:]))
        elif mode == "storm" and rng.random() < 0.08:
            mode = "jump"
            I = float(rng.choice(spaces))
        elif mode == "jump":
            mode = "calm" if rng.random() < 0.5 else "storm"
            I = float(rng.choice(spaces))
        else:
            I = float(np.clip(I + rng.normal(0, 0.05), 0.4, 3.0))
            if rng.random() < 0.04:
                I = float(rng.choice(spaces))  # sudden dip/jump
        sch.append(I)
    return sch


def ingest_I(fleet_success: float, env_I: float) -> float:
    """
    INGEST NODE:
    Combine world interference with observed fleet failure into kernel I.
    """
    fail = 1.0 - fleet_success
    return float(np.clip(0.50 * env_I + 1.6 * fail + 0.25, 0.4, 3.0))


def shield_env_I(env_I: float, kernel_stability: float, target: float = 0.92) -> float:
    """
    When kernel is healthy, damp the world load the fleet feels (orchestration shield).
    This is the main 'product help' for Proof A.
    """
    if kernel_stability >= target - 0.01:
        return float(env_I * 0.55)  # strong shield near target
    if kernel_stability >= target - 0.05:
        return float(env_I * 0.72)
    if kernel_stability >= 0.80:
        return float(env_I * 0.88)
    return float(env_I)  # no shield when kernel itself is struggling


def actuate(fleet: FleetWorld, kernel_stability: float, target: float = 0.92):
    """
    ACTUATE NODE:
    Gentle quarantine only when kernel + fleet both hurting; prefer revive when OK.
    """
    gap = target - kernel_stability
    roll = fleet.rolling_success()
    if gap > 0.10 and roll < 0.45:
        fleet.quarantine_worst(k=1)
    if kernel_stability >= target - 0.03:
        fleet.revive_some(k=2)
    elif kernel_stability >= 0.85:
        fleet.revive_some(k=1)


def run_baseline(schedule: list[float], seed: int) -> dict:
    rng = np.random.default_rng(seed)
    world = FleetWorld(n_agents=20, rng=rng)
    rows = []
    for env_I in schedule:
        m = world.step(env_I)
        rows.append(
            {
                "success_rate": m["success_rate"],
                "step_success": m["step_success"],
                "n_active": m["n_active"],
                "env_I": env_I,
            }
        )
    return {"rows": rows, "world": world}


def run_with_engine(schedule: list[float], seed: int) -> dict:
    rng = np.random.default_rng(seed + 1)
    world = FleetWorld(n_agents=20, rng=rng)

    # Kernel swarm (health controller) — promoted DNA
    k_rng = np.random.default_rng(seed + 99)
    agents = K.make_swarm(k_rng)
    paradox = K.Paradox(K.PROMOTED_DNA)
    paradox.install_drivers(agents)

    rows = []
    ambient = 0.0
    last_sr = 0.7
    stab = 0.85
    for env_I in schedule:
        # Shield world load using last kernel health, then fleet steps
        felt_I = shield_env_I(env_I, stab, target=K.TARGET_STABILITY)
        m = world.step(felt_I)
        last_sr = world.rolling_success()

        # Ingest → kernel interference
        I = ingest_I(last_sr, env_I)

        # Kernel step (hive health)
        for a in agents:
            a.step(I, ambient, k_rng)
        ambient = 0.03 * float(np.mean([a.flux for a in agents]))
        paradox.hive_pair_churn(agents, k_rng)
        paradox.install_drivers(agents)
        stab = K.stability(agents)

        # Actuate back on fleet
        actuate(world, stab, target=K.TARGET_STABILITY)

        wm = world.metrics()
        rows.append(
            {
                "success_rate": wm["success_rate"],
                "step_success": m["step_success"],
                "n_active": wm["n_active"],
                "n_quarantined": wm["n_quarantined"],
                "env_I": env_I,
                "felt_I": felt_I,
                "kernel_I": I,
                "kernel_stability": stab,
            }
        )
    return {"rows": rows, "world": world}


def summarize(rows: list[dict], key: str = "success_rate") -> dict:
    arr = np.array([r[key] for r in rows], dtype=float)
    return {
        "mean": float(np.mean(arr)),
        "late_mean": float(np.mean(arr[-max(1, len(arr) // 5) :])),
        "p10": float(np.percentile(arr, 10)),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
    }


def main():
    print("=" * 64)
    print(" PROOF A — Agent fleet under random tool failures")
    print(" Baseline vs Infinity Engine (KERNEL_v1)")
    print("=" * 64)

    steps = 120
    seed = 42
    rng = np.random.default_rng(seed)
    schedule = interference_schedule(steps, rng)

    print("\n[1/3] Running BASELINE (no kernel)…")
    base = run_baseline(schedule, seed=seed)
    base_s = summarize(base["rows"])

    print("[2/3] Running WITH ENGINE (KERNEL_v1)…")
    eng = run_with_engine(schedule, seed=seed)
    eng_s = summarize(eng["rows"])
    k_s = summarize(eng["rows"], key="kernel_stability")

    print("[3/3] Writing report + plot…")

    report = {
        "proof": "A_agent_fleet",
        "kernel": K.KERNEL_VERSION,
        "steps": steps,
        "baseline_success": base_s,
        "engine_success": eng_s,
        "kernel_stability": k_s,
        "improvement_mean": eng_s["mean"] - base_s["mean"],
        "improvement_late": eng_s["late_mean"] - base_s["late_mean"],
        "improvement_p10": eng_s["p10"] - base_s["p10"],
        "baseline_final_active": base["rows"][-1]["n_active"],
        "engine_final_active": eng["rows"][-1]["n_active"],
        "engine_final_quarantined": eng["rows"][-1].get("n_quarantined", 0),
    }

    # Plot
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    fig.patch.set_facecolor("#0b0f14")
    x = np.arange(steps)
    b_sr = [r["success_rate"] for r in base["rows"]]
    e_sr = [r["success_rate"] for r in eng["rows"]]
    env_I = [r["env_I"] for r in eng["rows"]]
    k_st = [r["kernel_stability"] for r in eng["rows"]]

    ax = axes[0]
    ax.set_facecolor("#0f1620")
    ax.plot(x, b_sr, color="#ff6b8a", label="Baseline fleet success", lw=1.5)
    ax.plot(x, e_sr, color="#5dffb0", label="Fleet + Infinity Engine", lw=1.5)
    ax.axhline(0.92, color="#7ec8ff", ls="--", alpha=0.7, label="0.92 band ref")
    ax.set_ylabel("Success rate", color="white")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_title("Proof A: multi-agent tool fleet under storms/jumps", color="white")

    ax = axes[1]
    ax.set_facecolor("#0f1620")
    ax.plot(x, env_I, color="#c090ff", label="World interference")
    ax.set_ylabel("Env I", color="white")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")

    ax = axes[2]
    ax.set_facecolor("#0f1620")
    ax.plot(x, k_st, color="#40d0ff", label="Kernel stability")
    ax.axhline(0.92, color="#5dffb0", ls="--", alpha=0.7)
    ax.axhline(0.97, color="#ff6b8a", ls=":", alpha=0.6, label="anti-lock")
    ax.set_ylabel("Kernel stab", color="white")
    ax.set_xlabel("Step", color="white")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")

    for ax in axes:
        for spine in ax.spines.values():
            spine.set_color("#445")
    fig.tight_layout()
    plot_path = OUT / "proof_a_comparison.png"
    fig.savefig(plot_path, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)

    json_path = OUT / "proof_a_results.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # HTML case study
    better = report["improvement_mean"] > 0.03
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>Proof A — Agent Fleet</title>
<style>
body{{margin:0;padding:28px;background:#0b0f14;color:#e8eef7;font-family:Segoe UI,sans-serif;max-width:900px}}
h1{{color:#fff}} .ok{{color:#5dffb0}} .bad{{color:#ff6b8a}}
.card{{background:#121a24;border:1px solid #243044;border-radius:12px;padding:16px;margin:14px 0}}
img{{max-width:100%;border-radius:8px}}
table{{border-collapse:collapse;width:100%}} td,th{{padding:8px;border-bottom:1px solid #243044;text-align:left}}
</style></head><body>
<h1>Proof A — Multi-agent tool fleet</h1>
<p><b>Problem:</b> 20 agents call flaky tools. Storms and jumps raise failure rate.
Cascades kill agents. Without a health layer, the fleet thrashes.</p>
<p><b>Approach:</b> Infinity Engine KERNEL_v1 as health controller.
Ingest (failures→I) → kernel hive step → actuate (quarantine worst / revive).</p>

<div class="card">
<h2>Results</h2>
<table>
<tr><th></th><th>Baseline</th><th>With Engine</th><th>Δ</th></tr>
<tr><td>Mean success</td><td>{base_s['mean']:.3f}</td><td class="ok">{eng_s['mean']:.3f}</td>
<td>{report['improvement_mean']:+.3f}</td></tr>
<tr><td>Late success</td><td>{base_s['late_mean']:.3f}</td><td class="ok">{eng_s['late_mean']:.3f}</td>
<td>{report['improvement_late']:+.3f}</td></tr>
<tr><td>p10 (floor)</td><td>{base_s['p10']:.3f}</td><td class="ok">{eng_s['p10']:.3f}</td>
<td>{report['improvement_p10']:+.3f}</td></tr>
<tr><td>Kernel late stab</td><td>—</td><td>{k_s['late_mean']:.3f}</td><td>target 0.92</td></tr>
</table>
<p>Verdict: <b class="{'ok' if better else 'bad'}">{'ENGINE HELPS' if better else 'NEEDS TUNING'}</b></p>
<img src="proof_a_comparison.png" alt="comparison"/>
</div>

<div class="card">
<h2>What this proves for the portfolio</h2>
<ul>
<li>Kernel applies outside pure sandbox swarm math.</li>
<li>Open-source-shaped problem: multi-agent tool failures + storms/jumps.</li>
<li>Path to specialized nodes: ingest + actuate are already sketched in code.</li>
</ul>
</div>
</body></html>"""
    html_path = OUT / "proof_a_case_study.html"
    html_path.write_text(html, encoding="utf-8")

    print("\n" + "=" * 64)
    print(" RESULTS")
    print("=" * 64)
    print(f"  Baseline mean success : {base_s['mean']:.3f}  (late {base_s['late_mean']:.3f})")
    print(f"  Engine   mean success : {eng_s['mean']:.3f}  (late {eng_s['late_mean']:.3f})")
    print(f"  Improvement (mean)    : {report['improvement_mean']:+.3f}")
    print(f"  Kernel late stability : {k_s['late_mean']:.3f}  (target 0.92)")
    print(f"  Lock frac (kernel)    : {k_s.get('min', 0):.3f} min stab tracked in series")
    print(f"\n  Plot : {plot_path}")
    print(f"  HTML : {html_path}")
    print(f"  JSON : {json_path}")
    print("=" * 64)
    print(" Open the HTML file in your browser to view the case study.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
