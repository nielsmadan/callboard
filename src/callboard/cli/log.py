import argparse
import json
from collections.abc import Mapping
from datetime import datetime

from callboard.cli.presentation import emit
from callboard.jsonout import ok_payload
from callboard.models import Runtime
from callboard.text import one_line
from callboard.trace import read_events, trace_path

HEAD = ("at", "pid", "event")


def clock_time(at: object) -> str:
    try:
        moment = datetime.fromisoformat(str(at)).astimezone()
    except ValueError:
        return str(at)
    return moment.strftime("%H:%M:%S.") + f"{moment.microsecond // 1000:03d}"


def shown(value: object) -> str:
    if not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False) if not value or " " in value else value


def event_line(event: Mapping[str, object]) -> str:
    fields = " ".join(f"{name}={shown(value)}" for name, value in event.items() if name not in HEAD)
    head = f"{clock_time(event.get('at'))} [{event.get('pid')}] {event.get('event')}"
    return one_line(f"{head} {fields}".rstrip())


def log(args: argparse.Namespace, runtime: Runtime) -> int:
    path = trace_path(runtime.env)
    events = read_events(runtime.env, count=args.lines, words=args.words, failures=args.errors)
    lines = [event_line(event) for event in events] or [f"no matching events in {path}"]
    emit(ok_payload({"file": str(path), "events": events}), lines, json_mode=args.json)
    return 0
