"""
Logic-loop governor — controlled verify / revise / abstain under thrash budget
==============================================================================
Strengths cousin of Eye of the Storm (not front door, not model training).

Doctrine: ops/LOGIC_LOOP_GOVERNOR.md
Learning loop: predict → act → verify → note → compare (ops/LEARNING_LOOP.md)

v1 world is *synthetic faithfulness*:
  - sources are sets of fact_ids that are allowed to be asserted
  - a "model" drafts claims; some are unsupported (hallucination of source)
  - governor multi-samples, votes, checks source, revises under loop budget,
    cools thrash, abstains when still false-confident

No foundation-model training. Pure control of the loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

Action = Literal["draft", "revise", "cool", "abstain", "release"]


@dataclass
class FactSource:
    """Grounding document for faithfulness exams / multi-retrieval."""

    source_id: str
    fact_ids: set[str]

    def supports(self, fact_id: str) -> bool:
        return fact_id in self.fact_ids


def multi_source_supports(
    sources: list[FactSource],
    fact_id: str,
    *,
    policy: str = "all",
    min_frac: float = 0.67,
) -> bool:
    """
    Ground a claim against one or more retrieved sources.

    policy:
      all      — must appear in every source (conflict + dual-retrieval poison fix)
      majority — appear in ≥ min_frac of sources
      any      — appear in at least one (legacy single-source behavior)
    """
    if not sources:
        return False
    n = sum(1 for s in sources if s.supports(fact_id))
    m = len(sources)
    pol = (policy or "all").lower()
    if m == 1 or pol == "any":
        return n >= 1
    if pol == "majority":
        need = max(1, int(np.ceil(m * float(np.clip(min_frac, 0.5, 1.0)))))
        return n >= need
    # default: all
    return n == m


def source_disagreement(sources: list[FactSource]) -> float:
    """
    0 = identical fact sets, 1 = fully disjoint.
    High disagreement → raise risk / prefer abstain.
    """
    if len(sources) < 2:
        return 0.0
    sets = [set(s.fact_ids) for s in sources]
    union: set[str] = set()
    inter = set(sets[0])
    for s in sets:
        union |= s
        inter &= s
    if not union:
        return 0.0
    return float(1.0 - (len(inter) / max(1, len(union))))


def source_intersection(sources: list[FactSource]) -> set[str]:
    """Facts present in every source (dual-evidence core)."""
    if not sources:
        return set()
    inter = set(sources[0].fact_ids)
    for s in sources[1:]:
        inter &= set(s.fact_ids)
    return inter


@dataclass
class Claim:
    """Atomic asserted claim (v1: fact_id identity)."""

    fact_id: str
    confidence: float = 0.5  # model-facing 0..1

    def as_dict(self) -> dict[str, Any]:
        return {"fact_id": self.fact_id, "confidence": float(self.confidence)}


@dataclass
class DraftResult:
    claims: list[Claim]
    noise: float
    thrash: float
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "claims": [c.as_dict() for c in self.claims],
            "noise": self.noise,
            "thrash": self.thrash,
            "note": self.note,
        }


@dataclass
class VerifyResult:
    supported: list[Claim]
    unsupported: list[Claim]
    agree_rate: float  # multi-sample consistency 0..1
    source_support_rate: float
    false_confident: bool
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_supported": len(self.supported),
            "n_unsupported": len(self.unsupported),
            "agree_rate": self.agree_rate,
            "source_support_rate": self.source_support_rate,
            "false_confident": self.false_confident,
            "note": self.note,
        }


@dataclass
class GovernorStepResult:
    """One item through the full controlled loop."""

    action_trace: list[str]
    released: list[Claim]
    abstained: bool
    loop_steps: int
    thrash_after: float
    # dual scoreboard (item-level)
    main_ok: bool  # released only supported claims (and not empty wrong)
    safe_ok: bool  # main_ok OR abstain (not releasing unsupported)
    support_rate: float  # of released
    false_confidence: bool
    predicted_risk: float
    note: str
    verify: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_trace": list(self.action_trace),
            "released": [c.as_dict() for c in self.released],
            "abstained": self.abstained,
            "loop_steps": self.loop_steps,
            "thrash_after": self.thrash_after,
            "main_ok": self.main_ok,
            "safe_ok": self.safe_ok,
            "support_rate": self.support_rate,
            "false_confidence": self.false_confidence,
            "predicted_risk": self.predicted_risk,
            "note": self.note,
            "verify": self.verify,
        }


@dataclass
class LogicLoopControls:
    """Exam-tunable knobs (DNA later)."""

    max_loops: int = 3  # draft + revises (thrash budget)
    n_samples: int = 3  # self-consistency samples per verify
    conf_release: float = 0.55  # min conf to release a claim
    conf_false: float = 0.70  # high conf + unsupported = false confidence
    agree_min: float = 0.55  # multi-sample agreement to trust draft
    cool_on_disagree: bool = True
    thrash_cool_rate: float = 0.35
    seed: int = 0
    # Multi-retrieval grounding (poison / conflict defense)
    source_policy: str = "all"  # all | majority | any
    min_source_frac: float = 0.67  # for majority
    # If sources disagree hard, require stronger agree or abstain
    conflict_disagreement_thresh: float = 0.28
    conflict_agree_boost: float = 0.14  # raise agree_min when sources conflict
    # Under hard source fight: no partial release — full agree or abstain
    conflict_block_partial: bool = True
    # Thrash cool stronger when sources fight (don't stampede revises)
    conflict_thrash_cool_extra: float = 0.12


@dataclass
class SyntheticModel:
    """
    Exam stand-in for an LLM: proposes fact_ids from a pool.
    Hallucinates (unsupported facts) with rate rising in noise/thrash.
    """

    source: FactSource
    universe: list[str]  # all fact ids that might appear
    base_halluc_rate: float = 0.25
    claims_per_draft: int = 4
    seed: int = 0

    def __post_init__(self) -> None:
        self._rng = np.random.default_rng(self.seed)
        self.universe = list(self.universe)
        if not self.universe:
            self.universe = sorted(self.source.fact_ids) or ["f0"]

    def draft(
        self,
        *,
        thrash: float = 0.0,
        noise: float = 0.0,
        prefer_supported: bool = False,
        grounded_pool: set[str] | list[str] | None = None,
    ) -> DraftResult:
        """
        Sample claims. Hallucination rate climbs with thrash + noise.
        prefer_supported: revision mode — bias toward grounded facts.
        grounded_pool: multi-source intersection (preferred over belief-source alone).
        """
        h = float(
            np.clip(
                self.base_halluc_rate + 0.35 * thrash + 0.40 * noise
                - (0.40 if prefer_supported else 0.0),
                0.02,
                0.92,
            )
        )
        # Prefer dual-evidence core when revising; else model belief source
        if grounded_pool:
            gset = set(grounded_pool)
            supported_pool = [f for f in self.universe if f in gset] or list(gset)
        else:
            supported_pool = [f for f in self.universe if self.source.supports(f)]
        if not supported_pool:
            supported_pool = list(self.source.fact_ids) or self.universe[:1]
        if grounded_pool:
            gset = set(grounded_pool)
            unsupported_pool = [f for f in self.universe if f not in gset]
        else:
            unsupported_pool = [
                f for f in self.universe if not self.source.supports(f)
            ]
        if not unsupported_pool:
            unsupported_pool = [f"halluc_{i}" for i in range(6)]

        claims: list[Claim] = []
        n = max(1, self.claims_per_draft)
        for _ in range(n):
            # Under prefer_supported, heavily bias to grounded core
            roll_h = h * (0.35 if prefer_supported and grounded_pool else 1.0)
            if self._rng.random() < roll_h:
                fid = str(self._rng.choice(unsupported_pool))
                conf = float(
                    np.clip(
                        self._rng.normal(0.55 + 0.35 * thrash, 0.12),
                        0.15,
                        0.99,
                    )
                )
            else:
                fid = str(self._rng.choice(supported_pool))
                conf = float(np.clip(self._rng.normal(0.72, 0.10), 0.2, 0.99))
            claims.append(Claim(fact_id=fid, confidence=conf))

        return DraftResult(
            claims=claims,
            noise=float(noise),
            thrash=float(thrash),
            note=f"h={h:.2f} pref_sup={prefer_supported} gpool={len(grounded_pool or [])}",
        )


@dataclass
class LogicLoopGovernor:
    """
    Always-on control spine for one answer item.

    Grounding: optional multi-retrieval `sources` with source_policy.
    Single polluted retrieval is not enough under poison/conflict — pass
    ≥2 independent retrievals and policy=all (intersection).
    """

    model: SyntheticModel
    controls: LogicLoopControls = field(default_factory=LogicLoopControls)
    # Independent retrievals for multi-source grounding (None → [model.source])
    sources: list[FactSource] | None = None
    thrash: float = 0.0
    _step: int = 0
    _prev_disagree: float = 0.0

    def __post_init__(self) -> None:
        self.controls.max_loops = int(np.clip(self.controls.max_loops, 1, 8))
        self.controls.n_samples = int(np.clip(self.controls.n_samples, 1, 9))
        self._rng = np.random.default_rng(self.controls.seed + 17)
        if self.sources is not None and len(self.sources) == 0:
            self.sources = None

    def grounding_sources(self) -> list[FactSource]:
        if self.sources:
            return list(self.sources)
        return [self.model.source]

    def is_grounded(self, fact_id: str) -> bool:
        return multi_source_supports(
            self.grounding_sources(),
            fact_id,
            policy=self.controls.source_policy,
            min_frac=self.controls.min_source_frac,
        )

    def reset_thrash(self) -> None:
        self.thrash = 0.0
        self._prev_disagree = 0.0

    def predict_risk(self, noise: float) -> float:
        """PREDICT: short-horizon risk of ungrounded release."""
        disagree = source_disagreement(self.grounding_sources())
        r = (
            0.22 * noise
            + 0.40 * self.thrash
            + 0.25 * self._prev_disagree
            + 0.25 * disagree
        )
        return float(np.clip(r, 0, 1))

    def _verify_drafts(
        self,
        drafts: list[DraftResult],
        *,
        sources: list[FactSource] | None = None,
    ) -> VerifyResult:
        """
        Self-consistency: fact_id frequency across samples.
        Source support: multi-source policy (all / majority / any).
        Keep claims that both (a) appear in sample majority and (b) are grounded.
        """
        srcs = sources if sources is not None else self.grounding_sources()
        n = max(1, len(drafts))
        counts: dict[str, int] = {}
        conf_acc: dict[str, list[float]] = {}
        for d in drafts:
            seen = set()
            for c in d.claims:
                if c.fact_id in seen:
                    continue
                seen.add(c.fact_id)
                counts[c.fact_id] = counts.get(c.fact_id, 0) + 1
                conf_acc.setdefault(c.fact_id, []).append(c.confidence)

        if not counts:
            return VerifyResult(
                supported=[],
                unsupported=[],
                agree_rate=0.0,
                source_support_rate=0.0,
                false_confident=True,
                note="empty",
            )

        mode_n = max(counts.values())
        agree = mode_n / float(n)

        thresh = max(1, int(np.ceil(n * 0.5)))
        candidates = [fid for fid, k in counts.items() if k >= thresh]
        if not candidates:
            candidates = [
                fid
                for fid, _ in sorted(counts.items(), key=lambda x: -x[1])[:2]
            ]

        supported: list[Claim] = []
        unsupported: list[Claim] = []
        for fid in candidates:
            conf = float(np.mean(conf_acc.get(fid, [0.5])))
            claim = Claim(fact_id=fid, confidence=conf)
            if multi_source_supports(
                srcs,
                fid,
                policy=self.controls.source_policy,
                min_frac=self.controls.min_source_frac,
            ):
                supported.append(claim)
            else:
                unsupported.append(claim)

        n_all = max(1, len(supported) + len(unsupported))
        src_rate = len(supported) / n_all
        false_conf = any(
            c.confidence >= self.controls.conf_false for c in unsupported
        ) or (agree < self.controls.agree_min and len(unsupported) > 0)

        disagree = source_disagreement(srcs)
        note = (
            f"agree={agree:.2f} src={src_rate:.2f} "
            f"pol={self.controls.source_policy} nsrc={len(srcs)} "
            f"src_dis={disagree:.2f}"
        )
        return VerifyResult(
            supported=supported,
            unsupported=unsupported,
            agree_rate=float(agree),
            source_support_rate=float(src_rate),
            false_confident=bool(false_conf),
            note=note,
        )

    def _sample_drafts(
        self,
        *,
        noise: float,
        thrash: float,
        n: int,
        prefer_supported: bool,
        grounded_pool: set[str] | None = None,
    ) -> list[DraftResult]:
        out = []
        for i in range(n):
            # slight thrash growth per sample = sampling cost
            t = thrash + 0.04 * i
            out.append(
                self.model.draft(
                    thrash=t,
                    noise=noise,
                    prefer_supported=prefer_supported,
                    grounded_pool=grounded_pool,
                )
            )
        return out

    def step_item(
        self,
        *,
        noise: float = 0.0,
        inject_thrash: float = 0.0,
    ) -> GovernorStepResult:
        """
        Full controlled loop for one answer unit.

        Doctrine peak path:
          dual evidence + intersection grounding
          → thrash-bounded revise
          → strip ungrounded
          → abstain when sources fight / nothing grounded
          → FC only on released junk
        """
        self._step += 1
        self.thrash = float(np.clip(self.thrash + inject_thrash, 0, 1.5))
        trace: list[str] = []
        risk = self.predict_risk(noise)
        trace.append(f"predict_risk={risk:.2f}")
        srcs = self.grounding_sources()
        src_dis = source_disagreement(srcs)
        core = source_intersection(srcs)
        # Multi-source: revise toward intersection, not belief-union
        grounded_pool: set[str] | None = core if len(srcs) > 1 else None
        if grounded_pool is not None and not grounded_pool:
            # sources fully fight — nothing to ground; abstain path
            grounded_pool = set()

        sources_fighting = src_dis >= self.controls.conflict_disagreement_thresh
        agree_need = float(self.controls.agree_min)
        if sources_fighting:
            # scale boost with how hard sources fight
            boost = self.controls.conflict_agree_boost * (0.6 + 0.8 * src_dis)
            agree_need = min(0.95, agree_need + boost)
            # extra cool — don't thrash-revise into the fight
            self.thrash *= max(
                0.0, 1.0 - self.controls.conflict_thrash_cool_extra
            )
            trace.append(f"src_conflict={src_dis:.2f}+agree_need={agree_need:.2f}")
            if not core:
                # empty intersection: only honest move is abstain
                self.thrash *= 0.85
                return GovernorStepResult(
                    action_trace=trace + ["abstain_empty_intersection"],
                    released=[],
                    abstained=True,
                    loop_steps=0,
                    thrash_after=float(self.thrash),
                    main_ok=False,
                    safe_ok=True,
                    support_rate=1.0,
                    false_confidence=False,
                    predicted_risk=float(risk),
                    note="+".join(trace + ["abstain_empty_intersection"]),
                    verify=None,
                )

        # pre-arm cool if already thrashing hard
        if self.thrash > 0.85 and self.controls.cool_on_disagree:
            self.thrash *= 1.0 - self.controls.thrash_cool_rate
            trace.append("cool_pre")

        loops = 0
        prefer = False
        last_v: VerifyResult | None = None
        released: list[Claim] = []
        abstained = False

        while loops < self.controls.max_loops:
            loops += 1
            # sampling thrash tax (lighter when sources already fighting)
            tax = 0.08 * self.controls.n_samples * (0.08 if sources_fighting else 0.15)
            self.thrash = float(np.clip(self.thrash + tax, 0, 1.5))
            drafts = self._sample_drafts(
                noise=noise,
                thrash=self.thrash,
                n=self.controls.n_samples,
                prefer_supported=prefer or sources_fighting,
                grounded_pool=grounded_pool,
            )
            trace.append("revise" if prefer else "draft")
            v = self._verify_drafts(drafts, sources=srcs)
            last_v = v
            self._prev_disagree = float(1.0 - v.agree_rate)
            trace.append(v.note)

            # good path: agreement + multi-source grounded candidates above conf
            good = [
                c
                for c in v.supported
                if c.confidence >= self.controls.conf_release
            ]
            bad = v.unsupported

            if good and not bad and v.agree_rate >= agree_need:
                released = good
                trace.append("release")
                break

            # Partial release: grounded only — blocked when sources fight hard
            partial_ok = not (
                sources_fighting and self.controls.conflict_block_partial
            )
            if (
                partial_ok
                and good
                and v.source_support_rate >= 0.67
                and v.agree_rate >= max(0.45, agree_need - 0.12)
            ):
                released = good
                if bad:
                    trace.append("drop_ungrounded")
                else:
                    trace.append("release_partial")
                break

            # When sources fight and we only have junk: cool + revise toward core
            if sources_fighting and not good and bad:
                trace.append("fight_no_grounded")

            # bad path: cool thrash and try revise once more
            if self.controls.cool_on_disagree:
                cool = self.controls.thrash_cool_rate
                if sources_fighting:
                    cool = min(0.75, cool + self.controls.conflict_thrash_cool_extra)
                self.thrash *= 1.0 - cool
                trace.append("cool")
            prefer = True

            if loops >= self.controls.max_loops:
                # thrash budget exhausted — only multi-source grounded
                # under hard fight: require agree_need even at budget
                if good and (
                    not sources_fighting or v.agree_rate >= agree_need - 0.05
                ):
                    released = good
                    trace.append("release_budget_grounded_only")
                else:
                    abstained = True
                    released = []
                    trace.append(
                        "abstain_budget_fight"
                        if sources_fighting
                        else "abstain_budget"
                    )
                break

        # if loop ended without release decision
        if not released and not abstained:
            if last_v and last_v.supported:
                released = [
                    c
                    for c in last_v.supported
                    if c.confidence >= self.controls.conf_release
                ]
                # sources fighting: don't fallback-release weak partials
                if sources_fighting and last_v.agree_rate < agree_need - 0.05:
                    released = []
                    abstained = True
                    trace.append("abstain_fight_fallback")
                elif released:
                    trace.append("release_fallback_grounded")
                else:
                    abstained = True
                    trace.append("abstain_low_conf")
            else:
                abstained = True
                trace.append("abstain_no_support")

        # Final safety filter: never release ungrounded (intersection / policy)
        if released:
            kept = [c for c in released if self.is_grounded(c.fact_id)]
            if len(kept) < len(released):
                trace.append("final_strip_ungrounded")
            released = kept
            if not released:
                abstained = True
                trace.append("abstain_after_strip")

        # scoreboard vs multi-source grounding (not model.belief alone)
        # false_confidence = released high-conf ungrounded only (not "we saw junk and abstained")
        if released:
            n_sup = sum(1 for c in released if self.is_grounded(c.fact_id))
            support_rate = n_sup / max(1, len(released))
            main_ok = n_sup == len(released) and len(released) > 0
            false_conf = any(
                (not self.is_grounded(c.fact_id))
                and c.confidence >= self.controls.conf_false
                for c in released
            )
        else:
            support_rate = 1.0 if abstained else 0.0
            main_ok = False  # nothing grounded released
            # Abstain after seeing bad candidates is success, not false confidence
            false_conf = False

        # SAFE: no ungrounded claim released (abstain OK); multi-source policy
        unsafe = any(not self.is_grounded(c.fact_id) for c in released)
        safe_ok = not unsafe

        # thrash cool after success
        if main_ok or abstained:
            self.thrash *= 0.85

        return GovernorStepResult(
            action_trace=trace,
            released=released,
            abstained=abstained,
            loop_steps=loops,
            thrash_after=float(self.thrash),
            main_ok=bool(main_ok),
            safe_ok=bool(safe_ok),
            support_rate=float(support_rate),
            false_confidence=bool(false_conf),
            predicted_risk=float(risk),
            note="+".join(trace),
            verify=last_v.as_dict() if last_v else None,
        )


def baseline_one_shot(
    model: SyntheticModel,
    *,
    noise: float,
    thrash: float,
    conf_release: float = 0.40,
) -> GovernorStepResult:
    """
    No verify loop — one draft, release all claims above conf.
    Mimics 'just answer' without logic-loop governor.
    """
    d = model.draft(thrash=thrash, noise=noise, prefer_supported=False)
    released = [c for c in d.claims if c.confidence >= conf_release]
    if not released:
        released = list(d.claims[:1])  # always say something (naive)
    n_sup = sum(1 for c in released if model.source.supports(c.fact_id))
    support_rate = n_sup / max(1, len(released))
    main_ok = n_sup == len(released) and len(released) > 0
    unsafe = any(not model.source.supports(c.fact_id) for c in released)
    false_conf = any(
        (not model.source.supports(c.fact_id)) and c.confidence >= 0.70
        for c in released
    )
    return GovernorStepResult(
        action_trace=["draft", "release_naive"],
        released=released,
        abstained=False,
        loop_steps=1,
        thrash_after=float(thrash),
        main_ok=bool(main_ok),
        safe_ok=bool(not unsafe),
        support_rate=float(support_rate),
        false_confidence=bool(false_conf),
        predicted_risk=float(np.clip(0.3 * noise + 0.4 * thrash, 0, 1)),
        note="baseline_one_shot",
        verify=None,
    )


def make_exam_world(seed: int = 0, n_facts: int = 12, n_source: int = 7) -> tuple[FactSource, list[str]]:
    """Supported facts + larger universe (hallucination pool)."""
    rng = np.random.default_rng(seed)
    universe = [f"fact_{i}" for i in range(n_facts)]
    pick = rng.choice(universe, size=min(n_source, n_facts), replace=False)
    source = FactSource(source_id="doc0", fact_ids=set(str(x) for x in pick))
    return source, universe
