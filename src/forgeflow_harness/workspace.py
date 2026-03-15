from __future__ import annotations

import re
import subprocess
from pathlib import Path

from forgeflow_harness.models import HarnessConfig, HarnessRequest, ValidationResult, WorkspaceHandle


class WorkspaceError(RuntimeError):
    """Raised when workspace preparation fails."""


class WorkspaceHarness:
    def __init__(self, config: HarnessConfig) -> None:
        self._root_dir = config.workspace_root_dir
        self._base_branch = config.workspace_base_branch
        self._branch_prefix = config.workspace_branch_prefix
        self._cleanup_on_failure = config.workspace_cleanup_on_failure
        self._root_dir.mkdir(parents=True, exist_ok=True)

    def prepare(self, harness_request: HarnessRequest) -> WorkspaceHandle:
        repo_path = Path(harness_request.repo).resolve()
        self._ensure_git_repo(repo_path)

        branch_name = self._branch_name(harness_request.request_id)
        worktree_path = self._root_dir / harness_request.request_id
        if worktree_path.exists():
            raise WorkspaceError(f"worktree already exists: {worktree_path}")

        self._run_git(
            repo_path,
            "worktree",
            "add",
            "-b",
            branch_name,
            str(worktree_path),
            self._base_branch,
        )
        return WorkspaceHandle(
            request_id=harness_request.request_id,
            repo_path=repo_path,
            worktree_path=worktree_path,
            branch_name=branch_name,
            status="ready",
        )

    def cleanup(self, workspace: WorkspaceHandle) -> None:
        if not self._cleanup_on_failure:
            return
        if workspace.worktree_path.exists():
            self._run_git(workspace.repo_path, "worktree", "remove", "--force", str(workspace.worktree_path))

    def run_validation(self, commands: list[list[str]], worktree_path: Path) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        for command in commands:
            try:
                completed = subprocess.run(
                    command,
                    cwd=worktree_path,
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except OSError as exc:
                raise WorkspaceError(f"validation command failed to start: {' '.join(command)}: {exc}") from exc

            result = ValidationResult(
                command=command,
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                status="passed" if completed.returncode == 0 else "failed",
            )
            results.append(result)
            if completed.returncode != 0:
                break
        return results

    def _branch_name(self, request_id: str) -> str:
        sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "-", request_id).strip("-")
        return f"{self._branch_prefix}/{sanitized}"

    def _ensure_git_repo(self, repo_path: Path) -> None:
        if not repo_path.exists():
            raise WorkspaceError(f"repo does not exist: {repo_path}")
        self._run_git(repo_path, "rev-parse", "--is-inside-work-tree")

    def _run_git(self, repo_path: Path, *args: str) -> None:
        command = ["git", *args]
        completed = subprocess.run(
            command,
            cwd=repo_path,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            raise WorkspaceError(f"git {' '.join(args)} failed: {stderr}")
