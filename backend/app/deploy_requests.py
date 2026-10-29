"""Updating CoachQuest from Admin → Update CoachQuest, without giving the web app Docker or root.

The API only writes a request file in DATA_DIR/deploy (kind=check or kind=deploy); deploy-agent.sh,
run each minute by cron on the server (menu.sh option 11), carries it out with the normal deploy.sh
and writes back agent.txt, versions.txt, status.txt, deploy.log and history.log, which this reads.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

from .config import settings

TARGETS = ("all", "backend", "frontend")
AGENT_STALE_S = 180  # the agent runs every minute; quiet for 3 minutes means it isn't installed or stopped


def folder() -> Path:
    return Path(settings.data_dir) / "deploy"


def _kv(name: str) -> dict:
    """key=value lines (up to a "---" line), and the lines after it under "_rest"."""
    path = folder() / name
    out: dict = {"_rest": []}
    if not path.is_file():
        return {}
    rest = False
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("---"):
            rest = True
        elif rest:
            out["_rest"].append(line)
        elif "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _tail(name: str, lines: int) -> list[str]:
    path = folder() / name
    if not path.is_file():
        return []
    return path.read_text(errors="replace").splitlines()[-lines:]


def _age_s(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    return (datetime.now(UTC) - when).total_seconds()


def state() -> dict:
    agent = _kv("agent.txt")
    versions = _kv("versions.txt")
    status = _kv("status.txt")
    age = _age_s(agent.get("seen"))
    commits = []
    for line in versions.get("_rest", []):
        parts = line.split("\t", 2)
        if len(parts) == 3:
            commits.append({"commit": parts[0], "date": parts[1], "subject": parts[2]})
    status.pop("_rest", None)
    return {
        "running": settings.build_commit,
        "agent": {"seen": agent.get("seen"), "alive": age is not None and age < AGENT_STALE_S},
        "versions": {k: v for k, v in versions.items() if k != "_rest"} or None,
        "new_commits": commits,
        "status": status or None,
        "pending": (folder() / "request.txt").is_file(),
        "log": _tail("deploy.log", 120),
        "history": list(reversed(_tail("history.log", 10))),
    }


def request(kind: str, by: str, target: str = "all") -> None:
    """Leave a request for the agent (written whole, then renamed, so it never reads half a file)."""
    if kind not in ("check", "deploy") or target not in TARGETS:
        raise ValueError("Unknown request")
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "request.txt.tmp"
    tmp.write_text(f"kind={kind}\ntarget={target}\nby={by}\nat={datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}\n")
    os.replace(tmp, d / "request.txt")
