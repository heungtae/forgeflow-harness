from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from forgeflow_harness.models import TraceEvent


class TraceRepository:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: TraceEvent) -> None:
        serializable = asdict(event)
        serializable["timestamp"] = event.timestamp.isoformat()
        with self.output_path.open("a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(serializable, sort_keys=True))
            file_obj.write("\n")
