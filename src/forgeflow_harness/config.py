from __future__ import annotations

import tomllib
from pathlib import Path

from forgeflow_harness.models import CommandPolicyRule, FilePolicyRule, HarnessConfig


def load_config(path: str | Path) -> HarnessConfig:
    config_path = Path(path)
    with config_path.open("rb") as file_obj:
        raw = tomllib.load(file_obj)

    codex = raw["codex"]
    workspace = raw["workspace"]
    validation = raw.get("validation", {})
    review = raw.get("review", {})
    guardrail = raw.get("guardrail", {})
    trace = raw["trace"]
    logging = raw["logging"]

    return HarnessConfig(
        codex_base_url=codex["base_url"],
        codex_timeout_seconds=int(codex["timeout_seconds"]),
        codex_session_name=codex["session_name"],
        codex_event_poll_interval_seconds=float(codex.get("event_poll_interval_seconds", 1.0)),
        codex_event_poll_max_attempts=int(codex.get("event_poll_max_attempts", 30)),
        codex_terminal_success_types=_load_terminal_event_types(
            codex.get("terminal_success_types", ["run_completed", "task_completed", "completed"]),
            "codex.terminal_success_types",
        ),
        codex_terminal_failure_types=_load_terminal_event_types(
            codex.get("terminal_failure_types", ["run_failed", "task_failed", "failed", "error"]),
            "codex.terminal_failure_types",
        ),
        workspace_root_dir=Path(workspace["root_dir"]),
        workspace_base_branch=workspace["base_branch"],
        workspace_branch_prefix=workspace["branch_prefix"],
        workspace_cleanup_on_failure=bool(workspace["cleanup_on_failure"]),
        workspace_max_workspaces=int(workspace["max_workspaces"]),
        validation_commands=_load_validation_commands(validation),
        validation_profiles=_load_validation_profiles(validation),
        validation_default_profile=_load_validation_default_profile(validation),
        validation_repo_profiles=_load_validation_repo_profiles(validation),
        review_max_rounds=int(review.get("max_rounds", 2)),
        review_required_reviewer_decision_fields=_load_required_reviewer_fields(review),
        guardrail_command_rules=_load_guardrail_command_rules(guardrail),
        guardrail_file_rules=_load_guardrail_file_rules(guardrail),
        guardrail_runtime_observation_enabled=bool(guardrail.get("runtime_observation_enabled", True)),
        guardrail_approval_timeout_seconds=int(guardrail.get("approval_timeout_seconds", 86400)),
        trace_output_path=Path(trace["output_path"]),
        log_level=logging["level"],
        logger_name=logging["logger_name"],
    )


def _load_terminal_event_types(raw_types: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(raw_types, list) or not raw_types:
        raise ValueError(f"{field_name} must be a non-empty list of strings")

    normalized: list[str] = []
    for index, event_type in enumerate(raw_types):
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError(f"{field_name}[{index}] must be a non-empty string")
        normalized.append(event_type.strip().lower())
    return tuple(normalized)


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


def _load_guardrail_command_rules(guardrail: dict[str, object]) -> list[CommandPolicyRule]:
    raw_rules = guardrail.get("command_rules", [])
    return _load_guardrail_rules(raw_rules, "guardrail.command_rules", CommandPolicyRule)


def _load_guardrail_file_rules(guardrail: dict[str, object]) -> list[FilePolicyRule]:
    raw_rules = guardrail.get("file_rules", [])
    return _load_guardrail_rules(raw_rules, "guardrail.file_rules", FilePolicyRule)


def _load_required_reviewer_fields(review: dict[str, object]) -> tuple[str, ...]:
    raw_fields = review.get("required_reviewer_decision_fields", ["review_decision|decision|result", "summary"])
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ValueError("review.required_reviewer_decision_fields must be a non-empty list of strings")

    normalized: list[str] = []
    for index, field_spec in enumerate(raw_fields):
        if not isinstance(field_spec, str) or not field_spec.strip():
            raise ValueError(f"review.required_reviewer_decision_fields[{index}] must be a non-empty string")
        normalized.append(field_spec.strip())
    return tuple(normalized)


def _load_guardrail_rules(
    raw_rules: object,
    field_name: str,
    rule_type: type[CommandPolicyRule] | type[FilePolicyRule],
) -> list[CommandPolicyRule] | list[FilePolicyRule]:
    if not isinstance(raw_rules, list):
        raise ValueError(f"{field_name} must be a list of rule tables")

    rules: list[CommandPolicyRule] | list[FilePolicyRule] = []
    for index, raw_rule in enumerate(raw_rules):
        if not isinstance(raw_rule, dict):
            raise ValueError(f"{field_name}[{index}] must be a rule table")
        pattern = raw_rule.get("pattern")
        action = raw_rule.get("action")
        reason = raw_rule.get("reason", "")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError(f"{field_name}[{index}].pattern must be a non-empty string")
        if action not in {"allow", "approval_required", "deny"}:
            raise ValueError(f"{field_name}[{index}].action must be allow, approval_required, or deny")
        if not isinstance(reason, str):
            raise ValueError(f"{field_name}[{index}].reason must be a string")
        rules.append(rule_type(pattern=pattern, action=action, reason=reason))
    return rules
