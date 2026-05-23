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

    def list_run_summaries(self) -> list[dict[str, Any]]:
        if not self.runs_dir.exists():
            return []
        summaries: list[dict[str, Any]] = []
        for run_dir in self.runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            record_path = run_dir / "record.json"
            if not record_path.exists():
                continue
            record = json.loads(record_path.read_text())
            run_summary: dict[str, Any] = {}
            summary_path = run_dir / "run-summary.json"
            if summary_path.exists():
                run_summary = json.loads(summary_path.read_text())
            task = str(record.get("task", ""))
            summaries.append(
                {
                    "run_id": run_dir.name,
                    "created_at": record.get("created_at", ""),
                    "status": run_summary.get("status") or record.get("status", "unknown"),
                    "backend": run_summary.get("backend"),
                    "patch_present": bool(run_summary.get("patch_present"))
                    or (run_dir / "patch.diff").exists(),
                    "task": task[:80],
                }
            )
        summaries.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return summaries

    def latest_run_id(self) -> str | None:
        summaries = self.list_run_summaries()
        return summaries[0]["run_id"] if summaries else None

    def list_runs(self) -> list[str]:
        return [summary["run_id"] for summary in self.list_run_summaries()]

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
