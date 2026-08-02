"""Minimal immutable HTML report adapter for v0.8 AnalysisRun records."""

from __future__ import annotations

import hashlib
import html
import json
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile

from ..schema import AnalysisRun, ReportArtifact


class AnalysisRunReportBuilder:
    """Write a self-contained report with atomic replacement and a content hash."""

    def __init__(self, output_dir: Path | str) -> None:
        self._output_dir = Path(output_dir)

    def build(self, run: AnalysisRun) -> ReportArtifact:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        destination = self._output_dir / f"analysis-{run.run_id}.html"
        payload = json.dumps(
            asdict(run),
            default=lambda value: value.value if isinstance(value, Enum) else value.isoformat(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        document = (
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f"<title>谛听分析 {html.escape(run.symbol)}</title></head><body>"
            f"<h1>{html.escape(run.symbol)} · {html.escape(run.status.value)}</h1>"
            f"<p>run_id: {html.escape(run.run_id)}</p>"
            f"<pre>{html.escape(payload)}</pre></body></html>"
        )
        encoded = document.encode("utf-8")
        with NamedTemporaryFile(
            "wb",
            dir=self._output_dir,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(encoded)
            temporary = Path(handle.name)
        temporary.replace(destination)
        return ReportArtifact(
            run_id=run.run_id,
            path=destination.resolve(),
            media_type="text/html; charset=utf-8",
            sha256=hashlib.sha256(encoded).hexdigest(),
        )
