"""Scripted fake LLMs for tests (no API key needed).

`ScriptedInvestigator` behaves like a model following the skills: it collects from the plan
suggestions, correlates, optionally investigates further, chooses a cause, scores it, and submits a
report. It only uses what the tools return (it never peeks at the mock world). Switches make it
misbehave in the ways the guardrails must handle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from investigator.agent.provider import AssistantTurn, ToolCall, ToolSpec


def _rfc(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ScriptedInvestigator:
    extra_fetch: bool = False        # investigate beyond the suggestions (a wider window on the seed app)
    try_forbidden: bool = False      # try a command the guard must deny, then carry on
    own_cause: bool = False          # propose its own cause instead of the top lead, first over-claiming HIGH
    bogus_first: bool = False        # first report cites an invented event ID
    never_valid: bool = False        # every report is invalid (fallback test)
    loop_forever: bool = False       # keeps asking for the plan (turn-budget test)
    phase: str = "collect"
    calls: int = 0
    summary: Optional[Dict[str, Any]] = None
    scored: Optional[Dict[str, Any]] = None
    attempt: int = 0
    own_cause_overclaim: bool = False
    log: List[str] = field(default_factory=list)

    # --- helpers ------------------------------------------------------------------------
    def _id(self) -> str:
        self.calls += 1
        return f"call-{self.calls}"

    def _call(self, name: str, **args) -> AssistantTurn:
        self.log.append(name)
        return AssistantTurn(text=f"next: {name}", tool_calls=[ToolCall(self._id(), name, args)])

    @staticmethod
    def _last_result(messages, name) -> Optional[Dict[str, Any]]:
        for m in reversed(messages):
            if m["role"] == "tool" and m["name"] == name:
                return json.loads(m["content"])
        return None

    @staticmethod
    def _incident(messages) -> Dict[str, Any]:
        first = next(m["content"] for m in messages if m["role"] == "user")
        workdir = first.splitlines()[0].split("workdir: ", 1)[1]
        seed = json.loads(next(l for l in first.splitlines() if l.startswith("seed: "))[len("seed: "):])
        app_line = next((l for l in first.splitlines() if l.startswith("app:")), "")
        pairs = dict(t.split("=", 1) for t in app_line.split()[1:] if "=" in t)
        return {"workdir": workdir, "seed": seed, "cluster": pairs.get("cluster"), "namespace": pairs.get("namespace")}

    # --- the policy -----------------------------------------------------------------------
    def respond(self, messages: List[Dict[str, Any]], tools: List[ToolSpec]) -> AssistantTurn:
        if self.loop_forever:
            return self._call("plan")
        if self.phase == "collect":
            plan = self._last_result(messages, "plan") if messages[-1]["role"] == "tool" else None
            if plan is None or messages[-1]["name"] != "plan":
                return self._call("plan")
            if plan["done"]:
                self.phase = "extra" if (self.extra_fetch or self.try_forbidden) else "correlate"
                return self.respond(messages, tools)
            calls = [ToolCall(self._id(), "run", {"argv": s["argv"], "reason": s["reason"]}) for s in plan["steps"]]
            calls.append(ToolCall(self._id(), "plan", {}))
            self.log.append(f"run x{len(calls) - 1}")
            return AssistantTurn(text="collecting the suggested fetches", tool_calls=calls)
        if self.phase == "extra":
            self.phase = "correlate"
            inc = self._incident(messages)
            calls = []
            if self.extra_fetch and inc["cluster"]:
                ts = datetime.fromisoformat(inc["seed"]["ts"].replace("Z", "+00:00"))
                calls.append(ToolCall(self._id(), "run", {
                    "argv": ["mocklogs", "kubectl", "logs", f"deploy/{inc['seed']['app']}", "--context", inc["cluster"],
                             "-n", inc["namespace"], "--timestamps", f"--since-time={_rfc(ts - timedelta(minutes=30))}",
                             f"--until-time={_rfc(ts + timedelta(minutes=5))}", "--grep", "ERROR",
                             "--save-dir", inc["workdir"]],
                    "reason": "widen the window: were there earlier errors in the seed app?"}))
            if self.try_forbidden:
                calls.append(ToolCall(self._id(), "run", {
                    "argv": ["mocklogs", "kubectl", "logs", "deploy/some-undeclared-app", "--context",
                             inc["cluster"] or "x", "-n", inc["namespace"] or "x", "--save-dir", inc["workdir"]],
                    "reason": "check an app the config doesn't mention"}))
            self.log.append("extra")
            return AssistantTurn(text="digging further", tool_calls=calls or [ToolCall(self._id(), "plan", {})])
        if self.phase == "correlate":
            self.phase = "score"
            return self._call("correlate")
        if self.phase == "score":
            self.summary = self._last_result(messages, "correlate")
            cause = self._choose_cause()
            if cause is None:
                self.phase = "report"
                return self.respond(messages, tools)
            self.phase = "report"
            return self._call("score", cause_event_id=cause)
        if self.phase == "report":
            if self.scored is None and self.log and self.log[-1] == "score":
                self.scored = self._last_result(messages, "score")
            self.phase = "fix"
            return self._submit()
        if self.phase == "fix":
            result = self._last_result(messages, "submit_report")
            codes = {e["code"] for e in result["errors"]}
            if "confidence_above_ceiling" in codes or "insufficient_with_cause" in codes:
                if self.scored and self.scored["ceiling"] == "INSUFFICIENT":
                    self.scored = None  # an honest unknown instead
                self.own_cause_overclaim = False
            self.bogus_first = False
            return self._submit()
        return AssistantTurn(text="done")

    def _choose_cause(self) -> Optional[str]:
        s = self.summary
        leads = sorted(s["leads"], key=lambda h: ["INSUFFICIENT", "LOW", "MEDIUM", "HIGH"].index(h["ceiling"]),
                       reverse=True)
        if self.own_cause:
            seed_id = s["seed"]["event_id"] if s["seed"] else None
            lead_causes = {h["cause"]["event_id"] for h in leads if isinstance(h["cause"], dict)}
            others = [e for e in s["timeline"] if e["event_id"] not in lead_causes and e["event_id"] != seed_id
                      and s["seed"] and e["ts"] and e["ts"] < s["seed"]["ts"]]
            if others:
                self.own_cause_overclaim = True
                return others[0]["event_id"]
        if leads and leads[0]["ceiling"] != "INSUFFICIENT":
            return leads[0]["cause"]["event_id"]
        return None

    def _submit(self) -> AssistantTurn:
        self.attempt += 1
        return self._call("submit_report", report=self._report())

    def _report(self) -> Dict[str, Any]:
        s = self.summary
        seed = s["seed"]
        gaps = [{"target": g["target"], "reason": g["reason"], "impact": "less evidence from this source"}
                for g in s["gaps"]]
        base = {"summary": "", "correlation_id": s["seed_correlation_id"],
                "downstream_symptoms": [{"statement": "the seed error", "event_ids": [seed["event_id"]]}],
                "gaps": gaps, "ai_interpretations": [], "next_steps": ["Confirm the cause with the owning team."]}
        leads = s["leads"]
        if self.scored is None:
            report = {**base, "summary": "The evidence doesn't support a root cause.", "root_cause": "unknown",
                      "timeline": [{"event_id": seed["event_id"], "note": "the seed error"}], "evidence": [],
                      "alternative_hypotheses": [{"statement": h["summary"], "event_ids": [h["cause"]["event_id"]],
                                                  "status": "open", "why": f"lead with ceiling {h['ceiling']}"}
                                                 for h in leads if isinstance(h["cause"], dict)],
                      "confidence": {"level": "INSUFFICIENT", "factors": []}}
        else:
            cause = self.scored["cause_event_id"]
            lead = next((h for h in leads if isinstance(h["cause"], dict) and h["cause"]["event_id"] == cause), None)
            evidence = [cause] + ([e for e in lead["effect_event_ids"] if e != cause][:4] if lead else [])
            ts = {e["event_id"]: e["ts"] for e in s["timeline"]}
            ts.setdefault(seed["event_id"], seed["ts"])
            ordered = sorted({cause, seed["event_id"]}, key=lambda e: ts.get(e) or "")
            level = "HIGH" if self.own_cause_overclaim else self.scored["ceiling"]
            report = {**base,
                      "summary": f"Cause chosen by the AI ({'own pick' if not lead else 'agrees with a lead'}).",
                      "root_cause": {"statement": "see evidence", "cause_event_id": cause,
                                     "evidence_event_ids": evidence, "source": "detector" if lead else "ai"},
                      "timeline": [{"event_id": e, "note": "step"} for e in ordered],
                      "evidence": [{"event_id": e, "why": "supports the cause"} for e in evidence],
                      "alternative_hypotheses": [{"statement": h["summary"], "event_ids": [h["cause"]["event_id"]],
                                                  "status": "rejected", "why": "the AI preferred another cause"}
                                                 for h in leads if isinstance(h["cause"], dict)
                                                 and h["cause"]["event_id"] != cause],
                      "confidence": {"level": level, "factors": [{"name": f["name"], "value": f["value"],
                                                                   "reason": f["reason"]}
                                                                  for f in self.scored["factors"]]}}
        if self.bogus_first:
            report["evidence"] = report["evidence"] + [{"event_id": "ev-invented-by-the-model", "why": "trust me"}]
        if self.never_valid:
            report["confidence"]["level"] = "CERTAIN"
        return report
