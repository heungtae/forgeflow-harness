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
        codex_event_poll_interval_seconds=float(codex.get("event_poll_interval_seconds", 1.0)),
        codex_event_poll_max_attempts=int(codex.get("event_poll_max_attempts", 30)),
        workspace_root_dir=Path(workspace["root_dir"]),
        workspace_base_branch=workspace["base_branch"],
        workspace_branch_prefix=workspace["branch_prefix"],
        workspace_cleanup_on_failure=bool(workspace["cleanup_on_failure"]),
        workspace_max_workspaces=int(workspace["max_workspaces"]),
        validation_commands=_load_validation_commands(validation),
        validation_profiles=_load_validation_profiles(validation),
        validation_default_profile=_load_validation_default_profile(validation),
        validation_repo_profiles=_load_validation_repo_profiles(validation),
        trace_output_path=Path(trace["output_path"]),
        log_level=logging["level"],
        logger_name=logging["logger_name"],
    )


def _load_validation_commands(validation: dict[str, object]) -> list[list[str]]:
    profiles = _load_validation_profiles(validation)
    default_profile = _load_validation_default_profile(validation)
    return profiles[default_profile]


def _load_validation_profiles(validation: dict[str, object]) -> dict[str, list[list[str]]]:
    commands = validation.get("commands")
    if commands is not None:
        return {"default": _parse_command_lists(commands, "validation.commands")}

    profiles = validation.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return {"default": [["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]]}

    parsed_profiles: dict[str, list[list[str]]] = {}
    for profile_name, profile_value in profiles.items():
        if not isinstance(profile_name, str) or not profile_name:
            raise ValueError("validation.profiles keys must be non-empty strings")
        if not isinstance(profile_value, dict):
            raise ValueError(f"validation.profiles.{profile_name} must be a table with commands")
        parsed_profiles[profile_name] = _parse_command_lists(
            profile_value.get("commands"),
            f"validation.profiles.{profile_name}.commands",
        )
    return parsed_profiles


def _load_validation_default_profile(validation: dict[str, object]) -> str:
    if validation.get("commands") is not None:
        return "default"

    default_profile = validation.get("default_profile", "default")
    if not isinstance(default_profile, str) or not default_profile:
        raise ValueError("validation.default_profile must be a non-empty string")

    profiles = _load_validation_profiles(validation)
    if default_profile not in profiles:
        raise ValueError(f"validation.default_profile references unknown profile: {default_profile}")
    return default_profile


def _load_validation_repo_profiles(validation: dict[str, object]) -> dict[str, str]:
    repo_profiles = validation.get("repo_profiles", {})
    if not isinstance(repo_profiles, dict):
        raise ValueError("validation.repo_profiles must be a table of repo name to profile name")

    profiles = _load_validation_profiles(validation)
    parsed: dict[str, str] = {}
    for repo_name, profile_name in repo_profiles.items():
        if not isinstance(repo_name, str) or not repo_name:
            raise ValueError("validation.repo_profiles keys must be non-empty strings")
        if not isinstance(profile_name, str) or not profile_name:
            raise ValueError(f"validation.repo_profiles.{repo_name} must be a non-empty string")
        if profile_name not in profiles:
            raise ValueError(f"validation.repo_profiles.{repo_name} references unknown profile: {profile_name}")
        parsed[repo_name] = profile_name
    return parsed


def _parse_command_lists(raw_commands: object, field_name: str) -> list[list[str]]:
    if not isinstance(raw_commands, list) or not raw_commands:
        raise ValueError(f"{field_name} must be a non-empty list of string lists")

    parsed: list[list[str]] = []
    for command in raw_commands:
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError(f"{field_name} must be a non-empty list of string lists")
        parsed.append(command)
    return parsed
