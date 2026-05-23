"""GemCoder harness runner."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from gemcoder.config import GemCoderConfig, load_config
from gemcoder.events import RunStore
from gemcoder.google_sources import build_google_sources
from gemcoder.managed import ManagedAgentClient, ManagedAgentError, ManagedAgentResult
from gemcoder.task_packet import build_task_packet, collect_context_files, load_skills
from gemcoder.verify import VerificationResult, run_verification


@dataclass(slots=True)
class HarnessRunResult:
    run_id: str
    summary: str
    patch_path: str | None = None
    verification: list[VerificationResult] | None = None


@dataclass(slots=True)
class HarnessBuildResult:
    build_id: str
    build_dir: Path
    manifest_path: Path
    harness_path: Path
    task_template_path: Path
    instructions_path: Path
    skills_bundle_path: Path
    google_sources_path: Path


def _build_id() -> str:
    return "hbuild_" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")


class HarnessRunner:
    """Owns the repeatable GemCoder run lifecycle."""

    def __init__(self, root: str | Path = ".", config: GemCoderConfig | None = None) -> None:
        self.root = Path(root)
        self.config = config or load_config(self.root)
        self.store = RunStore(self.root)

    def inspect_harness(self) -> dict[str, object]:
        """Return the user-defined harness surface loaded for this repo."""
        instructions_path = self.root / self.config.harness.instructions
        skills = load_skills(self.root, self.config)
        context_files = collect_context_files(self.root, self.config)
        return {
            "project": self.config.project.name,
            "instructions": str(instructions_path),
            "instructions_exists": instructions_path.exists(),
            "skills": sorted(skills),
            "context_files": context_files,
            "verification_commands": self.config.verification.commands,
            "patch_format": self.config.harness.patch_format,
        }

    def build(self) -> HarnessBuildResult:
        """Compile editable harness files into a stable build artifact."""
        build_id = _build_id()
        build_dir = self.root / ".gemcoder" / "build" / build_id
        build_dir.mkdir(parents=True, exist_ok=True)

        instructions = self._read_instructions()
        skills = load_skills(self.root, self.config)
        manifest = {
            "build_id": build_id,
            "created_at": datetime.now(UTC).isoformat(),
            "harness": self.inspect_harness(),
            "source_files": {
                "config": "gemcoder.yaml",
                "instructions": self.config.harness.instructions,
                "skills_dir": self.config.harness.skills_dir,
            },
            "artifacts": {
                "manifest": "manifest.json",
                "harness": "harness.json",
                "task_template": "task-template.yaml",
                "managed_agent_instructions": "managed-agent-instructions.md",
                "skills_bundle": "skills-bundle.md",
                "google_sources": "google-sources.json",
            },
        }
        harness_payload = {
            "config": self.config.model_dump(mode="json"),
            "instructions": instructions,
            "skills": skills,
            "context_files": collect_context_files(self.root, self.config),
        }
        task_template = {
            "goal": "<task>",
            "repo": {
                "name": self.config.project.name,
                "test_commands": self.config.verification.commands,
                "context_files": collect_context_files(self.root, self.config),
            },
            "return_contract": {
                "patch": self.config.harness.patch_format,
                "changed_files": "list",
                "commands_run": "list",
                "test_result": "summary",
                "final_summary": "short",
            },
        }

        manifest_path = build_dir / "manifest.json"
        harness_path = build_dir / "harness.json"
        task_template_path = build_dir / "task-template.yaml"
        instructions_path = build_dir / "managed-agent-instructions.md"
        skills_bundle_path = build_dir / "skills-bundle.md"
        google_sources_path = build_dir / "google-sources.json"

        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        harness_path.write_text(json.dumps(harness_payload, indent=2) + "\n")
        task_template_path.write_text(yaml.safe_dump(task_template, sort_keys=False))
        instructions_path.write_text(instructions)
        skills_bundle_path.write_text(self._render_skills_bundle(skills))
        google_sources_path.write_text(
            json.dumps(build_google_sources(self.root, self.config), indent=2) + "\n"
        )

        current_path = self.root / ".gemcoder" / "build" / "current.json"
        current_path.write_text(
            json.dumps({"build_id": build_id, "path": str(build_dir)}, indent=2) + "\n"
        )

        return HarnessBuildResult(
            build_id=build_id,
            build_dir=build_dir,
            manifest_path=manifest_path,
            harness_path=harness_path,
            task_template_path=task_template_path,
            instructions_path=instructions_path,
            skills_bundle_path=skills_bundle_path,
            google_sources_path=google_sources_path,
        )

    def current_build_manifest(self) -> dict[str, object] | None:
        current_path = self.root / ".gemcoder" / "build" / "current.json"
        if not current_path.exists():
            return None
        current = json.loads(current_path.read_text())
        build_path = Path(str(current["path"]))
        manifest_path = build_path / "manifest.json"
        if not manifest_path.exists():
            return None
        manifest = json.loads(manifest_path.read_text())
        manifest["manifest_path"] = str(manifest_path.relative_to(self.root))
        return manifest

    def run(self, task: str) -> HarnessRunResult:
        run_id = self.store.create_run(task)
        self.store.append(run_id, "harness.loaded", self.inspect_harness())
        build_manifest = self.current_build_manifest()
        if build_manifest is not None:
            self.store.append(run_id, "harness.build.loaded", build_manifest)

        preflight = self._maybe_answer_from_verification(run_id, task)
        if preflight is not None:
            return preflight

        packet = build_task_packet(self.root, task, self.config)
        self.store.append(run_id, "task.packet.created")
        self.store.write_artifact(run_id, "task-packet.yaml", packet)

        client = ManagedAgentClient(self.config, self.root)
        self.store.append(
            run_id,
            "managed.interaction.started",
            {"provider": self.config.managed_agent.provider},
        )
        try:
            managed_result = client.run_task(packet)
        except ManagedAgentError as exc:
            managed_result = ManagedAgentResult(
                summary=f"Managed Agent request failed: {exc}",
                request=json.dumps(client.build_interaction_payload(packet), indent=2) + "\n",
            )
            self.store.append(
                run_id,
                "managed.interaction.failed",
                {"error": str(exc)},
            )
        self._store_managed_result(run_id, managed_result)

        patch_path: str | None = None
        if managed_result.patch:
            path = self.store.write_artifact(run_id, "patch.diff", managed_result.patch)
            patch_path = str(path.relative_to(self.root))
            self.store.append(run_id, "patch.received", {"path": patch_path})
        else:
            self.store.append(run_id, "patch.empty")

        return HarnessRunResult(
            run_id=run_id,
            summary=managed_result.summary,
            patch_path=patch_path,
        )

    def _maybe_answer_from_verification(
        self, run_id: str, task: str
    ) -> HarnessRunResult | None:
        lowered = task.lower()
        if "failing test" not in lowered and "failing tests" not in lowered:
            return None
        if not self.config.verification.commands:
            return None

        self.store.append(
            run_id,
            "verification.preflight.started",
            {"commands": self.config.verification.commands},
        )
        results = run_verification(self.root, self.config.verification.commands)
        for result in results:
            status = "pass" if result.returncode == 0 else "fail"
            self.store.append(
                run_id,
                "verification.command",
                {"command": result.command, "status": status},
            )
        if not results or any(result.returncode != 0 for result in results):
            self.store.append(run_id, "verification.preflight.failed")
            return None

        self.store.append(run_id, "verification.preflight.passed")
        summary = (
            "I ran the configured verification commands and they already pass, "
            "so there are no failing tests to fix."
        )
        self._store_managed_result(run_id, ManagedAgentResult(summary=summary))
        self.store.append(run_id, "patch.empty")
        return HarnessRunResult(run_id=run_id, summary=summary)

    def verify(self, run_id: str | None = None) -> list[VerificationResult]:
        selected = run_id or self.latest_run_id() or "manual"
        self.store.append(
            selected,
            "verification.started",
            {"commands": self.config.verification.commands},
        )
        results = run_verification(self.root, self.config.verification.commands)
        for result in results:
            status = "pass" if result.returncode == 0 else "fail"
            self.store.append(
                selected,
                "verification.command",
                {"command": result.command, "status": status},
            )
        if results and all(result.returncode == 0 for result in results):
            self.store.append(selected, "verification.passed")
        elif results:
            self.store.append(selected, "verification.failed")
        else:
            self.store.append(selected, "verification.skipped")
        return results

    def latest_run_id(self) -> str | None:
        runs = self.store.list_runs()
        return runs[-1] if runs else None

    def _store_managed_result(self, run_id: str, result: ManagedAgentResult) -> None:
        self.store.append(run_id, "managed.result.received", {"summary": result.summary})
        if result.request:
            self.store.write_artifact(run_id, "managed-request.json", result.request)
        if result.raw:
            self.store.write_artifact(run_id, "managed-response.json", result.raw)
        self.store.write_artifact(
            run_id,
            "managed-result.json",
            json.dumps(asdict(result), indent=2) + "\n",
        )

    def _read_instructions(self) -> str:
        path = self.root / self.config.harness.instructions
        return path.read_text(errors="replace") if path.exists() else ""

    @staticmethod
    def _render_skills_bundle(skills: dict[str, str]) -> str:
        sections: list[str] = []
        for name, content in sorted(skills.items()):
            sections.append(f"<!-- skill: {name} -->\n\n{content.strip()}\n")
        return "\n---\n\n".join(sections) + ("\n" if sections else "")
