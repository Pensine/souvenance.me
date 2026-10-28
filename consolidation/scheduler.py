"""Cycle clock for the Docker install: a tiny cron, with no system
daemon or third-party binary.

Reads a crontab-format table (five fields + command, by default
deploy/docker/crontab) and launches each cycle at its time, one after the
other — two cycles never overlap: if consolidation runs over into the
Sunday REM time, the REM starts right after, it is not skipped. Output of
each command: on screen (docker logs) and in PENSINE_LOG_DIR/<cycle>.log.

At startup, the local copy of GeoNames is installed if missing
(PENSINE_GEONAMES_AUTO=1): public data, no personal data leaves.
"""

import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TABLE = ROOT / "deploy" / "docker" / "crontab"
RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]


def parse_field(field: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = b = int(part)
        if not (lo <= a <= hi and lo <= b <= hi) or step < 1:
            raise ValueError(f"cron field out of bounds: {field}")
        out.update(range(a, b + 1, step))
    if hi == 7 and 7 in out:  # Sunday is also written as 7
        out.add(0)
    return out


class Job:
    def __init__(self, line: str):
        parts = line.split(None, 5)
        if len(parts) < 6:
            raise ValueError(f"incomplete cron line: {line!r}")
        self.spec = parts[:5]
        self.command = parts[5]
        raw = self.spec
        self.fields = [parse_field(f, lo, hi) for f, (lo, hi) in zip(raw, RANGES)]
        self.dom_any, self.dow_any = self.spec[2] == "*", self.spec[4] == "*"
        self.name = _name(self.command)

    def matches(self, t: datetime) -> bool:
        minute, hour, dom, month, dow = self.fields
        if t.minute not in minute or t.hour not in hour or t.month not in month:
            return False
        day_ok, wday_ok = t.day in dom, (t.isoweekday() % 7) in dow
        if self.dom_any or self.dow_any:  # cron rule: OR if both are set
            return day_ok and wday_ok
        return day_ok or wday_ok

    def next_after(self, t: datetime) -> datetime:
        t = t.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(366 * 24 * 60):
            if self.matches(t):
                return t
            t += timedelta(minutes=1)
        raise ValueError(f"never scheduled: {' '.join(self.spec)}")


def _name(command: str) -> str:
    for token in shlex.split(command):
        if token.endswith((".py", ".sh")):
            return Path(token).stem
    return "cycle"


def load(path: Path) -> list[Job]:
    jobs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            jobs.append(Job(line))
    return jobs


def run(job: Job) -> int:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(config.LOG_DIR / f"{job.name}.log", "a", encoding="utf-8") as log:
        header = f"== {stamp} {job.command}\n"
        sys.stdout.write(header)
        log.write(header)
        proc = subprocess.Popen(job.command, shell=True, cwd=ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in proc.stdout:
            sys.stdout.write(line)
            log.write(line)
        code = proc.wait()
        footer = f"== end {job.name} (code {code})\n"
        sys.stdout.write(footer)
        log.write(footer)
        sys.stdout.flush()
    return code


def ensure_geonames() -> None:
    if os.environ.get("PENSINE_GEONAMES_AUTO", "0") != "1":
        return
    if (config.GEO_DIR / "cities1000.txt").exists():
        return
    print("GeoNames missing — installing the local copy…", flush=True)
    if subprocess.run(["bash", str(ROOT / "scripts" / "install_geonames.sh")],
                      cwd=ROOT).returncode != 0:
        print("GeoNames not installed (retry at next startup) — "
              "places stay unnamed, nothing else changes.", flush=True)


def main(table: Path = DEFAULT_TABLE) -> None:
    jobs = load(table)
    ensure_geonames()
    now = datetime.now()
    due = {id(j): j.next_after(now) for j in jobs}
    for j in jobs:
        print(f"{j.name}: next run {due[id(j)]:%Y-%m-%d %H:%M}", flush=True)
    while True:
        now = datetime.now()
        for j in sorted(jobs, key=lambda j: due[id(j)]):
            if due[id(j)] <= now:
                run(j)
                due[id(j)] = j.next_after(datetime.now())
        wait = (min(due.values()) - datetime.now()).total_seconds()
        time.sleep(max(1.0, min(wait, 60.0)))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TABLE)
