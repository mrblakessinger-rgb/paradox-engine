"""
LangGraph adapter — optional dependency.

    from plugins.adapters.langgraph import EyeStormCallback, eye_gate_node

    # Option A: callback on graph invoke (metrics in → control state out)
    cb = EyeStormCallback(eye)
    graph.invoke(state, config={"callbacks": [cb]})

    # Option B: explicit node in the graph
    graph.add_node("eye_storm", eye_gate_node(eye))

If langgraph is not installed, helpers still work as pure callables on dict state.
"""

from __future__ import annotations

from typing import Any, Callable

from ..core import Eye, EyeOfTheStorm
from ..types import ControlHints, HealthSnapshot


def snapshot_from_state(state: dict[str, Any]) -> HealthSnapshot:
    """
    Pull metrics from a LangGraph-style state dict.
    Recognized keys (use any subset):

      success_rate, failure_rate, goodput, env_load, thrash,
      queue_depth, empty_tool_rate, budget_remaining, latency_p95,
      n_agents, n_active, tool_errors, tool_calls
    """
    empty = state.get("empty_tool_rate")
    if empty is None and state.get("tool_calls"):
        te = float(state.get("tool_errors") or 0)
        tc = float(state["tool_calls"])
        empty = te / max(1.0, tc)

    return HealthSnapshot(
        success_rate=state.get("success_rate"),
        failure_rate=state.get("failure_rate"),
        goodput=state.get("goodput"),
        env_load=float(state.get("env_load", state.get("load", 1.0))),
        thrash=float(state.get("thrash", state.get("retries", 0.0))),
        queue_depth=state.get("queue_depth"),
        queue_capacity=float(state.get("queue_capacity", 100.0)),
        empty_tool_rate=empty,
        budget_remaining=state.get("budget_remaining"),
        latency_p95=state.get("latency_p95"),
        n_agents=state.get("n_agents"),
        n_active=state.get("n_active"),
        concurrency=state.get("concurrency") or state.get("n_active"),
    )


def apply_hints_to_state(state: dict[str, Any], ctrl: ControlHints) -> dict[str, Any]:
    """Merge control hints into graph state (non-destructive copy)."""
    out = dict(state)
    out["eye_storm"] = ctrl.as_dict()
    out["max_concurrency"] = ctrl.max_concurrency
    out["retry_budget"] = ctrl.retry_budget
    out["request_pace"] = ctrl.request_pace
    out["cool_retries"] = ctrl.cool_retries
    out["storm_active"] = ctrl.storm_active
    out["felt_load_scale"] = ctrl.felt_load_scale
    out["pause_new_work"] = ctrl.should_pause_new_work()
    out["open_traffic"] = ctrl.open_traffic
    out["quarantine_k"] = ctrl.quarantine_k
    out["revive_k"] = ctrl.revive_k
    return out


def eye_gate_node(eye: EyeOfTheStorm | None = None, *, seed: int = 42) -> Callable[[dict], dict]:
    """
    Returns a node function: state_in → state_out with eye_storm controls.

        graph.add_node("eye_storm", eye_gate_node())
        graph.add_edge("tools", "eye_storm")
        graph.add_edge("eye_storm", "agents")
    """
    eng = eye or Eye(seed=seed, world="fleet")

    def _node(state: dict[str, Any]) -> dict[str, Any]:
        snap = snapshot_from_state(state)
        ctrl = eng.step(snap)
        return apply_hints_to_state(state, ctrl)

    return _node


class EyeStormCallback:
    """
    Minimal callback-style hook. Works without langgraph installed.
    If you use langchain callbacks, wrap on_chain_end to call `flush`.
    """

    def __init__(self, eye: EyeOfTheStorm | None = None, *, seed: int = 42, world: str = "fleet"):
        self.eye = eye or Eye(seed=seed, world=world)
        self.metrics: dict[str, Any] = {}
        self.last: ControlHints | None = None

    def update(self, **metrics: Any) -> None:
        self.metrics.update(metrics)

    def flush(self) -> ControlHints:
        snap = snapshot_from_state(self.metrics)
        self.last = self.eye.step(snap)
        return self.last

    # LangChain-style optional hooks (no import)
    def on_chain_end(self, outputs: dict[str, Any], **kwargs: Any) -> ControlHints | None:
        if isinstance(outputs, dict):
            for k in (
                "success_rate",
                "env_load",
                "thrash",
                "goodput",
                "tool_errors",
                "tool_calls",
            ):
                if k in outputs:
                    self.metrics[k] = outputs[k]
        if self.metrics:
            return self.flush()
        return None
