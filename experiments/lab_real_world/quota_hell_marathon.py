"""
Quota hell MARATHON — longer hell + episode adaptation + find hard break
=======================================================================
Hold actuate target at 0.925.

IMPORTANT:
  KERNEL DNA is FROZEN (no cross-run learning).
  This run uses *episode adaptation* — within-run scars that adjust cool /
  open thresholds as the episode progresses. You will see policy change
  over steps. That is intentional "watch it adapt", not DNA training.

Phases:
  H1  90 steps  L1 quota_hell
  H2  90 steps  L2 cruel
  H3  72 steps  L3 brutal
  H4  60 steps  L4 nightmare   (hunt fleet death / hard break)
  R   40 steps  recovery after whatever remains

  python real_world/quota_hell_marathon.py
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
TARGET = 0.925  # held per request


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
        amount = max(0.12, self.refill_base - self.storm_penalty * max(0.0, env_I - 0.8))
        self.tokens = min(self.max_tokens, self.tokens + amount)


@dataclass
class Harshness:
    level: int
    n_workers: int
    max_tokens: float
    refill_base: float
    storm_penalty: float
    p429: float
    p500: float
    p_slow: float
    storm_len: tuple[int, int]
    label: str


def harsh(level: int) -> Harshness:
    table = [
        Harshness(0, 16, 9.0, 2.4, 1.0, 0.10, 0.14, 0.08, (3, 6), "hard"),
        Harshness(1, 20, 8.0, 2.2, 1.1, 0.12, 0.18, 0.10, (4, 8), "quota_hell"),
        Harshness(2, 24, 6.0, 1.8, 1.3, 0.16, 0.22, 0.14, (5, 10), "cruel"),
        Harshness(3, 28, 5.0, 1.4, 1.5, 0.20, 0.28, 0.18, (6, 12), "brutal"),
        Harshness(4, 32, 4.0, 1.0, 1.7, 0.26, 0.35, 0.22, (8, 14), "nightmare"),
        Harshness(5, 36, 3.0, 0.7, 1.9, 0.32, 0.42, 0.28, (10, 16), "collapse"),
    ]
    return table[min(level, len(table) - 1)]


@dataclass
class EpisodeAdapter:
    """
    Within-run scars only. Resets every marathon. Not written to DNA.
    Adjusts cool strength and open thresholds from recent outcomes.
    """

    cool_gain: float = 0.66
    open_tokens: float = 2.5
    max_extra_jobs: int = 2
    window: list[float] = field(default_factory=list)
    scars: list[dict] = field(default_factory=list)
    adapt_every: int = 12

    def observe(self, roll: float, alive_frac: float, env_I: float, t: int) -> None:
        self.window.append(roll)
        if len(self.window) > self.adapt_every:
            self.window = self.window[-self.adapt_every :]
        if (t + 1) % self.adapt_every != 0 or len(self.window) < self.adapt_every:
            return
        mean_w = float(np.mean(self.window))
        prev = dict(cool_gain=self.cool_gain, open_tokens=self.open_tokens, max_extra=self.max_extra_jobs)

        if mean_w < 0.12 and env_I > 1.7:
            # deep hell floor — cool harder, open only with more tokens
            self.cool_gain = float(np.clip(self.cool_gain * 0.92, 0.50, 0.75))
            self.open_tokens = float(np.clip(self.open_tokens + 0.35, 2.0, 5.0))
            self.max_extra_jobs = max(0, self.max_extra_jobs - 1)
            reason = "deep_floor_tighten"
        elif mean_w < 0.25 and env_I > 1.5:
            self.cool_gain = float(np.clip(self.cool_gain * 0.96, 0.50, 0.75))
            self.open_tokens = float(np.clip(self.open_tokens + 0.15, 2.0, 5.0))
            reason = "low_success_tighten"
        elif mean_w > 0.45 and env_I < 1.6 and alive_frac > 0.8:
            # climbing — allow slightly more reopen
            self.cool_gain = float(np.clip(self.cool_gain * 1.02, 0.50, 0.75))
            self.open_tokens = float(np.clip(self.open_tokens - 0.2, 2.0, 5.0))
            self.max_extra_jobs = min(3, self.max_extra_jobs + 1)
            reason = "climb_loosen"
        elif mean_w > 0.35 and env_I < 1.3:
            self.open_tokens = float(np.clip(self.open_tokens - 0.1, 2.0, 5.0))
            self.max_extra_jobs = min(3, self.max_extra_jobs + 1)
            reason = "calm_open"
        else:
            reason = "hold"

        if reason != "hold":
            self.scars.append(
                {
                    "t": t,
                    "reason": reason,
                    "mean_w": mean_w,
                    "before": prev,
                    "after": {
                        "cool_gain": self.cool_gain,
                        "open_tokens": self.open_tokens,
                        "max_extra": self.max_extra_jobs,
                    },
                }
            )
            print(
                f"    · ADAPT t={t+1} {reason}  cool_gain={self.cool_gain:.3f}  "
                f"open_tok={self.open_tokens:.2f}  extra={self.max_extra_jobs}  "
                f"(window_mean={mean_w:.3f})"
            )


def http_ok(url: str, timeout: float = 5.0) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "InfinityEngine-Marathon/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def worker_attempt(budget: SharedBudget, env_I: float, thrash: float, rng: np.random.Generator, h: Harshness) -> bool:
    if thrash > 1.2 and rng.random() < min(0.55, h.p429 * thrash):
        return http_ok(f"{HTTPBIN}/status/429")
    if env_I > 1.8 and rng.random() < h.p500:
        return http_ok(f"{HTTPBIN}/status/500")
    if env_I > 2.2 and thrash > 1.0 and rng.random() < h.p_slow:
        return http_ok(f"{HTTPBIN}/delay/1")
    if not budget.try_take(1.0):
        return http_ok(f"{HTTPBIN}/status/429")
    return http_ok(f"{HTTPBIN}/get")


def hell_schedule(steps: int, rng: np.random.Generator, h: Harshness) -> list[float]:
    spaces = [1.0, 1.5, 2.0, 2.5, 2.95]
    I = 1.8
    out = []
    storm_left = 0
    for _ in range(steps):
        if storm_left > 0:
            I = float(np.clip(I + rng.normal(0.04, 0.06), 1.75, 3.0))
            storm_left -= 1
        elif rng.random() < 0.18:
            storm_left = int(rng.integers(*h.storm_len))
            I = float(rng.choice(spaces[2:]))
        elif rng.random() < 0.08:
            I = float(rng.choice(spaces))
        else:
            I = float(np.clip(I + rng.normal(0, 0.07), 1.2, 3.0))
        out.append(I)
    return out


def recovery_schedule(steps: int, rng: np.random.Generator) -> list[float]:
    out = []
    I = 1.2
    for t in range(steps):
        I = float(np.clip(0.8 + 0.2 * np.sin(t / 6) + rng.normal(0, 0.05), 0.5, 1.5))
        out.append(I)
    return out


def run_segment(
    sch: list[float],
    h: Harshness,
    *,
    eng: HealthEngine,
    adapter: EpisodeAdapter,
    state: dict,
    seed: int,
    tag: str,
    global_t0: int,
) -> dict:
    """Continue engine state across segments (same swarm memory via eng + adapter)."""
    rng = np.random.default_rng(seed)
    n = h.n_workers
    # resize alive/fails if worker count changes
    alive: np.ndarray = state["alive"]
    fails: np.ndarray = state["fails"]
    if len(alive) < n:
        alive = np.concatenate([alive, np.ones(n - len(alive), dtype=bool)])
        fails = np.concatenate([fails, np.zeros(n - len(fails), dtype=int)])
    elif len(alive) > n:
        # keep best n workers
        order = np.argsort(fails)[:n]
        alive = alive[order]
        fails = fails[order]
    state["alive"] = alive
    state["fails"] = fails

    budget = SharedBudget(h.max_tokens * 0.9, h.max_tokens, h.refill_base, h.storm_penalty)
    thrash = state.get("thrash", 1.0)
    concurrency = min(n, state.get("concurrency", n))
    recent: list[int] = state.get("recent", [])
    stab = state.get("stab", 0.88)
    rows = []
    ok_total = fail_total = 0
    soft_break_t = None
    hard_break_t = None
    t0 = time.time()

    print(f"\n  [{tag}] L{h.level}/{h.label}  workers={n}  steps={len(sch)}  target={TARGET}")
    print(f"         adapter cool_gain={adapter.cool_gain:.3f} open_tok={adapter.open_tokens:.2f}")

    for i, env_I in enumerate(sch):
        t = global_t0 + i
        budget.refill(env_I)
        roll = float(np.mean(recent[-50:])) if recent else 0.4
        plan = plan_actions(stab, success_rate=roll, target=TARGET, env_load=env_I)
        felt = apply_shield(env_I, plan)
        tokens = budget.tokens

        # Apply adapter-tuned cool / open
        if plan.cool_retries or (roll < 0.40 and env_I > 1.8):
            thrash = max(0.42, thrash * adapter.cool_gain)
            concurrency = max(3, concurrency - 1)
        elif plan.open_traffic and tokens >= adapter.open_tokens and env_I < 1.55:
            thrash = min(1.5, thrash + (0.08 if tokens >= 4 else 0.04))
            concurrency = min(n, concurrency + (2 if tokens >= 4 and env_I < 1.2 else 1))
        elif plan.open_traffic and tokens < adapter.open_tokens:
            thrash = max(0.42, thrash * 0.93)
            concurrency = max(3, min(concurrency, max(4, int(n * 0.5))))

        if plan.quarantine_k and roll < 0.42:
            order = np.argsort(-fails)
            k = plan.quarantine_k
            for j in order:
                if j < n and alive[j] and k > 0:
                    alive[j] = False
                    k -= 1
        if plan.revive_k:
            for j in range(n):
                if not alive[j] and plan.revive_k > 0:
                    alive[j] = True
                    fails[j] = 0
                    plan.revive_k -= 1

        active = [j for j in range(n) if alive[j]][:concurrency]
        if not active:
            j = int(np.argmin(fails[:n]))
            alive[j] = True
            active = [j]

        extra = 0
        if plan.open_traffic and tokens >= adapter.open_tokens + 1.0 and env_I < 1.4:
            extra = min(adapter.max_extra_jobs, int(tokens // 2))
        n_jobs = min(len(active) + extra, max(1, int(tokens) + len(active) // 2 + 1))
        jobs = [active[j % len(active)] for j in range(n_jobs)]

        ok = fail = 0
        with ThreadPoolExecutor(max_workers=min(32, max(4, len(jobs)))) as ex:
            futs = {ex.submit(worker_attempt, budget, felt, thrash, rng, h): wid for wid in jobs}
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
                    if fails[wid] >= 16 and rng.random() < 0.25:
                        alive[wid] = False

        if len(recent) > 400:
            recent = recent[-400:]
        roll = float(np.mean(recent[-50:])) if recent else 0.3
        n_alive = int(np.sum(alive[:n]))
        alive_frac = n_alive / n

        I_k = to_interference(success_rate=roll, env_load=env_I, thrash=max(0.0, thrash - 0.55))
        out = eng.step(I_k, success_rate=roll)
        stab = float(out["stability"])

        adapter.observe(roll, alive_frac, env_I, t)

        # Break markers
        if soft_break_t is None and roll < 0.12 and i > 8:
            soft_break_t = i
        if hard_break_t is None and n_alive <= max(2, n // 10):
            hard_break_t = i

        rows.append(
            {
                "t": t,
                "seg_t": i,
                "level": h.level,
                "label": h.label,
                "env_I": env_I,
                "rolling_success": roll,
                "n_alive": n_alive,
                "alive_frac": alive_frac,
                "thrash": thrash,
                "concurrency": concurrency,
                "budget": tokens,
                "kernel_stability": stab,
                "cool_gain": adapter.cool_gain,
                "open_tokens": adapter.open_tokens,
                "plan_note": plan.note,
            }
        )
        if (i + 1) % 15 == 0 or i == 0 or i == len(sch) - 1:
            print(
                f"    step {i+1:03d}/{len(sch)}  roll={roll:.2f}  alive={n_alive}/{n}  "
                f"I={env_I:.2f}  thrash={thrash:.2f}  stab={stab:.3f}  q={tokens:.1f}"
            )

    state["alive"] = alive
    state["fails"] = fails
    state["thrash"] = thrash
    state["concurrency"] = concurrency
    state["recent"] = recent
    state["stab"] = stab

    arr = np.array([r["rolling_success"] for r in rows], float)
    return {
        "tag": tag,
        "level": h.level,
        "label": h.label,
        "n_workers": n,
        "steps": len(sch),
        "elapsed": time.time() - t0,
        "mean": float(np.mean(arr)),
        "late": float(np.mean(arr[-max(1, len(arr) // 5) :])),
        "peak": float(np.max(arr)),
        "min_roll": float(np.min(arr)),
        "final_alive": int(np.sum(alive[:n])),
        "mean_alive": float(np.mean([r["n_alive"] for r in rows])),
        "min_alive": int(np.min([r["n_alive"] for r in rows])),
        "ok_total": ok_total,
        "fail_total": fail_total,
        "kernel_late": float(np.mean([r["kernel_stability"] for r in rows[-max(1, len(rows) // 5) :]])),
        "kernel_min": float(np.min([r["kernel_stability"] for r in rows])),
        "soft_break_step": soft_break_t,
        "hard_break_step": hard_break_t,
        "rows": rows,
    }


def main() -> int:
    print("=" * 64)
    print(" QUOTA HELL MARATHON")
    print(f" Actuate target HELD at {TARGET}")
    print(" DNA: FROZEN  |  Episode adaptation: ON (within-run scars)")
    print("=" * 64)
    print("  Probe httpbin…")
    if not http_ok(f"{HTTPBIN}/get", timeout=10):
        print("  ERROR: httpbin unreachable")
        return 1
    print("  OK")

    eng = HealthEngine(seed=925)
    adapter = EpisodeAdapter()
    # start with max workers we'll need
    n_max = 32
    state = {
        "alive": np.ones(n_max, dtype=bool),
        "fails": np.zeros(n_max, dtype=int),
        "thrash": 1.05,
        "concurrency": 20,
        "recent": [],
        "stab": 0.88,
    }

    plan = [
        (1, 90, "H1-quota_hell"),
        (2, 90, "H2-cruel"),
        (3, 72, "H3-brutal"),
        (4, 60, "H4-nightmare"),
    ]
    segments = []
    t_cursor = 0
    all_rows = []
    first_soft = None
    first_hard = None

    for level, steps, tag in plan:
        h = harsh(level)
        rng = np.random.default_rng(1000 + level)
        sch = hell_schedule(steps, rng, h)
        seg = run_segment(
            sch, h, eng=eng, adapter=adapter, state=state, seed=2000 + level, tag=tag, global_t0=t_cursor
        )
        segments.append({k: v for k, v in seg.items() if k != "rows"})
        all_rows.extend(seg["rows"])
        if first_soft is None and seg["soft_break_step"] is not None:
            first_soft = (tag, seg["soft_break_step"], h.label)
        if first_hard is None and seg["hard_break_step"] is not None:
            first_hard = (tag, seg["hard_break_step"], h.label)
            print(f"\n  *** HARD BREAK (fleet death threshold) in {tag} at seg step {seg['hard_break_step']}")
            # still continue? user wants to see limits — stop hell climb after hard break
            break
        t_cursor += steps
        print(
            f"  SEG DONE {tag}: mean={seg['mean']:.3f} late={seg['late']:.3f} "
            f"peak={seg['peak']:.3f} alive={seg['final_alive']}/{seg['n_workers']} "
            f"k_late={seg['kernel_late']:.3f}"
        )

    # Recovery if anyone left
    print("\n  [R] recovery tail 40 steps…")
    h_r = harsh(1)
    sch_r = recovery_schedule(40, np.random.default_rng(77))
    seg_r = run_segment(
        sch_r, h_r, eng=eng, adapter=adapter, state=state, seed=3000, tag="R-recover", global_t0=t_cursor
    )
    segments.append({k: v for k, v in seg_r.items() if k != "rows"})
    all_rows.extend(seg_r["rows"])

    # Plots
    x = np.arange(len(all_rows))
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    fig.patch.set_facecolor("#0b0f14")
    ax = axes[0]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["rolling_success"] for r in all_rows], color="#5dffb0", lw=1.2)
    ax.set_ylabel("Success", color="white")
    ax.set_title(f"Marathon hell (target={TARGET}, episode adapt ON, DNA frozen)", color="white")
    ax.tick_params(colors="white")
    # segment boundaries
    acc = 0
    for s in segments[:-1]:
        acc += s["steps"]
        ax.axvline(acc, color="#ffd060", ls="--", alpha=0.5)

    ax = axes[1]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["n_alive"] for r in all_rows], color="#ffd060", label="alive")
    ax.plot(x, [r["kernel_stability"] for r in all_rows], color="#40d0ff", label="kernel")
    ax.axhline(TARGET, color="#7ec8ff", ls="--", alpha=0.6)
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_ylabel("Alive / stab", color="white")

    ax = axes[2]
    ax.set_facecolor("#0f1620")
    ax.plot(x, [r["cool_gain"] for r in all_rows], color="#c090ff", label="cool_gain (adapt)")
    ax.plot(x, [r["open_tokens"] for r in all_rows], color="#ff6b8a", label="open_tokens (adapt)")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_xlabel("Global step", color="white")
    ax.set_ylabel("Adapter", color="white")
    for a in axes:
        for s in a.spines.values():
            s.set_color("#445")
    fig.tight_layout()
    fig.savefig(OUT / "marathon_comparison.png", dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)

    report = {
        "demo": "quota_hell_marathon",
        "target": TARGET,
        "dna": "FROZEN",
        "episode_adaptation": True,
        "adapter_final": {
            "cool_gain": adapter.cool_gain,
            "open_tokens": adapter.open_tokens,
            "max_extra_jobs": adapter.max_extra_jobs,
        },
        "scars": adapter.scars,
        "segments": segments,
        "first_soft_break": first_soft,
        "first_hard_break": first_hard,
        "recovery_peak": seg_r["peak"],
        "recovery_late": seg_r["late"],
        "final_alive": seg_r["final_alive"],
    }
    (OUT / "marathon_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    # HTML
    scar_rows = "".join(
        f"<tr><td>{s['t']}</td><td>{s['reason']}</td><td>{s['mean_w']:.3f}</td>"
        f"<td>{s['after']['cool_gain']:.3f}</td><td>{s['after']['open_tokens']:.2f}</td></tr>"
        for s in adapter.scars
    )
    seg_rows = "".join(
        f"<tr><td>{s['tag']}</td><td>{s['label']}</td><td>{s['mean']:.3f}</td>"
        f"<td>{s['late']:.3f}</td><td>{s['peak']:.3f}</td>"
        f"<td>{s['final_alive']}/{s['n_workers']}</td><td>{s['min_alive']}</td>"
        f"<td>{s['kernel_late']:.3f}</td></tr>"
        for s in segments
    )
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>Quota Hell Marathon</title>
<style>
body{{margin:0;padding:28px;background:#0b0f14;color:#e8eef7;font-family:Segoe UI,sans-serif;max-width:960px}}
.ok{{color:#5dffb0}} .bad{{color:#ff6b8a}} .card{{background:#121a24;border:1px solid #243044;border-radius:12px;padding:16px;margin:12px 0}}
img{{max-width:100%;border-radius:8px}} table{{width:100%;border-collapse:collapse;font-size:.9rem}}
td,th{{padding:8px;border-bottom:1px solid #243044;text-align:left}}
</style></head><body>
<h1>Marathon hell — target {TARGET}</h1>
<p><b>DNA:</b> frozen · <b>Episode adaptation:</b> on (within-run scars) · Nobody has to die for a soft break.</p>
<div class="card">
<p>First <b class="bad">soft break</b> (success floor): {first_soft}</p>
<p>First <b class="bad">hard break</b> (fleet death threshold): {first_hard or "NONE — fleet never collapsed"}</p>
<p>Recovery peak / late: <span class="ok">{seg_r['peak']:.3f} / {seg_r['late']:.3f}</span> · final alive {seg_r['final_alive']}</p>
</div>
<div class="card">
<h2>Segments</h2>
<table>
<tr><th>Tag</th><th>Label</th><th>Mean</th><th>Late</th><th>Peak</th><th>Alive end</th><th>Min alive</th><th>K late</th></tr>
{seg_rows}
</table>
</div>
<div class="card">
<h2>Episode adapts (scars)</h2>
<table>
<tr><th>t</th><th>reason</th><th>window mean</th><th>cool_gain</th><th>open_tokens</th></tr>
{scar_rows if scar_rows else "<tr><td colspan=5>no adapts logged</td></tr>"}
</table>
</div>
<img src="marathon_comparison.png"/>
</body></html>"""
    (OUT / "marathon_case_study.html").write_text(html, encoding="utf-8")

    print("\n" + "=" * 64)
    print(" MARATHON SUMMARY")
    print("=" * 64)
    print(f"  Target              : {TARGET}")
    print(f"  DNA                 : FROZEN")
    print(f"  Episode adapts      : {len(adapter.scars)} scars")
    print(f"  First soft break    : {first_soft}")
    print(f"  First hard break    : {first_hard or 'NONE (fleet never died)'}")
    print(f"  Recovery peak/late  : {seg_r['peak']:.3f} / {seg_r['late']:.3f}")
    print(f"  Final adapter       : cool={adapter.cool_gain:.3f} open_tok={adapter.open_tokens:.2f}")
    for s in segments:
        print(
            f"  {s['tag']:16s}  late={s['late']:.3f}  peak={s['peak']:.3f}  "
            f"alive={s['final_alive']}/{s['n_workers']} (min {s['min_alive']})"
        )
    print(f"\n  HTML → {OUT / 'marathon_case_study.html'}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
