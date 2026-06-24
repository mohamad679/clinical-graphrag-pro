#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree


REPO_ROOT = Path(__file__).resolve().parents[2]
COVERAGE_XML_PATH = REPO_ROOT / "backend" / "coverage.xml"
BADGE_JSON_PATH = REPO_ROOT / "coverage-badge.json"


def badge_color(coverage_percent: int) -> str:
    if coverage_percent >= 80:
        return "green"
    if coverage_percent >= 60:
        return "yellow"
    return "red"


def read_coverage_percent(path: Path) -> int:
    if not path.exists():
        raise FileNotFoundError(f"Coverage report not found: {path}")

    root = ElementTree.parse(path).getroot()
    line_rate = root.attrib.get("line-rate")
    if line_rate is None:
        raise ValueError(f"Coverage report is missing the line-rate attribute: {path}")

    return round(float(line_rate) * 100)


def build_badge_payload(coverage_percent: int) -> dict[str, int | str]:
    return {
        "schemaVersion": 1,
        "label": "coverage",
        "message": f"{coverage_percent}%",
        "color": badge_color(coverage_percent),
    }


def main() -> int:
    coverage_percent = read_coverage_percent(COVERAGE_XML_PATH)
    payload = build_badge_payload(coverage_percent)
    BADGE_JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
