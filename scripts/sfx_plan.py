#!/usr/bin/env python3
"""Build global SFX events from scene/element annotation fields."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _entries(value: Any) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, str):
        return [{"file": value}]
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        out: list[dict] = []
        for item in value:
            out.extend(_entries(item))
        return out
    return []


def collect_scene_sfx(annotation: dict, annotation_path: str | Path, *, scene_offset_ms: int = 0) -> list[dict]:
    base = Path(annotation_path).resolve().parent
    events: list[dict] = []

    for raw in _entries(annotation.get("sfx")):
        file = raw.get("file")
        if not file:
            continue
        p = Path(file); p = p if p.is_absolute() else base / p
        events.append({
            "file": str(p),
            "startMs": scene_offset_ms + max(0, int(raw.get("startMs", raw.get("offsetMs", 0)) or 0)),
            "gainDb": float(raw.get("gainDb", 0.0) or 0.0),
            "source": "scene",
        })

    for element in annotation.get("elements") or []:
        reveal = element.get("reveal") or {}
        anchor = int(reveal.get("startMs") or 0)
        raw_sfx = element.get("sfx") if element.get("sfx") is not None else reveal.get("sfx")
        for raw in _entries(raw_sfx):
            file = raw.get("file")
            if not file:
                continue
            p = Path(file); p = p if p.is_absolute() else base / p
            events.append({
                "file": str(p),
                "startMs": scene_offset_ms + anchor + max(0, int(raw.get("offsetMs", 0) or 0)),
                "gainDb": float(raw.get("gainDb", 0.0) or 0.0),
                "source": str(element.get("id") or element.get("label") or "element"),
            })
    return sorted(events, key=lambda e: (e["startMs"], e["file"]))


def write_plan(events: list[dict], output: str | Path) -> Path:
    output = Path(output)
    output.write_text(json.dumps({"events": events}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
