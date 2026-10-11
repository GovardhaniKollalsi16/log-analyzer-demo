"""`investigator check`: allow or deny ONE command the AI wants to run (D31).

The AI investigates freely; this guard checks every command against the rules the user set:
  - only the tool's documented, read-only fetch commands, with documented flags only;
  - no shell metacharacters (the runner never uses a shell, but the argv must be clean anyway);
  - output saved to the investigation's workdir (`--save-dir <workdir>`);
  - WHERE (cluster/namespace, Kafka bootstrap/topics, DB host/name) only from the incident (D22, D27);
  - WHO (which related apps) only from the seed app's config (D26). The seed config is the only config;
  - Kafka collection scope (D28): consumer-group lag isn't collected yet (D29).
Every denial carries a machine-readable reason code, so the AI can adjust instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from investigator.models import AppTopology, Incident

TOOL = "mocklogs"
SHELL_META = set(";|&$`<>\\\n\r") | {"$("}

# command shape -> flags it may carry (documented in the component skills)
FLAGS: Dict[str, Set[str]] = {
    "kubectl logs": {"--context", "-n", "--namespace", "--timestamps", "--since-time", "--until-time", "--grep",
                     "--instance", "--thread", "--save-dir"},
    "kubectl get": {"--context", "-n", "--namespace", "-o", "--output", "--save-dir"},
    "kafka-get-offsets": {"--bootstrap-server", "--topic", "--time", "--save-dir"},
    "kafka-console-consumer": {"--bootstrap-server", "--topic", "--partition", "--offset", "--max-messages",
                               "--property", "--grep", "--from-beginning", "--save-dir"},
    "kafka logs": {"--bootstrap-server", "--component", "--topic", "--since-time", "--until-time", "--save-dir"},
    "db logs": {"--host", "--db", "--since-time", "--until-time", "--grep", "--save-dir"},
}
VALUELESS = {"--timestamps", "--from-beginning"}


@dataclass
class Verdict:
    allowed: bool
    reasons: List[Dict[str, str]] = field(default_factory=list)  # [{"code": ..., "detail": ...}]
    shape: Optional[str] = None

    def deny(self, code: str, detail: str) -> None:
        self.allowed = False
        self.reasons.append({"code": code, "detail": detail})


def _options(args: List[str], v: Verdict, allowed: Set[str]) -> Dict[str, List[str]]:
    """Parse `--flag value`, `--flag=value` and valueless flags. Unknown flags are denied."""
    opts: Dict[str, List[str]] = {}
    i = 0
    while i < len(args):
        a = args[i]
        if not a.startswith("-"):
            opts.setdefault("_positional", []).append(a)
            i += 1
            continue
        name, eq, val = a.partition("=")
        if name not in allowed:
            v.deny("flag_not_allowed", f"{name} isn't a documented flag for this command")
            i += 1
            continue
        if name in VALUELESS:
            opts.setdefault(name, []).append("")
            i += 1
        elif eq:
            opts.setdefault(name, []).append(val)
            i += 1
        else:
            opts.setdefault(name, []).append(args[i + 1] if i + 1 < len(args) else "")
            i += 2
    return opts


def _one(opts: Dict[str, List[str]], *names: str) -> Optional[str]:
    for n in names:
        if opts.get(n):
            return opts[n][-1]
    return None


def check(argv: List[str], incident: Incident, topology: Optional[AppTopology], workdir: str) -> Verdict:
    v = Verdict(allowed=True)
    if not argv or argv[0] != TOOL:
        v.deny("unknown_tool", f"only `{TOOL}` fetch commands are checked here")
        return v
    for a in argv:
        if any(m in a for m in SHELL_META):
            v.deny("shell_metachar", f"argument {a!r} contains a shell metacharacter")
    args = argv[1:]
    shape = " ".join(args[:2]) if args[:1] in (["kubectl"], ["kafka"], ["db"]) else (args[0] if args else "")
    v.shape = shape
    if shape not in FLAGS:
        if shape.startswith("kafka-consumer-groups"):
            v.deny("not_in_collection_scope", "consumer-group lag isn't part of collection (D28/D29)")
        elif shape.split(" ")[0] in ("sso", "scenario"):
            v.deny("not_allowed_for_agent", "login and scenario commands are for the user/harness only")
        else:
            v.deny("unknown_command", f"`{shape}` isn't a documented fetch command")
        return v
    rest = args[2:] if " " in shape else args[1:]
    opts = _options(rest, v, FLAGS[shape])
    save = _one(opts, "--save-dir")
    if save is None or Path(save).resolve() != Path(workdir).resolve():
        v.deny("save_dir_missing", f"output must be saved with --save-dir {workdir}")

    seed = incident.seed
    if shape in ("kubectl logs", "kubectl get"):
        cluster, ns = _one(opts, "--context"), _one(opts, "-n", "--namespace")
        pos = opts.get("_positional", [])
        if shape == "kubectl get":
            if pos[:1] != ["configmap"] or len(pos) < 2:
                v.deny("unknown_command", "only `kubectl get configmap <seed app>-config` is allowed")
                return v
            if pos[1] != f"{seed.app}-config":
                v.deny("config_not_seed", "only the seed app's config may be read (D26)")
            app = seed.app
        else:
            target = pos[0] if pos else ""
            if not target.startswith("deploy/"):
                v.deny("unknown_command", "logs target must be deploy/<app>")
                return v
            app = target.split("/", 1)[1]
        if app == seed.app:
            loc = incident.app
            if loc is None:
                v.deny("input_missing", "the incident has no `app:` line (no input, no access)")
        else:
            declared = set(topology.upstream_apps + topology.downstream_apps) if topology else set()
            if app not in declared:
                v.deny("app_not_related", f"{app} isn't declared as upstream/downstream in the seed config (D26)")
            loc = incident.related_apps.get(app)
            if loc is None:
                v.deny("input_missing", f"the incident has no `app[{app}]:` line (no input, no access)")
        if loc is not None and (cluster, ns) != (loc.cluster, loc.namespace):
            v.deny("location_mismatch",
                   f"{app} must be read from cluster {loc.cluster} / namespace {loc.namespace} (from the incident)")
    elif shape.startswith("kafka"):
        if not incident.kafka_bootstrap:
            v.deny("input_missing", "the incident has no `kafka:` line (no input, no access)")
        elif _one(opts, "--bootstrap-server") != incident.kafka_bootstrap:
            v.deny("location_mismatch", f"Kafka cluster must be {incident.kafka_bootstrap} (from the incident)")
        topic = _one(opts, "--topic")
        if incident.kafka_topics and topic not in incident.kafka_topics:
            v.deny("topic_not_in_incident", f"topic {topic!r} isn't listed in the incident")
    elif shape == "db logs":
        if not incident.db_host or not incident.db_name:
            v.deny("input_missing", "the incident has no `db:` line (no input, no access)")
        elif (_one(opts, "--host"), _one(opts, "--db")) != (incident.db_host, incident.db_name):
            v.deny("location_mismatch", f"DB must be {incident.db_host}/{incident.db_name} (from the incident)")
    return v
