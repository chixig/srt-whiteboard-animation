#!/usr/bin/env python3
"""Build and validate global SFX events from scene/element annotation fields."""
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


def normalize_sfx_events(value: Any) -> list[dict]:
    """Expand string/dict/list shorthand into a flat list of event dictionaries."""
    return [dict(event) for event in _entries(value)]


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _validate_value(value: Any, *, scope: str, element: str | None = None) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, (str, dict, list)):
        return [{"severity": "error", "code": "sfx.invalid_container", "element": element,
                 "message": f"{scope} sfx 必须是文件字符串、对象或数组"}]
    findings: list[dict] = []
    if isinstance(value, list):
        for index, item in enumerate(value):
            if not isinstance(item, (str, dict, list)):
                findings.append({"severity": "error", "code": "sfx.invalid_entry", "element": element,
                                 "message": f"{scope} sfx[{index}] 必须是文件字符串、对象或数组"})
    entries = _entries(value)
    if not entries and value not in (None, [], ""):
        findings.append({"severity": "error", "code": "sfx.invalid_entry", "element": element,
                         "message": f"{scope} sfx 中没有有效事件"})
    for index, event in enumerate(entries):
        file = event.get("file")
        if not isinstance(file, str) or not file.strip():
            findings.append({"severity": "error", "code": "sfx.file_required", "element": element,
                             "message": f"{scope} sfx[{index}] 缺少非空 file"})
        for key in ("startMs", "offsetMs"):
            if key in event:
                num = _number(event.get(key))
                if num is None or num < 0:
                    findings.append({"severity": "error", "code": "sfx.invalid_time", "element": element,
                                     "message": f"{scope} sfx[{index}].{key} 必须是 >= 0 的数字"})
        if "gainDb" in event and _number(event.get("gainDb")) is None:
            findings.append({"severity": "error", "code": "sfx.invalid_gain", "element": element,
                             "message": f"{scope} sfx[{index}].gainDb 必须是数字"})
    return findings


def validate_sfx_events(events: Any, *, scope: str = "SFX plan") -> list[dict]:
    return _validate_value(events, scope=scope)


def validate_sfx_fields(annotation: dict) -> list[dict]:
    findings = _validate_value(annotation.get("sfx"), scope="scene")
    for index, element in enumerate(annotation.get("elements") or []):
        label = str(element.get("label") or element.get("id") or f"element-{index + 1}")
        reveal = element.get("reveal") or {}
        raw = element.get("sfx") if element.get("sfx") is not None else reveal.get("sfx")
        findings.extend(_validate_value(raw, scope="element", element=label))
    return findings


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
            "startMs": scene_offset_ms + max(0, int(round(float(raw.get("startMs", raw.get("offsetMs", 0)) or 0)))),
            "gainDb": float(raw.get("gainDb", 0.0) or 0.0),
            "source": "scene",
        })

    for element in annotation.get("elements") or []:
        reveal = element.get("reveal") or {}
        anchor = int(round(float(reveal.get("startMs") or 0)))
        raw_sfx = element.get("sfx") if element.get("sfx") is not None else reveal.get("sfx")
        for raw in _entries(raw_sfx):
            file = raw.get("file")
            if not file:
                continue
            p = Path(file); p = p if p.is_absolute() else base / p
            events.append({
                "file": str(p),
                "startMs": scene_offset_ms + anchor + max(0, int(round(float(raw.get("offsetMs", 0) or 0)))),
                "gainDb": float(raw.get("gainDb", 0.0) or 0.0),
                "source": str(element.get("id") or element.get("label") or "element"),
            })
    return sorted(events, key=lambda e: (e["startMs"], e["file"]))


def write_plan(events: list[dict], output: str | Path) -> Path:
    output = Path(output)
    output.write_text(json.dumps({"events": events}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
