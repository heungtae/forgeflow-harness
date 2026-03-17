from __future__ import annotations

from fnmatch import fnmatch

from forgeflow_harness.models import CommandPolicyRule, FilePolicyRule, GuardrailDecision


class GuardrailEngine:
    def __init__(
        self,
        command_rules: list[CommandPolicyRule],
        file_rules: list[FilePolicyRule],
    ) -> None:
        self._command_rules = command_rules
        self._file_rules = file_rules

    def check_command(self, command: list[str]) -> GuardrailDecision:
        command_text = " ".join(command)
        return self._match(command_text, self._command_rules)

    def check_files(self, file_paths: list[str]) -> GuardrailDecision:
        for file_path in file_paths:
            decision = self._match(file_path, self._file_rules)
            if decision.action != "allow":
                return decision
        return GuardrailDecision(action="allow", reason="", matched_rule=None)

    def _match(
        self,
        candidate: str,
        rules: list[CommandPolicyRule] | list[FilePolicyRule],
    ) -> GuardrailDecision:
        for rule in rules:
            if fnmatch(candidate, rule.pattern):
                return GuardrailDecision(
                    action=rule.action,
                    reason=rule.reason or f"matched policy: {rule.pattern}",
                    matched_rule=rule.pattern,
                )
        return GuardrailDecision(action="allow", reason="", matched_rule=None)
