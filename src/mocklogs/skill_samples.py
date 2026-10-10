"""Real `mocklogs` output for the skill files, rendered from a NEUTRAL fixture.

Every name is overridden to `example-*`, and only benign lines (health checks,
healthy lag, routine broker/DB activity) and refusals are shown. So the samples
match the real formats exactly but can never hint at a scenario's answer (R20).

    python -m mocklogs.skill_samples --write   # refresh the samples in .claude/skills/*/SKILL.md
    python -m mocklogs.skill_samples --check   # exit 1 if any sample is stale

In a skill file a sample is delimited by:
    <!-- mocklogs-sample: <key> -->
    ```
    ...generated...
    ```
    <!-- /mocklogs-sample -->
(optionally indented as a whole, e.g. inside a list item; the body is re-indented to match).
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from mocklogs import cli, sso
from mocklogs.render import BANNER
from mocklogs.scenarios.base import DEFAULT_T0

SKILLS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills"

NEUTRAL_NAMES = {
    "gateway_app": "example-gateway",
    "seed_app": "example-app",
    "upstream_app": "example-upstream",
    "downstream_app": "example-downstream",
    "notify_app": "example-notifier",
    "in_topic": "example.in",
    "out_topic": "example.out",
    "seed_group": "example-app-group",
    "down_group": "example-downstream-group",
    "notify_group": "example-notifier-group",
    "cluster": "example-cluster",
    "namespace": "apps",
    "bootstrap": "example-kafka:9092",
    "db_host": "example-db-host",
    "db_name": "example-db",
    "db_user": "example",
}


def _t(sec: int) -> str:
    return (DEFAULT_T0 + timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms(sec: int) -> str:
    return str(int((DEFAULT_T0 + timedelta(seconds=sec)).timestamp() * 1000))


K8S = ["--context", "example-cluster", "-n", "apps"]
BOOT = ["--bootstrap-server", "example-kafka:9092"]
PROPS = ["--property", "print.headers=true", "--property", "print.timestamp=true",
         "--property", "print.partition=true", "--property", "print.offset=true"]

# key -> (argv, access_denied entries, logged in?)
SAMPLES: Dict[str, Tuple[List[str], List[str], bool]] = {
    "app-logs/output": (["kubectl", "logs", "deploy/example-gateway", *K8S, "--timestamps",
                         f"--since-time={_t(0)}", f"--until-time={_t(25)}"], [], True),
    "app-logs/sso": (["kubectl", "logs", "deploy/example-app", *K8S, "--timestamps"], [], False),
    "app-logs/forbidden": (["kubectl", "logs", "deploy/example-app", *K8S, "--timestamps"],
                           ["logs:example-app"], True),
    "app-logs/not-found": (["kubectl", "logs", "deploy/example-missing", *K8S, "--timestamps"], [], True),
    "app-config/output": (["kubectl", "get", "configmap", "example-downstream-config", *K8S, "-o", "json"], [], True),
    "app-config/forbidden": (["kubectl", "get", "configmap", "example-downstream-config", *K8S, "-o", "json"],
                             ["config:example-downstream"], True),
    "app-config/not-found": (["kubectl", "get", "configmap", "example-missing-config", *K8S, "-o", "json"], [], True),
    "kafka/sso": (["kafka-get-offsets", *BOOT, "--topic", "example.in", "--time", "-1"], [], False),
    "kafka/forbidden": (["kafka-get-offsets", *BOOT, "--topic", "example.in", "--time", "-1"],
                        ["kafka-topic:example.in"], True),
    "kafka/unreachable": (["kafka-get-offsets", "--bootstrap-server", "example-other:9092", "--topic", "example.in",
                           "--time", "-1"], [], True),
    "kafka/lag": (["kafka-consumer-groups", *BOOT, "--describe", "--group", "example-downstream-group",
                   "--samples", "2"], [], True),
    "kafka/offsets": (["kafka-get-offsets", *BOOT, "--topic", "example.in", "--time", _ms(60)], [], True),
    "kafka/messages": (["kafka-console-consumer", *BOOT, "--topic", "example.in", "--partition", "0",
                        "--offset", "1180", "--max-messages", "1", *PROPS], [], True),
    "kafka/logs": (["kafka", "logs", *BOOT, "--component", "broker", "--topic", "example.out",
                    f"--since-time={_t(0)}", f"--until-time={_t(60)}"], [], True),
    "db-logs/output": (["db", "logs", "--host", "example-db-host", "--db", "example-db",
                        f"--since-time={_t(0)}", f"--until-time={_t(21)}"], [], True),
    "db-logs/forbidden": (["db", "logs", "--host", "example-db-host", "--db", "example-db"], ["db:example-db"], True),
    "db-logs/unreachable": (["db", "logs", "--host", "example-other-host", "--db", "example-db"], [], True),
}


def _render_one(argv: List[str], denied: List[str], logged_in: bool) -> str:
    saved = {k: os.environ.get(k) for k in ("MOCKLOGS_HOME", "MOCKLOGS_SCENARIO", "MOCKLOGS_KNOBS")}
    with tempfile.TemporaryDirectory() as home:
        try:
            os.environ["MOCKLOGS_HOME"] = home
            os.environ["MOCKLOGS_SCENARIO"] = "upstream-timeout"
            os.environ["MOCKLOGS_KNOBS"] = json.dumps({"names": NEUTRAL_NAMES, "access_denied": denied})
            if logged_in:
                sso.login()
            res = cli.run(argv)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    command = "mocklogs " + " ".join(argv)
    body = "\n".join([BANNER] + res.out + res.err)
    return f"$ {command}\n{body}\n# exit code {res.code}"


def generate() -> Dict[str, str]:
    return {key: _render_one(*spec) for key, spec in SAMPLES.items()}


BLOCK = re.compile(
    r"(?P<ind>[ ]*)<!-- mocklogs-sample: (?P<key>[\w/-]+) -->\n(?P=ind)```\n(?P<body>.*?)\n(?P=ind)```\n"
    r"(?P=ind)<!-- /mocklogs-sample -->", re.S)


def apply(text: str, samples: Dict[str, str]) -> str:
    def sub(m: "re.Match[str]") -> str:
        key, ind = m.group("key"), m.group("ind")
        if key not in samples:
            raise KeyError(f"unknown sample key {key!r}")
        body = "\n".join(ind + line if line else line for line in samples[key].split("\n"))
        return (f"{ind}<!-- mocklogs-sample: {key} -->\n{ind}```\n{body}\n{ind}```\n"
                f"{ind}<!-- /mocklogs-sample -->")
    return BLOCK.sub(sub, text)


def used_keys(text: str) -> List[str]:
    return [m.group("key") for m in BLOCK.finditer(text)]


def main(argv: Optional[List[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    mode = args[0] if args else "--check"
    samples = generate()
    stale = []
    for path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        new = apply(text, samples)
        if new != text:
            stale.append(path)
            if mode == "--write":
                path.write_text(new, encoding="utf-8")
    for path in stale:
        print(f"{'updated' if mode == '--write' else 'stale'}: {path.relative_to(SKILLS_DIR.parent.parent)}")
    return 1 if stale and mode == "--check" else 0


if __name__ == "__main__":
    sys.exit(main())
