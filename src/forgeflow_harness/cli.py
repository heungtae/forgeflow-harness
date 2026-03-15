from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from forgeflow_harness.config import load_config
from forgeflow_harness.json_logging import configure_logger
from forgeflow_harness.models import HarnessRequest
from forgeflow_harness.orchestrator import build_orchestrator
from forgeflow_harness.trace import TraceRepository


def parse_constraints(values: list[str]) -> dict[str, Any]:
    constraints: dict[str, Any] = {}
    for value in values:
        key, separator, raw_value = value.partition("=")
        if not separator:
            raise ValueError(f"constraint must be key=value: {value}")
        constraints[key] = _coerce_value(raw_value)
    return constraints


def _coerce_value(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(value)
    except ValueError:
        return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Forgeflow Week 2 harness CLI")
    parser.add_argument("--config", default="config.toml", help="Path to config.toml")
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--constraint", action="append", default=[], help="Constraint in key=value form")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = load_config(args.config)
    logger = configure_logger(config.logger_name, config.log_level)
    trace_repository = TraceRepository(Path(config.trace_output_path))
    orchestrator = build_orchestrator(config, logger, trace_repository)

    try:
        constraints = parse_constraints(args.constraint)
    except ValueError as exc:
        parser.error(str(exc))

    harness_request = HarnessRequest(
        request_id=args.request_id,
        repo=args.repo,
        goal=args.goal,
        constraints=constraints,
    )
    result = orchestrator.run(harness_request)
    print(
        json.dumps(
            {
                "request_id": result.request.request_id,
                "status": result.status,
                "message": result.message,
                "session_id": None if result.session is None else result.session.session_id,
                "workspace_path": None if result.workspace is None else str(result.workspace.worktree_path),
            },
            sort_keys=True,
        )
    )
    return 0 if result.status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
