from __future__ import annotations

import tomllib
from pathlib import Path

from forgeflow_harness.models import HarnessConfig


def load_config(path: str | Path) -> HarnessConfig:
    config_path = Path(path)
    with config_path.open("rb") as file_obj:
        raw = tomllib.load(file_obj)

    codex = raw["codex"]
    workspace = raw["workspace"]
    validation = raw.get("validation", {})
    trace = raw["trace"]
    logging = raw["logging"]

    return HarnessConfig(
        codex_base_url=codex["base_url"],
        codex_timeout_seconds=int(codex["timeout_seconds"]),
        codex_session_name=codex["session_name"],
        workspace_root_dir=Path(workspace["root_dir"]),
        workspace_base_branch=workspace["base_branch"],
        workspace_branch_prefix=workspace["branch_prefix"],
        workspace_cleanup_on_failure=bool(workspace["cleanup_on_failure"]),
        workspace_max_workspaces=int(workspace["max_workspaces"]),
        validation_commands=_load_validation_commands(validation),
        trace_output_path=Path(trace["output_path"]),
        log_level=logging["level"],
        logger_name=logging["logger_name"],
    )


def _load_validation_commands(validation: dict[str, object]) -> list[list[str]]:
    commands = validation.get("commands")
    if commands is None:
        return [["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]]

    parsed: list[list[str]] = []
    for command in commands:
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("validation.commands must be a list of non-empty string lists")
        parsed.append(command)
    return parsed
