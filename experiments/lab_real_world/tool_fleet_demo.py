"""
Real-world demo 2 — Multi-tool agent fleet (real HTTP tools)
============================================================
Each "agent" calls a different public HTTP "tool" (httpbin endpoints).
Storms raise forced 429/500 paths. Baseline vs Soft Pack nodes.

  python real_world/tool_fleet_demo.py
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
from nodes.ingest import to_interference

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
HTTPBIN = "https://httpbin.org"

# Each agent owns a "tool" URL (real endpoints)
TOOLS = [
    f"{HTTPBIN}/get",
    f"{HTTPBIN}/uuid",
    f"{HTTPBIN}/headers",
    f"{HTTPBIN}/user-agent",
    f"{HTTPBIN}/ip",
    f"{HTTPBIN}/anything",
    f"{HTTPBIN}/json",
    f"{HTTPBIN}/encoding/utf8",
    f"{HTTPBIN}/html",
    f"{HTTPBIN}/xml",
    f"{HTTPBIN}/robots.txt",
    f"{HTTPBIN}/deny",  # often 403 — flaky tool
]


def http_ok(url: str, timeout: float = 6.0) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "InfinityEngine-ToolFleet/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def call_tool(tool_url: str, env_I: float, thrash: float, rng: np.random.Generator) -> bool:
    """Real tool call; storms inject real 429/500 endpoints."""
    if thrash > 1.3 and rng.random() < min(0.4, 0.1 * thrash):
        return http_ok(f"{HTTPBIN}/status/429")
    if env_I > 1.9 and rng.random() < 0.18:
        return http_ok(f"{HTTPBIN}/status/500")
    if env_I > 2.3 and rng.random() < 0.12:
        return http_ok(f"{HTTPBIN}/delay/2")  # slow tool — may timeout
    return http_ok(tool_url)


def run_mode(*, controlled: bool, steps: int = 18, seed: int = 21) -> dict:
    rng = np.random.default_rng(seed)
    n = len(TOOLS)
    alive = np.ones(n, dtype=bool)
    fails = np.zeros(n, dtype=int)
    recent: list[int] = []
    thrash = 1.0
    concurrency = n
    eng = HealthEngine(seed=seed + 3) if controlled else None
    stab = 0.88
    rows = []

    I = 1.0
    sch = []
    for _ in range(steps):
        if rng.random() < 0.14:
            I = float(rng.choice([0.7, 1.3, 1.9, 2.5, 2.8]))
        else:
            I = float(np.clip(I + rng.normal(0, 0.07), 0.5, 2.95))
        sch.append(I)

    label = "ENGINE" if controlled else "BASELINE"
    print(f"\n  Mode: {label}  tools={n}  steps={steps}")
    t0 = time.time()

    for t, env_I in enumerate(sch):
        if controlled and eng is not None:
            plan = plan_actions(stab, success_rate=(float(np.mean(recent[-40:])) if recent else 0.55))
            felt = apply_shield(env_I, plan)
            roll = float(np.mean(recent[-40:])) if recent else 0.55
            if roll < 0.68 or plan.cool_retries or stab < 0.90:
                thrash = max(0.5, thrash * 0.7)
                concurrency = max(3, concurrency - 1)
            if plan.quarantine_k:
                order = np.argsort(-fails)
                for i in order:
                    if alive[i] and plan.quarantine_k > 0:
                        alive[i] = False
                        plan.quarantine_k -= 1
            if plan.revive_k:
                for i in range(n):
                    if not alive[i] and plan.revive_k > 0:
                        alive[i] = True
                        fails[i] = 0
                        plan.revive_k -= 1
            if stab >= 0.91:
                thrash = min(1.2, thrash + 0.04)
                concurrency = min(n, concurrency + 1)
        else:
            felt = env_I
            thrash = min(2.4, thrash + 0.1 * (1.0 - (float(np.mean(recent[-40:])) if recent else 0.5)) + 0.04 * env_I)
            concurrency = n

        active = [i for i in range(n) if alive[i]][:concurrency]
        if not active:
            alive[0] = True
            active = [0]

        ok = fail = 0
        with ThreadPoolExecutor(max_workers=max(1, len(active) + 2)) as ex:
            futs = {ex.submit(call_tool, TOOLS[i], felt, thrash, rng): i for i in active}
            # baseline panic retries
            extra = (2 + int(thrash * 2)) if not controlled else (1 if thrash > 1.2 else 0)
            for _ in range(extra):
                i = int(rng.choice(active))
                futs[ex.submit(call_tool, TOOLS[i], felt, thrash, rng)] = -1

            for fut in as_completed(futs):
                wid = futs[fut]
                success = bool(fut.result())
                if success:
                    ok += 1
                    recent.append(1)
                    if wid >= 0:
                        fails[wid] = max(0, fails[wid] - 1)
                else:
                    fail += 1
                    recent.append(0)
                    if wid >= 0:
                        fails[wid] += 1
                        if not controlled and fails[wid] >= 4:
                            alive[wid] = False

        if len(recent) > 200:
            recent = recent[-200:]
        roll = float(np.mean(recent[-40:])) if recent else 0.5

        if controlled and eng is not None:
            I_k = to_interference(success_rate=roll, env_load=env_I, thrash=max(0, thrash - 0.7))
            out = eng.step(I_k, success_rate=roll)
            stab = float(out["stability"])
        else:
            stab = float("nan")

        rows.append(
            {
                "rolling_success": roll,
                "env_I": env_I,
                "n_alive": int(np.sum(alive)),
                "thrash": thrash,
                "kernel_stability": stab,
            }
        )
        print(
            f"    step {t+1:02d}/{steps}  roll={roll:.2f}  alive={int(np.sum(alive))}  "
            f"ok/fail={ok}/{fail}  I={env_I:.2f}"
            + (f"  stab={stab:.3f}" if controlled else "")
        )

    arr = np.array([r["rolling_success"] for r in rows], float)
    return {
        "elapsed": time.time() - t0,
        "mean": float(np.mean(arr)),
        "late": float(np.mean(arr[-max(1, len(arr) // 5) :])),
        "p10": float(np.percentile(arr, 10)),
        "final_alive": int(np.sum(alive)),
        "rows": rows,
    }


def main() -> int:
    print("=" * 64)
    print(" REAL-WORLD TOOL FLEET — multi-tool agents (httpbin tools)")
    print("=" * 64)
    print("  Checking network…")
    if not http_ok(f"{HTTPBIN}/get"):
        print("  ERROR: httpbin unreachable")
        return 1
    print("  OK")

    base = run_mode(controlled=False)
    eng = run_mode(controlled=True)
    d = eng["mean"] - base["mean"]

    print("\n" + "=" * 64)
    print(" RESULTS")
    print("=" * 64)
    print(f"  Baseline mean : {base['mean']:.3f}  late {base['late']:.3f}  alive {base['final_alive']}")
    print(f"  Engine   mean : {eng['mean']:.3f}  late {eng['late']:.3f}  alive {eng['final_alive']}")
    print(f"  Δ mean        : {d:+.3f}")
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
    ax.set_title("Real-world tool fleet (multi-endpoint HTTP tools)", color="white")
    ax.set_ylabel("Rolling success", color="white")
    ax = axes[1]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["env_I"] for r in eng["rows"]], color="#c090ff", label="Env I")
    ax.plot(x, [r["kernel_stability"] for r in eng["rows"]], color="#40d0ff", label="Kernel stab")
    ax.plot(x, [r["n_alive"] / len(TOOLS) for r in eng["rows"]], color="#ffd060", label="Alive frac")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_xlabel("Step", color="white")
    for a in axes:
        for s in a.spines.values():
            s.set_color("#445")
    fig.tight_layout()
    fig.savefig(OUT / "tool_fleet_comparison.png", dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)

    report = {
        "demo": "real_world_tool_fleet",
        "baseline": {k: base[k] for k in ("mean", "late", "p10", "final_alive", "elapsed")},
        "engine": {k: eng[k] for k in ("mean", "late", "p10", "final_alive", "elapsed")},
        "improvement_mean": d,
    }
    (OUT / "tool_fleet_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>Real-world tool fleet</title>
<style>
body{{margin:0;padding:28px;background:#0b0f14;color:#e8eef7;font-family:Segoe UI,sans-serif;max-width:900px}}
.ok{{color:#5dffb0}} .card{{background:#121a24;border:1px solid #243044;border-radius:12px;padding:16px}}
img{{max-width:100%;border-radius:8px}} table{{width:100%;border-collapse:collapse}}
td,th{{padding:8px;border-bottom:1px solid #243044;text-align:left}}
</style></head><body>
<h1>Real-world tool fleet</h1>
<p>12 agents, each with a <b>real HTTP tool</b> (httpbin endpoints). Storms inject 429/500/slow tools.
Baseline stampedes; Soft Pack nodes shield / cool / quarantine / revive.</p>
<div class="card">
<table>
<tr><th></th><th>Baseline</th><th>Engine</th><th>Δ</th></tr>
<tr><td>Mean success</td><td>{base['mean']:.3f}</td><td class="ok">{eng['mean']:.3f}</td><td>{d:+.3f}</td></tr>
<tr><td>Late success</td><td>{base['late']:.3f}</td><td class="ok">{eng['late']:.3f}</td>
<td>{eng['late']-base['late']:+.3f}</td></tr>
<tr><td>Tools alive</td><td>{base['final_alive']}</td><td class="ok">{eng['final_alive']}</td>
<td>{eng['final_alive']-base['final_alive']:+d}</td></tr>
</table>
<img src="tool_fleet_comparison.png"/>
</div>
</body></html>"""
    (OUT / "tool_fleet_case_study.html").write_text(html, encoding="utf-8")
    print(f"\n  HTML → {OUT / 'tool_fleet_case_study.html'}")
    print("=" * 64)
    return 0 if d > 0.02 else 1


if __name__ == "__main__":
    raise SystemExit(main())
