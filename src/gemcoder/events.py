"""Run events and filesystem-backed run storage."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class RunEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now)


@dataclass(slots=True)
class RunRecord:
    run_id: str
    task: str
    status: str = "started"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


class RunStore:
    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root)
        self.runs_dir = self.root / ".gemcoder" / "runs"

    def create_run(self, task: str) -> str:
        run_id = "run_" + uuid.uuid4().hex[:12]
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        record = RunRecord(run_id=run_id, task=task)
        (run_dir / "record.json").write_text(json.dumps(asdict(record), indent=2) + "\n")
        self.append(run_id, "run.started", {"task": task})
        return run_id

    def append(self, run_id: str, event_type: str, data: dict[str, Any] | None = None) -> None:
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        event = RunEvent(type=event_type, data=data or {})
        with (run_dir / "events.jsonl").open("a") as handle:
            handle.write(json.dumps(asdict(event), sort_keys=True) + "\n")

    def write_artifact(self, run_id: str, name: str, content: str) -> Path:
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / name
        path.write_text(content)
        return path

    def list_runs(self) -> list[str]:
        if not self.runs_dir.exists():
            return []
        return sorted(path.name for path in self.runs_dir.iterdir() if path.is_dir())

    def read_events(self, run_id: str) -> list[RunEvent]:
        path = self.runs_dir / run_id / "events.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"No events found for run: {run_id}")
        events: list[RunEvent] = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            events.append(RunEvent(**json.loads(line)))
        return events
