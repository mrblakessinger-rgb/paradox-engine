"""
Quota hell LIMITS probe — long recovery + honest break point
============================================================
Phase A — LONG: survive hell, then measure how high success climbs given time
Phase B — BREAK: escalate harshness until engine fails clear criteria

Target coherence LOCKED at 0.92. No DNA changes.

  python real_world/quota_hell_limits_demo.py
  python real_world/quota_hell_limits_demo.py --phase A
  python real_world/quota_hell_limits_demo.py --phase B
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
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
# Default contract; CLI --target can set 0.925 after tune validates
TARGET = 0.92


@dataclass
class SharedBudget:
    tokens: float
    max_tokens: float
    refill_base: float
    storm_penalty: float

    def try_take(self, cost: float = 1.0) -> bool:
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False

    def refill(self, env_I: float) -> None:
        amount = max(0.15, self.refill_base - self.storm_penalty * max(0.0, env_I - 0.8))
        self.tokens = min(self.max_tokens, self.tokens + amount)


def http_ok(url: str, timeout: float = 5.0) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "InfinityEngine-Limits/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def worker_attempt(
    budget: SharedBudget,
    env_I: float,
    thrash: float,
    rng: np.random.Generator,
    *,
    p429: float,
    p500: float,
    p_slow: float,
) -> bool:
    if thrash > 1.2 and rng.random() < min(0.55, p429 * thrash):
        return http_ok(f"{HTTPBIN}/status/429")
    if env_I > 1.8 and rng.random() < p500:
        return http_ok(f"{HTTPBIN}/status/500")
    if env_I > 2.2 and thrash > 1.0 and rng.random() < p_slow:
        return http_ok(f"{HTTPBIN}/delay/1")
    if not budget.try_take(1.0):
        return http_ok(f"{HTTPBIN}/status/429")
    return http_ok(f"{HTTPBIN}/get")


@dataclass
class Harshness:
    """Escalation knobs for break probe."""

    level: int
    n_workers: int
    max_tokens: float
    refill_base: float
    storm_penalty: float
    p429: float
    p500: float
    p_slow: float
    storm_len: tuple[int, int]
    stampede_extra: float
    label: str


def harshness_level(level: int) -> Harshness:
    """level 0 = hard-but-known · higher = meaner until break."""
    table = [
        Harshness(0, 16, 9.0, 2.4, 1.0, 0.10, 0.14, 0.08, (3, 6), 2.0, "hard"),
        Harshness(1, 20, 8.0, 2.2, 1.1, 0.12, 0.18, 0.10, (4, 8), 2.5, "quota_hell"),
        Harshness(2, 24, 6.0, 1.8, 1.3, 0.16, 0.22, 0.14, (5, 10), 3.2, "cruel"),
        Harshness(3, 28, 5.0, 1.4, 1.5, 0.20, 0.28, 0.18, (6, 12), 4.0, "brutal"),
        Harshness(4, 32, 4.0, 1.0, 1.7, 0.26, 0.35, 0.22, (8, 14), 5.0, "nightmare"),
        Harshness(5, 36, 3.0, 0.7, 1.9, 0.32, 0.42, 0.28, (10, 16), 6.0, "collapse"),
    ]
    return table[min(level, len(table) - 1)]


def make_schedule(steps: int, rng: np.random.Generator, h: Harshness, *, recovery_tail: int = 0) -> list[float]:
    """Hell body + optional calm recovery tail (for Phase A maximize)."""
    spaces = [0.8, 1.4, 2.0, 2.5, 2.9]
    I = 1.6
    out = []
    storm_left = 0
    body = max(0, steps - recovery_tail)
    for t in range(body):
        if storm_left > 0:
            I = float(np.clip(I + rng.normal(0.03, 0.07), 1.7, 3.0))
            storm_left -= 1
        elif rng.random() < 0.16:
            storm_left = int(rng.integers(*h.storm_len))
            I = float(rng.choice(spaces[2:]))
        elif rng.random() < 0.10:
            I = float(rng.choice(spaces))
        else:
            I = float(np.clip(I + rng.normal(0, 0.08), 0.5, 3.0))
        out.append(I)
    # recovery: drift down to mild
    I = min(I, 1.5)
    for t in range(recovery_tail):
        I = float(np.clip(0.85 + 0.15 * np.sin(t / 5) + rng.normal(0, 0.04), 0.55, 1.6))
        out.append(I)
    return out


def run_engine(
    sch: list[float],
    h: Harshness,
    *,
    seed: int,
    log_every: int = 8,
    tag: str = "",
    target: float = TARGET,
) -> dict:
    rng = np.random.default_rng(seed)
    n = h.n_workers
    budget = SharedBudget(h.max_tokens, h.max_tokens, h.refill_base, h.storm_penalty)
    alive = np.ones(n, dtype=bool)
    fails = np.zeros(n, dtype=int)
    recent: list[int] = []
    thrash = 1.1
    concurrency = n
    eng = HealthEngine(seed=seed + 7)
    stab = 0.88
    rows = []
    ok_total = fail_total = 0
    t0 = time.time()
    steps = len(sch)

    print(f"\n  [{tag}] ENGINE  level={h.level}({h.label})  workers={n}  steps={steps}  target={target}")

    for t, env_I in enumerate(sch):
        budget.refill(env_I)
        roll = float(np.mean(recent[-50:])) if recent else 0.4
        # Recovery-aware actuate (v1.1): pass env_load so calm can re-open traffic
        plan = plan_actions(stab, success_rate=roll, target=target, env_load=env_I)
        felt = apply_shield(env_I, plan)

        # Cool on thrash; re-open ONLY when budget can fund attempts (v1.2)
        # (v1.1 opened traffic into empty quota → 429 spam → worse peak)
        tokens = budget.tokens
        if plan.cool_retries or (roll < 0.40 and env_I > 1.8):
            thrash = max(0.45, thrash * 0.66)
            concurrency = max(3, concurrency - 1)
        elif plan.open_traffic and tokens >= 2.5 and env_I < 1.55:
            # Funded recovery: climb goodput without stampeding empty budget
            thrash = min(1.45, thrash + (0.08 if tokens >= 4.0 else 0.04))
            concurrency = min(n, concurrency + (2 if tokens >= 4.0 and env_I < 1.2 else 1))
        elif plan.open_traffic and tokens < 2.5:
            # Want recovery but broke — wait for refill, keep fleet, don't spam
            thrash = max(0.45, thrash * 0.92)
            concurrency = max(3, min(concurrency, max(4, int(n * 0.45))))
        elif plan.concurrency_delta < 0:
            concurrency = max(3, concurrency + plan.concurrency_delta)

        if plan.quarantine_k and roll < 0.45:
            order = np.argsort(-fails)
            k = plan.quarantine_k
            for i in order:
                if alive[i] and k > 0:
                    alive[i] = False
                    k -= 1
        if plan.revive_k:
            for i in range(n):
                if not alive[i] and plan.revive_k > 0:
                    alive[i] = True
                    fails[i] = 0
                    plan.revive_k -= 1

        active = [i for i in range(n) if alive[i]][:concurrency]
        if not active:
            # last gasp revive one
            i = int(np.argmin(fails))
            alive[i] = True
            active = [i]

        # Extra jobs only if tokens available (goodput without 429 flood)
        extra = 0
        if plan.open_traffic and tokens >= 3.5 and env_I < 1.4:
            extra = min(2, int(tokens // 2))
        elif thrash > 1.25 and tokens >= 2.0:
            extra = 1
        n_jobs = len(active) + extra
        # Cap jobs by roughly available tokens + 1 probe
        n_jobs = min(n_jobs, max(1, int(tokens) + len(active) // 2 + 1))
        jobs = [active[j % len(active)] for j in range(n_jobs)]

        ok = fail = 0
        with ThreadPoolExecutor(max_workers=min(28, max(4, len(jobs)))) as ex:
            futs = {
                ex.submit(
                    worker_attempt,
                    budget,
                    felt,
                    thrash,
                    rng,
                    p429=h.p429,
                    p500=h.p500,
                    p_slow=h.p_slow,
                ): wid
                for wid in jobs
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
                    if fails[wid] >= 14 and rng.random() < 0.2:
                        alive[wid] = False

        if len(recent) > 400:
            recent = recent[-400:]
        roll = float(np.mean(recent[-50:])) if recent else 0.35

        I_k = to_interference(success_rate=roll, env_load=env_I, thrash=max(0.0, thrash - 0.6))
        out = eng.step(I_k, success_rate=roll)
        stab = float(out["stability"])

        rows.append(
            {
                "t": t,
                "env_I": env_I,
                "rolling_success": roll,
                "n_alive": int(np.sum(alive)),
                "thrash": thrash,
                "concurrency": concurrency,
                "budget": budget.tokens,
                "kernel_stability": stab,
                "level": h.level,
            }
        )
        if (t + 1) % log_every == 0 or t == 0 or t == steps - 1:
            print(
                f"    step {t+1:03d}/{steps}  roll={roll:.2f}  alive={int(np.sum(alive))}  "
                f"I={env_I:.2f}  thrash={thrash:.2f}  stab={stab:.3f}  q={budget.tokens:.1f}"
            )

    arr = np.array([r["rolling_success"] for r in rows], float)
    stab_arr = np.array([r["kernel_stability"] for r in rows], float)
    alive_arr = np.array([r["n_alive"] for r in rows], float)
    late_n = max(1, steps // 5)
    # peak rolling success in last 40% of run (maximize with time)
    tail = arr[int(steps * 0.4) :]
    peak_tail = float(np.max(tail)) if len(tail) else float(np.max(arr))

    return {
        "elapsed": time.time() - t0,
        "mean": float(np.mean(arr)),
        "late": float(np.mean(arr[-late_n:])),
        "peak_tail": peak_tail,
        "p10": float(np.percentile(arr, 10)),
        "min_roll": float(np.min(arr)),
        "final_alive": int(alive_arr[-1]),
        "mean_alive": float(np.mean(alive_arr)),
        "min_alive": int(np.min(alive_arr)),
        "ok_total": ok_total,
        "fail_total": fail_total,
        "kernel_late": float(np.mean(stab_arr[-late_n:])),
        "kernel_mean": float(np.mean(stab_arr)),
        "kernel_min": float(np.min(stab_arr)),
        "rows": rows,
        "harshness": h.label,
        "level": h.level,
    }


def is_broken(r: dict, h: Harshness) -> tuple[bool, list[str]]:
    """Honest break criteria — any hard fail = broken at this level."""
    reasons = []
    if r["final_alive"] <= max(2, h.n_workers // 10):
        reasons.append(f"fleet_collapse final_alive={r['final_alive']}/{h.n_workers}")
    if r["mean_alive"] < h.n_workers * 0.25:
        reasons.append(f"mean_alive_too_low={r['mean_alive']:.1f}")
    if r["late"] < 0.12 and r["peak_tail"] < 0.20:
        reasons.append(f"success_floor late={r['late']:.3f} peak_tail={r['peak_tail']:.3f}")
    if r["kernel_late"] < 0.80:
        reasons.append(f"kernel_late_collapse={r['kernel_late']:.3f}")
    if r["kernel_min"] < 0.45:
        reasons.append(f"kernel_min_crash={r['kernel_min']:.3f}")
    # thrash death: almost only failures
    tot = r["ok_total"] + r["fail_total"]
    if tot > 50 and r["ok_total"] / tot < 0.08:
        reasons.append(f"ok_ratio_collapse={r['ok_total']/tot:.3f}")
    return (len(reasons) > 0, reasons)


def phase_a_long(target: float = TARGET) -> dict:
    """Long hell then recovery tail — how high can it climb with time?"""
    print("\n" + "=" * 64)
    print(" PHASE A — LONG RECOVERY (maximize with time)")
    print(f" Hell body 70 steps + calm recovery 40 steps | level=1 quota_hell | target={target}")
    print("=" * 64)
    h = harshness_level(1)
    rng = np.random.default_rng(7)
    sch = make_schedule(110, rng, h, recovery_tail=40)
    r = run_engine(sch, h, seed=11, log_every=10, tag="A-LONG", target=target)

    # Split metrics hell vs recovery
    hell = r["rows"][:70]
    rec = r["rows"][70:]
    hell_roll = [x["rolling_success"] for x in hell]
    rec_roll = [x["rolling_success"] for x in rec]
    summary = {
        "phase": "A_long_recovery",
        "target": TARGET,
        "hell_steps": 70,
        "recovery_steps": 40,
        "hell_mean": float(np.mean(hell_roll)),
        "hell_min": float(np.min(hell_roll)),
        "recovery_mean": float(np.mean(rec_roll)),
        "recovery_late": float(np.mean(rec_roll[-8:])),
        "recovery_peak": float(np.max(rec_roll)),
        "overall": {k: r[k] for k in r if k != "rows"},
        "rows": r["rows"],
    }
    print("\n  PHASE A SUMMARY")
    print(f"    Hell mean / min success : {summary['hell_mean']:.3f} / {summary['hell_min']:.3f}")
    print(f"    Recovery mean / late    : {summary['recovery_mean']:.3f} / {summary['recovery_late']:.3f}")
    print(f"    Recovery PEAK success   : {summary['recovery_peak']:.3f}  ← max climb given time")
    print(f"    Final alive             : {r['final_alive']}/{h.n_workers}")
    print(f"    Kernel late / min       : {r['kernel_late']:.3f} / {r['kernel_min']:.3f}")
    return summary


def phase_b_break(target: float = TARGET) -> dict:
    """Escalate harshness until break criteria fire."""
    print("\n" + "=" * 64)
    print(" PHASE B — BREAK LADDER (honest limits)")
    print(f" Escalate level 0→5 until broken | 36 steps each | target={target}")
    print("=" * 64)

    results = []
    break_level = None
    break_reasons: list[str] = []
    last_ok_level = None

    for level in range(0, 6):
        h = harshness_level(level)
        rng = np.random.default_rng(100 + level)
        sch = make_schedule(36, rng, h, recovery_tail=0)
        r = run_engine(sch, h, seed=200 + level, log_every=12, tag=f"B-L{level}", target=target)
        broken, reasons = is_broken(r, h)
        entry = {
            "level": level,
            "label": h.label,
            "n_workers": h.n_workers,
            "max_tokens": h.max_tokens,
            "broken": broken,
            "reasons": reasons,
            "mean": r["mean"],
            "late": r["late"],
            "peak_tail": r["peak_tail"],
            "final_alive": r["final_alive"],
            "mean_alive": r["mean_alive"],
            "kernel_late": r["kernel_late"],
            "kernel_min": r["kernel_min"],
            "ok_total": r["ok_total"],
            "fail_total": r["fail_total"],
            "elapsed": r["elapsed"],
            "rows": r["rows"],
        }
        results.append(entry)
        print(f"\n  LEVEL {level} ({h.label}): broken={broken}")
        if reasons:
            for rs in reasons:
                print(f"    · {rs}")
        else:
            print(
                f"    ok  late={r['late']:.3f}  alive={r['final_alive']}/{h.n_workers}  "
                f"k_late={r['kernel_late']:.3f}"
            )
            last_ok_level = level

        if broken and break_level is None:
            break_level = level
            break_reasons = reasons
            # continue one more level optional? stop at first break for clarity
            break

    return {
        "phase": "B_break_ladder",
        "target": TARGET,
        "last_ok_level": last_ok_level,
        "break_level": break_level,
        "break_label": harshness_level(break_level).label if break_level is not None else None,
        "break_reasons": break_reasons,
        "levels": [{k: v for k, v in e.items() if k != "rows"} for e in results],
        "level_rows": {e["level"]: e["rows"] for e in results},
    }


def plot_phase_a(summary: dict) -> Path:
    rows = summary["rows"]
    x = np.arange(len(rows))
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    fig.patch.set_facecolor("#0b0f14")
    ax = axes[0]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["rolling_success"] for r in rows], color="#5dffb0", lw=1.4)
    ax.axvline(70, color="#ffd060", ls="--", alpha=0.8, label="Hell → recovery")
    ax.axhline(summary["recovery_peak"], color="#7ec8ff", ls=":", alpha=0.7, label=f"Peak {summary['recovery_peak']:.2f}")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_ylabel("Success", color="white")
    ax.set_title("Phase A: long hell then recovery (maximize with time)", color="white")
    ax = axes[1]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["env_I"] for r in rows], color="#c090ff", label="Env I")
    ax.plot(x, [r["kernel_stability"] for r in rows], color="#40d0ff", label="Kernel")
    ax.axhline(TARGET, color="#7ec8ff", ls="--", alpha=0.6)
    ax.axvline(70, color="#ffd060", ls="--", alpha=0.8)
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_xlabel("Step", color="white")
    for a in axes:
        for s in a.spines.values():
            s.set_color("#445")
    fig.tight_layout()
    path = OUT / "limits_phase_a.png"
    fig.savefig(path, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


def plot_phase_b(summary: dict) -> Path:
    levels = summary["levels"]
    fig, axes = plt.subplots(2, 1, figsize=(11, 6))
    fig.patch.set_facecolor("#0b0f14")
    xs = [e["level"] for e in levels]
    ax = axes[0]
    ax.set_facecolor("#0f1620")
    ax.plot(xs, [e["late"] for e in levels], "o-", color="#5dffb0", label="Late success")
    ax.plot(xs, [e["mean_alive"] / harshness_level(e["level"]).n_workers for e in levels], "s-", color="#ffd060", label="Mean alive frac")
    if summary["break_level"] is not None:
        ax.axvline(summary["break_level"], color="#ff6b8a", ls="--", label=f"Break L{summary['break_level']}")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_ylabel("Metric", color="white")
    ax.set_title("Phase B: break ladder", color="white")
    ax = axes[1]
    ax.set_facecolor("#0f1620")
    ax.plot(xs, [e["kernel_late"] for e in levels], "o-", color="#40d0ff", label="Kernel late")
    ax.axhline(TARGET, color="#7ec8ff", ls="--", alpha=0.6, label="Target 0.92")
    ax.axhline(0.80, color="#ff9b6b", ls=":", alpha=0.7, label="Break line 0.80")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_xlabel("Harshness level", color="white")
    ax.set_ylabel("Kernel", color="white")
    for a in axes:
        for s in a.spines.values():
            s.set_color("#445")
    fig.tight_layout()
    path = OUT / "limits_phase_b.png"
    fig.savefig(path, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


def write_html(phase_a: dict | None, phase_b: dict | None) -> Path:
    parts = [
        """<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Quota Hell Limits</title>
<style>
body{margin:0;padding:28px;background:#0b0f14;color:#e8eef7;font-family:Segoe UI,sans-serif;max-width:940px}
.ok{color:#5dffb0} .bad{color:#ff6b8a} .card{background:#121a24;border:1px solid #243044;border-radius:12px;padding:16px;margin:14px 0}
img{max-width:100%;border-radius:8px} table{width:100%;border-collapse:collapse}
td,th{padding:8px;border-bottom:1px solid #243044;text-align:left}
</style></head><body>
<h1>Limits probe — long climb + break point</h1>
<p>Target coherence <b>locked at 0.92</b>. Honest limits, not a sales polish pass.</p>
"""
    ]
    if phase_a:
        parts.append(
            f"""
<div class="card">
<h2>Phase A — maximize with time</h2>
<table>
<tr><td>Hell mean / min</td><td>{phase_a['hell_mean']:.3f} / {phase_a['hell_min']:.3f}</td></tr>
<tr><td>Recovery mean / late</td><td class="ok">{phase_a['recovery_mean']:.3f} / {phase_a['recovery_late']:.3f}</td></tr>
<tr><td><b>Recovery peak</b></td><td class="ok"><b>{phase_a['recovery_peak']:.3f}</b></td></tr>
<tr><td>Final alive</td><td>{phase_a['overall']['final_alive']}</td></tr>
<tr><td>Kernel late / min</td><td>{phase_a['overall']['kernel_late']:.3f} / {phase_a['overall']['kernel_min']:.3f}</td></tr>
</table>
<img src="limits_phase_a.png"/>
</div>
"""
        )
    if phase_b:
        br = phase_b.get("break_level")
        br_s = f"L{br} ({phase_b.get('break_label')})" if br is not None else "did not break in ladder"
        parts.append(
            f"""
<div class="card">
<h2>Phase B — break ladder</h2>
<p>Last OK level: <b class="ok">{phase_b.get('last_ok_level')}</b> · First break: <b class="bad">{br_s}</b></p>
<ul>
"""
        )
        for rs in phase_b.get("break_reasons") or []:
            parts.append(f"<li class='bad'>{rs}</li>")
        if not phase_b.get("break_reasons"):
            parts.append("<li>No break criteria fired in levels 0–5</li>")
        parts.append("</ul><table><tr><th>L</th><th>Label</th><th>Late</th><th>Alive</th><th>K late</th><th>Broken?</th></tr>")
        for e in phase_b["levels"]:
            cls = "bad" if e["broken"] else "ok"
            parts.append(
                f"<tr><td>{e['level']}</td><td>{e['label']}</td><td>{e['late']:.3f}</td>"
                f"<td>{e['final_alive']}/{e['n_workers']}</td><td>{e['kernel_late']:.3f}</td>"
                f"<td class='{cls}'>{e['broken']}</td></tr>"
            )
        parts.append('</table><img src="limits_phase_b.png"/></div>')

        # external improvement hints
        parts.append(
            """
<div class="card">
<h2>Where external improvements help</h2>
<ul>
<li><b>Quota / budget layer</b> — fairer refill, priority tokens for healthy workers</li>
<li><b>Smarter actuate</b> — adaptive cool vs goodput (don't under-request when calm returns)</li>
<li><b>Per-worker backoff</b> — jittered 429 respect before fleet-level cool</li>
<li><b>Ingest thrash signal</b> — stronger thrash weight when queue of 429s spikes</li>
<li><b>Graduated revive</b> — revive slower after deep storms to avoid re-stampede</li>
</ul>
</div>
"""
        )
    parts.append("</body></html>")
    path = OUT / "limits_case_study.html"
    path.write_text("".join(parts), encoding="utf-8")
    return path


def main() -> int:
    global TARGET
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["A", "B", "both"], default="both")
    ap.add_argument("--target", type=float, default=None, help="Actuate target (default 0.92)")
    args = ap.parse_args()
    target = float(args.target) if args.target is not None else TARGET
    TARGET = target

    print("=" * 64)
    print(" QUOTA HELL LIMITS — long climb + break point")
    print(f" Target = {target}  |  recovery-tuned actuate v1.1")
    print("=" * 64)
    print("  Probe httpbin…")
    if not http_ok(f"{HTTPBIN}/get", timeout=10):
        print("  ERROR: httpbin unreachable")
        return 1
    print("  OK")

    phase_a = phase_b = None
    if args.phase in ("A", "both"):
        phase_a = phase_a_long(target=target)
        plot_phase_a(phase_a)
    if args.phase in ("B", "both"):
        phase_b = phase_b_break(target=target)
        plot_phase_b(phase_b)

    # strip rows for json size
    out = {"target": target, "tune": "recovery_v1.1", "phase_a": None, "phase_b": None}
    if phase_a:
        out["phase_a"] = {k: v for k, v in phase_a.items() if k != "rows"}
        out["phase_a"]["overall"] = phase_a["overall"]
    if phase_b:
        out["phase_b"] = {k: v for k, v in phase_b.items() if k != "level_rows"}

    (OUT / "limits_results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    html = write_html(phase_a, phase_b)
    print(f"\n  HTML → {html}")
    print(f"  JSON → {OUT / 'limits_results.json'}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
