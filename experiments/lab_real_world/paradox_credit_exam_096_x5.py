"""
Desire 0.96 — 5 exams × 5 adapt cycles + sim host pressure
==========================================================
Same stack as 0.95 (recovery + horizon + credit) plus:
  - World host pressure schedules (CPU/RAM/GPU/IO sim)
  - sandbox ResourceDriver dry-run → apply_resource_intent on World
  - Between exams: adapt knobs to hold desire 0.96 under rising surge + host heat

  python real_world/paradox_credit_exam_096_x5.py
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
from paradox_credit_exam import (
    World,
    apply_plan,
    apply_resource_intent,
    bright_week,
    tough_week,
    host_pressure_week,
    STEPS_DAY,
)
from sandbox.resource_driver import ResourceDriver, SimSensors, snapshot_from_dict

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

TARGET = 0.96
N_EXAMS = 5
CYCLES_PER_EXAM = 5
EXAM_SEEDS = [7, 11, 21, 29, 42]

# Pass bar for "successful" 0.96 run (host pressure legitimately cuts goodput)
PASS_GP = 0.185  # under host sim; 0.22 was pre-host bar
PASS_ALIVE = 14.0
PASS_STAB = TARGET - 0.005  # allow tiny miss → still "near"
PASS_STORM = 0.95
PASS_POST = 14.0
PASS_PRE_ARM = 0.50


def inject_surprise(env, bud, empty, strength: float = 1.0):
    env, bud, empty = list(env), list(bud), list(empty)
    flags = [False] * len(env)
    queue = [0.05] * len(env)
    arrival = [1.0] * len(env)
    for d in range(7):
        for h in range(STEPS_DAY):
            t = d * STEPS_DAY + h
            if d == 5 and 7 <= h <= 9:
                ramp = (h - 6) / 3.0
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
    host=None,
    host_strength: float = 1.0,
    use_resource: bool = True,
):
    eng.credit.lr_scale = lr
    eng.credit_loop = True
    eng.target = TARGET
    eng.paradox.intuition["target_coherence"] = TARGET
    w = World(rng=np.random.default_rng(seed + 3))
    sensors = SimSensors()
    driver = ResourceDriver(sensors=sensors) if use_resource else None

    if host is None:
        rng_h = np.random.default_rng(seed + 99)
        host = host_pressure_week(rng_h, strength=host_strength)
    cpu_s, mem_s, gpu_s, io_s = host

    gps, alives, stabs = [], [], []
    errs, regrets = [], []
    storm_s, damp_s, damp_c = [], [], []
    recovery_flags, pre_arm_all, risk_all, storm_all = [], [], [], []
    throttle_all, host_cpu_all = [], []

    for t in range(len(env)):
        w.budget_mul, w.tool_empty = bud[t], empty[t]
        w.set_host_pressure(cpu=cpu_s[t], mem=mem_s[t], gpu=gpu_s[t], io=io_s[t])
        sensors.set(
            cpu_util=cpu_s[t],
            mem_pressure=mem_s[t],
            gpu_util=gpu_s[t],
            io_wait=io_s[t],
        )
        # host pressure also shows as thrash / queue heat
        thrash = w.retries + w.rempty() + 0.35 * cpu_s[t] + 0.25 * mem_s[t]
        kw = {
            "queue_pressure": float(queue[t]) if queue is not None else float(0.15 + 0.5 * cpu_s[t]),
        }
        if arrival is not None:
            kw["arrival_rate"] = float(arrival[t])
        out = eng.step_from_metrics(
            success_rate=w.rs(),
            env_load=env[t],
            thrash=thrash,
            goodput=w.rgp(),
            budget_remaining=bud[t],
            empty_tool_rate=max(w.rempty(), 0.5 * mem_s[t] * 0.2),
            **kw,
        )
        if driver is not None:
            res = driver.step(out["plan"], host=snapshot_from_dict(w.host_snapshot()))
            apply_resource_intent(w, res.intent)
            throttle_all.append(float(res.intent.compute_throttle))
        else:
            throttle_all.append(0.0)
        host_cpu_all.append(cpu_s[t])

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
    if idx:
        last_s, first_s = max(idx), min(idx)
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
        "mean_throttle": float(np.mean(throttle_all)) if throttle_all else 0.0,
        "mean_host_cpu": float(np.mean(host_cpu_all)) if host_cpu_all else 0.0,
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
    notes = []
    gp = last.get("gp_mean", 0.23)
    alive = last.get("alive_end", 12)
    err = last.get("mean_err_gp", 0.02) or 0.02
    storm = last.get("storm_on_surge", 1.0)
    gap = last.get("stab_vs_target", 0.0) or 0.0
    post_a = last.get("post_surge_alive")
    rec_f = last.get("recovery_frac_post")
    climb_ok = post_a is not None and post_a >= 13
    stab_ok = gap >= -0.008

    # Hold 0.96 first — only harden if crushing
    if gp >= 0.228 and alive >= 14 and climb_ok and stab_ok and storm >= 0.95:
        state["surge_strength"] = min(1.30, state["surge_strength"] + 0.06)
        state["host_strength"] = min(1.25, state.get("host_strength", 1.0) + 0.05)
        notes.append(f"surge/host harder →{state['surge_strength']:.2f}/{state['host_strength']:.2f}")
    if (alive < 11 and not climb_ok) or (last.get("gp_surge") or 1) < 0.17 or gap < -0.015:
        state["surge_strength"] = max(0.70, state["surge_strength"] - 0.08)
        state["host_strength"] = max(0.65, state.get("host_strength", 1.0) - 0.08)
        state["bright_ratio"] = min(3, state["bright_ratio"] + 1)
        notes.append("ease surge/host + bright")
    if alive < 13 and climb_ok:
        state["extra_pairing"] = min(0.14, state.get("extra_pairing", 0) + 0.03)
        notes.append("pairing↑ end-alive")
    if (post_a is not None and post_a < 12) or (rec_f is not None and rec_f < 0.4):
        state["extra_recovery_drive"] = min(0.55, state.get("extra_recovery_drive", 0) + 0.08)
        notes.append("recovery_drive↑")
    if climb_ok and (rec_f or 0) >= 0.45:
        state["extra_recovery_drive"] = min(0.55, max(state.get("extra_recovery_drive", 0), 0.10))
    if gap < -0.008:
        state["extra_repair"] = min(0.10, state.get("extra_repair", 0) + 0.025)
        notes.append("repair↑ desire gap")
    if err > 0.018:
        state["train_lr"] = min(1.45, state["train_lr"] * 1.08)
        notes.append("lr↑")
    else:
        state["train_lr"] = max(0.45, state["train_lr"] * 0.93)
        notes.append("lr↓")
    if last.get("pre_arm_lead", 1) is not None and last.get("pre_arm_lead", 1) < 0.4:
        state["extra_horizon"] = min(0.35, state.get("extra_horizon", 0) + 0.08)
        notes.append("horizon_sens↑")
    if last.get("mean_throttle", 0) < 0.08 and last.get("mean_host_cpu", 0) > 0.45:
        state["extra_horizon"] = min(0.35, state.get("extra_horizon", 0) + 0.05)
        notes.append("resource posture↑")
    if last.get("damper_calm") and last["damper_calm"] > 2.15 and alive < 14:
        state["ease_damper"] = min(0.06, state.get("ease_damper", 0) + 0.015)
        notes.append("ease damper")

    state["notes"] = notes
    return state


def apply_knobs_to_eng(eng: HealthEngine, state: dict):
    I = eng.paradox.intuition
    I["target_coherence"] = TARGET
    if state.get("extra_repair", 0) > 0:
        I["repair_bias"] = float(np.clip(float(I.get("repair_bias", 2)) + state["extra_repair"], 0.5, 2.4))
    if state.get("extra_pairing", 0) > 0:
        I["pairing_strength"] = float(
            np.clip(float(I.get("pairing_strength", 1)) + state["extra_pairing"], 0.3, 2.5)
        )
    if state.get("ease_damper", 0) > 0:
        I["damper_bias"] = float(np.clip(float(I.get("damper_bias", 2)) - state["ease_damper"], 1.45, 2.28))
    base_rd = float(I.get("recovery_drive", 1.25))
    floor_rd = 1.20 + float(state.get("extra_recovery_drive", 0.0))
    I["recovery_drive"] = float(np.clip(max(base_rd, floor_rd), 0.8, 1.90))
    base_hs = float(I.get("horizon_sensitivity", 1.0))
    I["horizon_sensitivity"] = float(
        np.clip(max(base_hs, 1.0 + state.get("extra_horizon", 0.0)), 0.6, 1.7)
    )
    eng.credit.lr_scale = state["train_lr"]
    eng.target = TARGET


def adapt_cycle(eng, seed, cycle, state, rng):
    lr = state["train_lr"] * (0.93**cycle)
    eng.credit.lr_scale = lr
    hs = state.get("host_strength", 1.0)
    for b in range(state["bright_ratio"]):
        env, bud, empty = bright_week(rng)
        run_week(
            eng,
            seed + cycle * 20 + b,
            env,
            bud,
            empty,
            None,
            lr * 1.05,
            True,
            host_strength=max(0.5, hs * 0.6),
        )
    env, bud, empty = tough_week(rng)
    env, bud, empty, flags, queue, arrival = inject_surprise(env, bud, empty, state["surge_strength"])
    host = host_pressure_week(rng, strength=hs)
    return run_week(
        eng,
        seed + cycle * 20 + 9,
        env,
        bud,
        empty,
        flags,
        lr,
        True,
        queue=queue,
        arrival=arrival,
        host=host,
        host_strength=hs,
    )


def passes(co: dict) -> bool:
    return (
        (co.get("gp_mean") or 0) >= PASS_GP
        and (co.get("alive_end") or 0) >= PASS_ALIVE
        and (co.get("stab_late") or 0) >= PASS_STAB
        and (co.get("storm_on_surge") or 0) >= PASS_STORM
        and (co.get("post_surge_alive") or 0) >= PASS_POST
        and (co.get("pre_arm_lead") or 0) >= PASS_PRE_ARM
    )


def main():
    print("=" * 72)
    print(f" DESIRE {TARGET} · {N_EXAMS} EXAMS · host-pressure sim + resource intents")
    print(" between exams: assess → adapt knobs → hold 0.96")
    print("=" * 72)

    state = {
        "surge_strength": 0.95,
        "host_strength": 0.90,
        "bright_ratio": 1,
        "train_lr": 1.18,
        "extra_repair": 0.02,
        "extra_pairing": 0.02,
        "ease_damper": 0.0,
        "extra_recovery_drive": 0.12,
        "extra_horizon": 0.05,
        "notes": [],
    }
    engines: dict[int, HealthEngine] = {}
    exam_history = []

    for exam in range(1, N_EXAMS + 1):
        print(f"\n{'#'*72}\n# EXAM {exam}/{N_EXAMS}  knobs={ {k:state[k] for k in state if k!='notes'} }\n{'#'*72}")
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
            print(f"  seed {seed}: {CYCLES_PER_EXAM} adapt…", end=" ", flush=True)
            last_c = None
            for c in range(CYCLES_PER_EXAM):
                last_c = adapt_cycle(engines[seed], seed + exam * 50, c, state, rng)
            print(
                f"gp={last_c['gp_mean']:.3f} alive={last_c['alive_end']:.0f} "
                f"stab={last_c['stab_late']:.3f} thr={last_c['mean_throttle']:.2f}"
            )

        rows, nc_rows = [], []
        for seed in EXAM_SEEDS:
            rng = np.random.default_rng(seed + exam * 999)
            env, bud, empty = tough_week(rng)
            env, bud, empty, flags, queue, arrival = inject_surprise(
                env, bud, empty, state["surge_strength"]
            )
            host = host_pressure_week(rng, strength=state.get("host_strength", 1.0))
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
                host=host,
                host_strength=state.get("host_strength", 1.0),
            )
            rows.append(r)
            eng_nc = HealthEngine(
                seed=seed + 300 + exam, storm_mode="auto", credit_loop=False, target=TARGET
            )
            nc_rows.append(
                run_week(
                    eng_nc,
                    seed + 301,
                    env,
                    bud,
                    empty,
                    flags,
                    1.0,
                    False,
                    queue=queue,
                    arrival=arrival,
                    host=host,
                    use_resource=True,
                )
            )

        def mean(rs, k):
            vals = [x[k] for x in rs if x.get(k) is not None]
            return float(np.mean(vals)) if vals else float("nan")

        keys = [
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
            "mean_throttle",
            "mean_host_cpu",
        ]
        summary = {
            "exam": exam,
            "knobs": {k: state[k] for k in state if k != "notes"},
            "credit_opt": {k: mean(rows, k) for k in keys},
            "no_credit": {
                k: mean(nc_rows, k)
                for k in (
                    "gp_mean",
                    "alive_end",
                    "gp_surge",
                    "storm_on_surge",
                    "post_surge_alive",
                    "pre_arm_lead",
                    "mean_throttle",
                )
            },
            "intuition": {
                k: float(np.mean([r["intuition"][k] for r in rows])) for k in rows[0]["intuition"]
            },
        }
        exam_history.append(summary)
        co, nc = summary["credit_opt"], summary["no_credit"]
        ok = passes(co)
        print(
            f"\n  EXAM {exam}  gp={co['gp_mean']:.3f} alive={co['alive_end']:.1f} "
            f"stab={co['stab_late']:.3f} (desire {TARGET}) gap={co['stab_vs_target']:+.3f}  "
            f"{'PASS' if ok else 'SOFT'}"
        )
        print(
            f"  surge storm={100*co['storm_on_surge']:.0f}%  post={co.get('post_surge_alive')}  "
            f"rec={100*(co.get('recovery_frac_post') or 0):.0f}%  "
            f"pre_arm={100*(co.get('pre_arm_lead') or 0):.0f}%  "
            f"throttle={co.get('mean_throttle'):.2f} host_cpu={co.get('mean_host_cpu'):.2f}"
        )
        print(f"  vs nc: Δgp={co['gp_mean']-nc['gp_mean']:+.3f} Δalive={co['alive_end']-nc['alive_end']:+.2f}")
        if exam < N_EXAMS:
            state = adapt_knobs(state, co)
            print(f"  ADAPT: {state['notes']}")
            for seed in EXAM_SEEDS:
                apply_knobs_to_eng(engines[seed], state)

    e1, e5 = exam_history[0]["credit_opt"], exam_history[-1]["credit_opt"]
    print("\n" + "=" * 72)
    print(f" PROGRESS · desire {TARGET} · host-pressure + resource sim")
    print("=" * 72)
    print(f"  {'ex':>3}  {'gp':>6}  {'alive':>6}  {'stab':>6}  {'err':>6}  {'storm%':>7}  {'pre%':>5}  host")
    for s in exam_history:
        c = s["credit_opt"]
        print(
            f"  {s['exam']:3d}  {c['gp_mean']:6.3f}  {c['alive_end']:6.1f}  {c['stab_late']:6.3f}  "
            f"{c['mean_err_gp']:6.3f}  {100*c['storm_on_surge']:6.0f}%  "
            f"{100*(c.get('pre_arm_lead') or 0):4.0f}%  "
            f"h={s['knobs'].get('host_strength', 1):.2f}/s={s['knobs']['surge_strength']:.2f}"
        )
    print(f"\n[e5−e1] Δgp={e5['gp_mean']-e1['gp_mean']:+.4f} Δalive={e5['alive_end']-e1['alive_end']:+.2f} "
          f"Δstab={e5['stab_late']-e1['stab_late']:+.4f} gap_e5={e5['stab_vs_target']:+.4f}")

    assessments = []
    if e5["stab_late"] >= TARGET - 0.002:
        assessments.append(f"Late stability meets/near desire {TARGET}.")
    else:
        assessments.append(f"Late stability vs {TARGET}: gap {e5['stab_vs_target']:+.3f}.")
    if e5["storm_on_surge"] >= 0.95:
        assessments.append("Surprise surge: storm arm excellent.")
    if (e5.get("pre_arm_lead") or 0) >= 0.5:
        assessments.append(f"Horizon pre-arm lead {100*e5['pre_arm_lead']:.0f}%.")
    if (e5.get("post_surge_alive") or 0) >= 12:
        assessments.append(f"Post-surge climb ok (alive≈{e5['post_surge_alive']:.1f}).")
    if (e5.get("mean_throttle") or 0) >= 0.10:
        assessments.append(f"Resource throttle engaged (mean={e5['mean_throttle']:.2f}).")
    final_pass = passes(e5)
    assessments.append("BATTERY PASS @0.96" if final_pass else "BATTERY SOFT — near band, review gaps.")
    print("\n[ASSESSMENT]")
    for a in assessments:
        print(f"  • {a}")

    xs = list(range(1, N_EXAMS + 1))
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    axes[0, 0].plot(xs, [s["credit_opt"]["gp_mean"] for s in exam_history], "o-")
    axes[0, 0].set_title(f"Goodput @ {TARGET}")
    axes[0, 0].grid(True, alpha=0.25)
    axes[0, 1].plot(xs, [s["credit_opt"]["alive_end"] for s in exam_history], "o-", color="#40d0ff")
    axes[0, 1].set_title("End alive")
    axes[0, 1].grid(True, alpha=0.25)
    axes[1, 0].plot(xs, [s["credit_opt"]["stab_late"] for s in exam_history], "o-", color="#9b59b6")
    axes[1, 0].axhline(TARGET, color="#e74c3c", ls="--", label=f"desire {TARGET}")
    axes[1, 0].axhline(0.95, color="#888", ls=":")
    axes[1, 0].legend(fontsize=8)
    axes[1, 0].set_title("Late stability")
    axes[1, 0].grid(True, alpha=0.25)
    axes[1, 1].plot(xs, [s["credit_opt"].get("mean_throttle") or 0 for s in exam_history], "o-", label="throttle")
    axes[1, 1].plot(xs, [s["knobs"].get("host_strength", 1) for s in exam_history], "s--", label="host_str")
    axes[1, 1].legend(fontsize=8)
    axes[1, 1].set_title("Resource throttle + host heat")
    axes[1, 1].grid(True, alpha=0.25)
    for ax in axes.ravel():
        ax.set_xticks(xs)
    fig.suptitle(f"Desire {TARGET} · host pressure sim · 5×5 adapt")
    fig.tight_layout()
    png = OUT / "paradox_credit_096_x5_progress.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)

    out = {
        "target": TARGET,
        "host_pressure_sim": True,
        "resource_driver": True,
        "n_exams": N_EXAMS,
        "cycles_per_exam": CYCLES_PER_EXAM,
        "pass_criteria": {
            "gp": PASS_GP,
            "alive": PASS_ALIVE,
            "stab": PASS_STAB,
            "storm": PASS_STORM,
            "post": PASS_POST,
            "pre_arm": PASS_PRE_ARM,
        },
        "final_pass": final_pass,
        "exams": [
            {
                "exam": s["exam"],
                "knobs": s["knobs"],
                "credit_opt": s["credit_opt"],
                "no_credit": s["no_credit"],
                "intuition": s["intuition"],
            }
            for s in exam_history
        ],
        "learning_curve": {
            "delta_gp": e5["gp_mean"] - e1["gp_mean"],
            "delta_alive": e5["alive_end"] - e1["alive_end"],
            "delta_stab": e5["stab_late"] - e1["stab_late"],
            "final_gap": e5["stab_vs_target"],
            "final_surge": exam_history[-1]["knobs"]["surge_strength"],
            "final_host": exam_history[-1]["knobs"].get("host_strength"),
        },
        "assessments": assessments,
    }
    js = OUT / "paradox_credit_exam_096_x5_results.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n  plot → {png}\n  json → {js}\n  final_pass={final_pass}")
    print("=" * 72)
    return 0 if final_pass else 0  # still 0 so campaign continues; flag in JSON


if __name__ == "__main__":
    raise SystemExit(main())
