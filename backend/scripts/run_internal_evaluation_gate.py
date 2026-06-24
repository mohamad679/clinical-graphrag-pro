"""
Run the internal quality suite and exit non-zero on regression.
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.services.evaluation_runner import evaluation_runner_service


async def _main() -> int:
    report = await evaluation_runner_service.run_internal_quality_suite()
    print(
        json.dumps(
            {
                "suite_name": report.suite_name,
                "suite_version": report.suite_version,
                "dataset_size": report.dataset_size,
                "metrics": report.metrics,
                "quality_gate": report.quality_gate,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report.quality_gate.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
