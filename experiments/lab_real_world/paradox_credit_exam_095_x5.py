"""
Desire 0.95 — 5 exam runs × 5 adaptation cycles each
====================================================
Includes recovery_drive (faster post-surge climb). Between exams: assess + adapt.

  python real_world/paradox_credit_exam_095_x5.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodes.actuate import apply_shield
from nodes.engine_loop import HealthEngine
from paradox_credit_exam import World, apply_plan, bright_week, tough_week, STEPS_DAY, DAYS

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

TARGET = 0.95
N_EXAMS = 5
CYCLES_PER_EXAM = 5  # adaptation cycles before each exam measurement
EXAM_SEEDS = [7, 11, 21, 29, 42]


def inject_surprise(env, bud, empty, strength: float = 1.0):
    """
    Saturday surge; strength scales toughness (adapted between exams).

    Also injects *leading signs* 3h before peak (queue-like empty↑, budget soft,
    mild env climb) so HorizonScout can pre-arm — not a cliff from calm to hell.
    """
    env, bud, empty = list(env), list(bud), list(empty)
    flags = [False] * len(env)
    # optional upstream schedules (parallel to env) for horizon
    queue = [0.05] * len(env)
    arrival = [1.0] * len(env)
    for d in range(7):
        for h in range(STEPS_DAY):
            t = d * STEPS_DAY + h
            if d == 5 and 7 <= h <= 9:
                # leading signs: ramp *before* the surge window
                ramp = (h - 6) / 3.0  # ~0.33..1.0
                env[t] = float(np.clip(env[t] + 0.25 * ramp * strength, 0.5, 1.85))
                bud[t] = float(np.clip(bud[t] - 0.08 * ramp * strength, 0.40, 1.0))
                empty[t] = float(np.clip(empty[t] + 0.04 * ramp * strength, 0.0, 0.22))
                queue[t] = float(np.clip(0.25 + 0.35 * ramp * strength, 0.1, 0.85))
                arrival[t] = float(np.clip(1.05 + 0.35 * ramp * strength, 1.0, 1.6))
            if d == 5 and 10 <= h <= 16:
                env[t] = float(np.clip(2.2 + 0.35 * strength, 1.8, 2.7))
                bud[t] = float(np.clip(0.55 - 0.15 * strength, 0.35, 0.7))
                empty[t] = float(np.clip(0.08 + 0.08 * strength, 0.05, 0.25))
                queue[t] = float(np.clip(0.55 + 0.2 * strength, 0.4, 0.95))
                arrival[t] = float(np.clip(1.4 + 0.25 * strength, 1.2, 1.9))
                flags[t] = True
    return env, bud, empty, flags, queue, arrival


def run_week(
    eng: HealthEngine,
    seed: int,
    env,
    bud,
    empty,
    flags,
    lr: float,
    learn: bool,
    queue=None,
    arrival=None,
):
    eng.credit.lr_scale = lr
    eng.credit_loop = True
    eng.target = TARGET
    eng.paradox.intuition["target_coherence"] = TARGET
    w = World(rng=np.random.default_rng(seed + 3))
    gps, alives, stabs = [], [], []
    errs, regrets = [], []
    storm_s, damp_s, damp_c = [], [], []
    recovery_flags = []
    pre_arm_all = []
    risk_all = []
    storm_all = []

    for t in range(len(env)):
        w.budget_mul, w.tool_empty = bud[t], empty[t]
        kw = {}
        if queue is not None:
            kw["queue_pressure"] = float(queue[t])
        if arrival is not None:
            kw["arrival_rate"] = float(arrival[t])
        out = eng.step_from_metrics(
            success_rate=w.rs(),
            env_load=env[t],
            thrash=w.retries + w.rempty(),
            goodput=w.rgp(),
            budget_remaining=bud[t],
            empty_tool_rate=w.rempty(),
            **kw,
        )
        felt = apply_shield(env[t], out["plan"])
        m = w.step(felt)
        apply_plan(w, out["plan"])
        obs = eng.observe_actual(
            goodput=m["gp"], alive_frac=m["alive_frac"], stability=out["stability"]
        )
        gps.append(m["gp"])
        alives.append(m["alive"])
        stabs.append(out["stability"])
        recovery_flags.append(1.0 if out.get("recovery_active") else 0.0)
        pre_arm_all.append(1.0 if out.get("pre_arm") or out.get("storm_active") else 0.0)
        risk_all.append(float(out.get("surge_risk") or 0.0))
        storm_all.append(1.0 if out["storm_active"] else 0.0)
        if flags and flags[t]:
            storm_s.append(1.0 if out["storm_active"] else 0.0)
            damp_s.append(out["damper_live"])
        elif flags and not flags[t] and not out.get("weekly_drill"):
            damp_c.append(out["damper_live"])
        if obs:
            errs.append(obs["err_gp"])
            regrets.append(obs["regret"])

    if learn:
        eng.end_episode_credit()

    gp, al, st = np.array(gps), np.array(alives, float), np.array(stabs)
    idx = [i for i, f in enumerate(flags or []) if f]
    # recovery window: steps right after last surge flag
    if idx:
        last_s = max(idx)
        first_s = min(idx)
        rec_i = list(range(last_s + 1, min(len(al), last_s + 13)))
        post_alive = float(np.mean(al[rec_i])) if rec_i else None
        post_gp = float(np.mean(gp[rec_i])) if rec_i else None
        rec_frac = float(np.mean([recovery_flags[i] for i in rec_i])) if rec_i else 0.0
        lead_i = list(range(max(0, first_s - 3), first_s))
        pre_arm_lead = float(np.mean([pre_arm_all[i] for i in lead_i])) if lead_i else 0.0
        risk_lead = float(np.mean([risk_all[i] for i in lead_i])) if lead_i else 0.0
        storm_lead = float(np.mean([storm_all[i] for i in lead_i])) if lead_i else 0.0
    else:
        post_alive = post_gp = None
        rec_frac = float(np.mean(recovery_flags)) if recovery_flags else 0.0
        pre_arm_lead = risk_lead = storm_lead = 0.0
    return {
        "gp_mean": float(np.mean(gp)),
        "gp_sun": float(np.mean(gp[-STEPS_DAY:])),
        "alive_end": float(al[-1]),
        "alive_mean": float(np.mean(al)),
        "stab_late": float(np.mean(st[-STEPS_DAY:])),
        "stab_vs_target": float(np.mean(st[-STEPS_DAY:]) - TARGET),
        "mean_err_gp": float(np.mean(errs)) if errs else None,
        "mean_regret": float(np.mean(regrets)) if regrets else None,
        "gp_surge": float(np.mean(gp[idx])) if idx else None,
        "alive_surge": float(np.mean(al[idx])) if idx else None,
        "storm_on_surge": float(np.mean(storm_s)) if storm_s else 0.0,
        "damper_surge": float(np.mean(damp_s)) if damp_s else None,
        "damper_calm": float(np.mean(damp_c)) if damp_c else None,
        "post_surge_alive": post_alive,
        "post_surge_gp": post_gp,
        "recovery_frac_post": rec_frac,
        "pre_arm_lead": pre_arm_lead,
        "risk_lead": risk_lead,
        "storm_lead": storm_lead,
        "intuition": {
            k: float(eng.paradox.intuition.get(k, 0))
            for k in (
                "damper_bias",
                "repair_bias",
                "explore_bias",
                "countermeasure_invest",
                "pairing_strength",
                "failure_respect",
                "predict_trust",
                "target_coherence",
                "recovery_drive",
                "horizon_sensitivity",
            )
        },
    }


def adapt_knobs(state: dict, last: dict) -> dict:
    """
    Between exams: adapt training/test to maximize success.
    state holds: surge_strength, bright_ratio, train_lr, extra_revive_bias
    """
    notes = []
    gp = last.get("gp_mean", 0.23)
    alive = last.get("alive_end", 12)
    err = last.get("mean_err_gp", 0.02) or 0.02
    storm = last.get("storm_on_surge", 1.0)
    gap = last.get("stab_vs_target", 0.0) or 0.0

    post_a = last.get("post_surge_alive")
    rec_f = last.get("recovery_frac_post")
    # Prefer post-surge climb as recovery signal; end-alive for week survival
    climb_ok = post_a is not None and post_a >= 14
    # If crushing week + climb, inch surge tougher (still not blackout)
    if gp >= 0.232 and alive >= 14 and climb_ok and storm >= 0.95:
        state["surge_strength"] = min(1.35, state["surge_strength"] + 0.08)
        notes.append(f"surge harder →{state['surge_strength']:.2f}")
    # Struggle: only ease surge if BOTH end-alive and climb are weak (or surge gp floor)
    if (alive < 11 and not climb_ok) or (last.get("gp_surge") or 1) < 0.18:
        state["surge_strength"] = max(0.75, state["surge_strength"] - 0.08)
        state["bright_ratio"] = min(3, state["bright_ratio"] + 1)
        notes.append("ease surge + more bright weeks")
    # Weak end-alive but climb OK → pairing, not easier surge
    if alive < 13 and climb_ok:
        state["extra_pairing"] = min(0.12, state.get("extra_pairing", 0) + 0.03)
        notes.append("end-alive lag → pairing (climb already ok)")
    # Slow post-surge recovery → boost internal recovery desire
    if (post_a is not None and post_a < 13) or (rec_f is not None and rec_f < 0.4):
        state["extra_recovery_drive"] = min(0.55, state.get("extra_recovery_drive", 0) + 0.08)
        notes.append("recovery_drive↑")
    # Climbing well post-surge → hold desire
    if climb_ok and (rec_f or 0) >= 0.45:
        state["extra_recovery_drive"] = min(0.55, max(state.get("extra_recovery_drive", 0), 0.10))
        notes.append("recovery desire held (climb ok)")
    # Forecast noisy
    if err > 0.018:
        state["train_lr"] = min(1.4, state["train_lr"] * 1.08)
        notes.append("lr↑ forecast")
    else:
        state["train_lr"] = max(0.45, state["train_lr"] * 0.92)
        notes.append("lr↓ consolidate")
    # Under desire band
    if gap < -0.01:
        state["extra_repair"] = min(0.08, state["extra_repair"] + 0.02)
        notes.append("extra repair")
    # Survival lag
    if alive < 15:
        state["extra_pairing"] = min(0.12, state["extra_pairing"] + 0.03)
        notes.append("extra pairing")
    # Over-damped?
    if last.get("damper_calm") and last["damper_calm"] > 2.15 and alive < 15:
        state["ease_damper"] = min(0.06, state["ease_damper"] + 0.015)
        notes.append("ease base damper")

    state["notes"] = notes
    return state


def apply_knobs_to_eng(eng: HealthEngine, state: dict):
    I = eng.paradox.intuition
    I["target_coherence"] = TARGET
    if state["extra_repair"] > 0:
        I["repair_bias"] = float(np.clip(float(I.get("repair_bias", 2)) + state["extra_repair"], 0.5, 2.4))
    if state["extra_pairing"] > 0:
        I["pairing_strength"] = float(
            np.clip(float(I.get("pairing_strength", 1)) + state["extra_pairing"], 0.3, 2.5)
        )
    if state["ease_damper"] > 0:
        I["damper_bias"] = float(np.clip(float(I.get("damper_bias", 2)) - state["ease_damper"], 1.45, 2.28))
    # Internal desire: credit can grow recovery_drive; knobs set a floor (no double-add)
    base_rd = float(I.get("recovery_drive", 1.25))
    floor_rd = 1.20 + float(state.get("extra_recovery_drive", 0.0))
    I["recovery_drive"] = float(np.clip(max(base_rd, floor_rd), 0.8, 1.90))
    eng.credit.lr_scale = state["train_lr"]
    eng.target = TARGET


def adapt_cycle(eng: HealthEngine, seed: int, cycle: int, state: dict, rng: np.random.Generator):
    """One of 5 adaptation cycles: bright mix + tough with surprise."""
    lr = state["train_lr"] * (0.93**cycle)
    eng.credit.lr_scale = lr
    # bright weeks
    for b in range(state["bright_ratio"]):
        env, bud, empty = bright_week(rng)
        run_week(eng, seed + cycle * 20 + b, env, bud, empty, None, lr * 1.05, True)
    # tough + surprise (+ leading signs for horizon scout)
    env, bud, empty = tough_week(rng)
    env, bud, empty, flags, queue, arrival = inject_surprise(
        env, bud, empty, state["surge_strength"]
    )
    return run_week(
        eng, seed + cycle * 20 + 9, env, bud, empty, flags, lr, True, queue=queue, arrival=arrival
    )


def main():
    print("=" * 72)
    print(f" DESIRE {TARGET} · {N_EXAMS} EXAMS · {CYCLES_PER_EXAM} ADAPT CYCLES EACH")
    print(" recovery_drive v2: env-led release + residual-shell climb + credit desire")
    print(" between exams: assess → adapt knobs → maximize success")
    print("=" * 72)

    state = {
        "surge_strength": 1.0,
        "bright_ratio": 1,
        "train_lr": 1.15,
        "extra_repair": 0.0,
        "extra_pairing": 0.0,
        "ease_damper": 0.0,
        "extra_recovery_drive": 0.10,  # mild baseline desire; credit + adapt grow it
        "notes": [],
    }
    engines: dict[int, HealthEngine] = {}
    exam_history = []

    for exam in range(1, N_EXAMS + 1):
        print(f"\n{'#'*72}\n# EXAM {exam}/{N_EXAMS}  knobs={ {k:state[k] for k in state if k!='notes'} }\n{'#'*72}")

        # ensure engines + 5 adapt cycles
        for seed in EXAM_SEEDS:
            if seed not in engines:
                engines[seed] = HealthEngine(
                    seed=seed + 7,
                    storm_mode="auto",
                    credit_loop=True,
                    credit_lr=state["train_lr"],
                    target=TARGET,
                )
            apply_knobs_to_eng(engines[seed], state)
            rng = np.random.default_rng(seed * 1000 + exam * 17)
            print(f"  seed {seed}: {CYCLES_PER_EXAM} adapt cycles…", end=" ", flush=True)
            last_c = None
            for c in range(CYCLES_PER_EXAM):
                last_c = adapt_cycle(engines[seed], seed + exam * 50, c, state, rng)
            print(
                f"last_cycle gp={last_c['gp_mean']:.3f} alive={last_c['alive_end']:.0f} "
                f"surge_storm={100*last_c['storm_on_surge']:.0f}%"
            )

        # formal exam measurement (fresh tough+surprise, learn on)
        rows = []
        nc_rows = []
        for seed in EXAM_SEEDS:
            rng = np.random.default_rng(seed + exam * 999)
            env, bud, empty = tough_week(rng)
            env, bud, empty, flags, queue, arrival = inject_surprise(
                env, bud, empty, state["surge_strength"]
            )
            r = run_week(
                engines[seed],
                seed + 200 + exam,
                env,
                bud,
                empty,
                flags,
                max(0.35, state["train_lr"] * 0.5),
                True,
                queue=queue,
                arrival=arrival,
            )
            rows.append(r)
            # no-credit control
            eng_nc = HealthEngine(
                seed=seed + 300 + exam, storm_mode="auto", credit_loop=False, target=TARGET
            )
            nc_rows.append(
                run_week(
                    eng_nc, seed + 301, env, bud, empty, flags, 1.0, False, queue=queue, arrival=arrival
                )
            )

        def mean(rs, k):
            vals = [x[k] for x in rs if x.get(k) is not None]
            return float(np.mean(vals)) if vals else float("nan")

        summary = {
            "exam": exam,
            "knobs": {k: state[k] for k in state if k != "notes"},
            "credit_opt": {
                k: mean(rows, k)
                for k in (
                    "gp_mean",
                    "alive_end",
                    "stab_late",
                    "stab_vs_target",
                    "mean_err_gp",
                    "mean_regret",
                    "gp_surge",
                    "alive_surge",
                    "storm_on_surge",
                    "damper_surge",
                    "damper_calm",
                    "post_surge_alive",
                    "post_surge_gp",
                    "recovery_frac_post",
                    "pre_arm_lead",
                    "risk_lead",
                    "storm_lead",
                )
            },
            "no_credit": {
                k: mean(nc_rows, k)
                for k in (
                    "gp_mean",
                    "alive_end",
                    "gp_surge",
                    "storm_on_surge",
                    "post_surge_alive",
                    "recovery_frac_post",
                    "pre_arm_lead",
                    "risk_lead",
                    "storm_lead",
                )
            },
            "intuition": {
                k: float(np.mean([r["intuition"][k] for r in rows]))
                for k in rows[0]["intuition"]
            },
        }
        exam_history.append(summary)
        co, nc = summary["credit_opt"], summary["no_credit"]
        print(
            f"\n  EXAM {exam} RESULT  credit gp={co['gp_mean']:.3f} alive={co['alive_end']:.1f}  "
            f"stab={co['stab_late']:.3f} (desire {TARGET}) gap={co['stab_vs_target']:+.3f}  "
            f"err={co['mean_err_gp']:.3f}"
        )
        print(
            f"  surprise: gp={co['gp_surge']:.3f} alive={co['alive_surge']:.1f}  "
            f"storm={100*co['storm_on_surge']:.0f}%  damp {co['damper_calm']:.2f}→{co['damper_surge']:.2f}"
        )
        print(
            f"  post-surge recovery: alive={co.get('post_surge_alive', float('nan')):.1f}  "
            f"gp={co.get('post_surge_gp', float('nan')):.3f}  "
            f"recovery_drive_on={100*(co.get('recovery_frac_post') or 0):.0f}%"
        )
        print(
            f"  horizon pre-arm (3h before surge): storm/pre={100*(co.get('pre_arm_lead') or 0):.0f}%  "
            f"storm={100*(co.get('storm_lead') or 0):.0f}%  risk={co.get('risk_lead') or 0:.2f}"
        )
        print(
            f"  vs no_credit: Δgp={co['gp_mean']-nc['gp_mean']:+.3f}  "
            f"Δalive={co['alive_end']-nc['alive_end']:+.2f}"
        )

        if exam < N_EXAMS:
            state = adapt_knobs(state, co)
            print(f"  ADAPT for next exam: {state['notes']}")
            for seed in EXAM_SEEDS:
                apply_knobs_to_eng(engines[seed], state)

    # Progress report
    print("\n" + "=" * 72)
    print(f" PROGRESS REPORT · desire {TARGET} · 5 exams × 5 adapt cycles")
    print("=" * 72)
    print(
        f"  {'ex':>3}  {'gp':>6}  {'alive':>6}  {'stab':>6}  {'err':>6}  "
        f"{'surge_gp':>8}  {'storm%':>7}  {'Δgp_nc':>7}  surge_str"
    )
    for s in exam_history:
        c, n = s["credit_opt"], s["no_credit"]
        print(
            f"  {s['exam']:3d}  {c['gp_mean']:6.3f}  {c['alive_end']:6.1f}  {c['stab_late']:6.3f}  "
            f"{c['mean_err_gp']:6.3f}  {c['gp_surge']:8.3f}  {100*c['storm_on_surge']:6.0f}%  "
            f"{c['gp_mean']-n['gp_mean']:+7.3f}  {s['knobs']['surge_strength']:.2f}"
        )

    e1, e5 = exam_history[0]["credit_opt"], exam_history[-1]["credit_opt"]
    print("\n[e5 − e1]")
    print(f"  Δgp={e5['gp_mean']-e1['gp_mean']:+.4f}  Δalive={e5['alive_end']-e1['alive_end']:+.2f}")
    print(f"  Δstab={e5['stab_late']-e1['stab_late']:+.4f}  Δerr={e5['mean_err_gp']-e1['mean_err_gp']:+.4f}")
    print(f"  Δsurge_gp={e5['gp_surge']-e1['gp_surge']:+.4f}  desire gap e5={e5['stab_vs_target']:+.4f}")

    print("\n[INTUITION e1 → e5]")
    for k in exam_history[0]["intuition"]:
        a = exam_history[0]["intuition"][k]
        b = exam_history[-1]["intuition"][k]
        print(f"  {k:24s}  {a:.3f} → {b:.3f}")

    print("\n[KNOB TRAJECTORY]")
    for s in exam_history:
        k = s["knobs"]
        print(
            f"  exam{s['exam']}: surge={k['surge_strength']:.2f} bright={k['bright_ratio']} "
            f"lr={k['train_lr']:.2f} repair+={k['extra_repair']:.2f} pair+={k['extra_pairing']:.2f}"
        )

    # assessment
    e1 = exam_history[0]["credit_opt"]
    e5 = exam_history[-1]["credit_opt"]
    print("\n[ASSESSMENT]")
    assessments = []
    if e5["alive_end"] > e1["alive_end"]:
        assessments.append("Survival improved across exams under adaptive training.")
    elif e5["alive_end"] >= e1["alive_end"] - 1.0:
        assessments.append("Survival held under rising adaptive difficulty.")
    if e5["mean_err_gp"] <= e1["mean_err_gp"] + 0.002:
        assessments.append("Forecast error held or improved despite harder knobs.")
    if e5["storm_on_surge"] >= 0.95:
        assessments.append("Surprise surge: arsenal arm reliability excellent.")
    if e5["stab_late"] >= TARGET:
        assessments.append(f"Late stability meets/exceeds desire {TARGET}.")
    else:
        assessments.append(f"Late stability vs {TARGET}: gap {e5['stab_vs_target']:+.3f}.")
    if e5["gp_mean"] + 0.01 >= exam_history[-1]["no_credit"]["gp_mean"]:
        assessments.append("Control parity vs no_credit maintained.")
    pa = e5.get("post_surge_alive")
    rf = e5.get("recovery_frac_post")
    if pa is not None and pa >= 14:
        assessments.append(f"Post-surge climb healthy (alive≈{pa:.1f}).")
    elif pa is not None:
        assessments.append(f"Post-surge climb still slow (alive≈{pa:.1f}).")
    if rf is not None and rf >= 0.5:
        assessments.append(f"Recovery desire armed post-surge ({100*rf:.0f}% of window).")
    elif rf is not None:
        assessments.append(f"Recovery arming still low ({100*(rf or 0):.0f}% of window).")
    pl = e5.get("pre_arm_lead")
    if pl is not None and pl >= 0.5:
        assessments.append(
            f"Horizon scout pre-armed before surge peak ({100*pl:.0f}% of lead window)."
        )
    elif pl is not None:
        assessments.append(
            f"Horizon pre-arm still weak before peak ({100*(pl or 0):.0f}% of lead window)."
        )
    for a in assessments:
        print(f"  • {a}")

    print("\n[NEXT REFINEMENTS]")
    for i, x in enumerate(
        [
            "If alive rising and gp flat: keep inching surge_strength (adaptive already does).",
            "Split predict LR vs control LR if err drops but alive oscillates.",
            "Add mid-week second micro-surge only after 5 exams stay green.",
            "Soft Pack desire stays 0.92 until frozen multi-seed A/B/C + this suite pass.",
            "Product path A–E: budget governor + fail-closed tools as next Soft Pack modules.",
        ],
        1,
    ):
        print(f"  {i}. {x}")

    # plots
    xs = list(range(1, N_EXAMS + 1))
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    axes[0, 0].plot(xs, [s["credit_opt"]["gp_mean"] for s in exam_history], "o-", label="credit")
    axes[0, 0].plot(xs, [s["no_credit"]["gp_mean"] for s in exam_history], "s--", label="no_credit")
    axes[0, 0].set_title(f"Goodput @ {TARGET}")
    axes[0, 0].legend(fontsize=8)
    axes[0, 0].grid(True, alpha=0.25)

    axes[0, 1].plot(xs, [s["credit_opt"]["alive_end"] for s in exam_history], "o-", color="#40d0ff")
    axes[0, 1].set_title("End alive")
    axes[0, 1].grid(True, alpha=0.25)

    axes[1, 0].plot(xs, [s["credit_opt"]["stab_late"] for s in exam_history], "o-", color="#9b59b6")
    axes[1, 0].axhline(TARGET, color="#e74c3c", ls="--", label=f"desire {TARGET}")
    axes[1, 0].axhline(0.92, color="#888", ls=":")
    axes[1, 0].legend(fontsize=8)
    axes[1, 0].set_title("Late stability")
    axes[1, 0].grid(True, alpha=0.25)

    axes[1, 1].plot(xs, [s["credit_opt"]["gp_surge"] for s in exam_history], "o-", label="surge gp")
    axes[1, 1].plot(
        xs, [s["knobs"]["surge_strength"] for s in exam_history], "s--", label="surge_strength knob"
    )
    axes[1, 1].legend(fontsize=8)
    axes[1, 1].set_title("Surprise surge + adaptive difficulty")
    axes[1, 1].grid(True, alpha=0.25)

    for ax in axes.ravel():
        ax.set_xticks(xs)
    fig.suptitle(f"5 exams × 5 adapt cycles @ desire {TARGET}")
    fig.tight_layout()
    png = OUT / "paradox_credit_095_x5_progress.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"\n  plot → {png}")

    out = {
        "target": TARGET,
        "recovery_drive": True,
        "n_exams": N_EXAMS,
        "cycles_per_exam": CYCLES_PER_EXAM,
        "exams": [
            {
                "exam": s["exam"],
                "knobs": s["knobs"],
                "credit_opt": {k: v for k, v in s["credit_opt"].items()},
                "no_credit": s["no_credit"],
                "intuition": s["intuition"],
            }
            for s in exam_history
        ],
        "learning_curve": {
            "delta_gp": e5["gp_mean"] - e1["gp_mean"],
            "delta_alive": e5["alive_end"] - e1["alive_end"],
            "delta_err": e5["mean_err_gp"] - e1["mean_err_gp"],
            "delta_stab": e5["stab_late"] - e1["stab_late"],
            "final_surge_strength": exam_history[-1]["knobs"]["surge_strength"],
            "final_gap_to_target": e5["stab_vs_target"],
        },
        "assessments": assessments,
    }
    js = OUT / "paradox_credit_exam_095_x5_results.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
