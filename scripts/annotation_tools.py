#!/usr/bin/env python3
"""Annotation normalization and validation utilities for whiteboard scenes."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


MIN_DURATION_MS = 100


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def ordered_elements(annotation: dict, mode: str = "sequence") -> list[dict]:
    """Return elements in canonical draw order without mutating the annotation."""
    elements = list(annotation.get("elements") or [])
    indexed = list(enumerate(elements))
    if mode == "startMs":
        indexed.sort(key=lambda item: (_int(item[1].get("reveal", {}).get("startMs")), item[0]))
    else:
        indexed.sort(
            key=lambda item: (
                _int(item[1].get("sequence"), item[0] + 1),
                _int(item[1].get("reveal", {}).get("startMs")),
                item[0],
            )
        )
    return [element for _, element in indexed]


def normalize_timeline(
    annotation: dict,
    *,
    mode: str = "sequence",
    gap_ms: int = 180,
    lead_in_ms: int | None = None,
    gaze_ms: int = 500,
    preserve_scene_duration: bool = True,
) -> dict:
    """Return a normalized copy with deterministic order and non-overlapping timings.

    `sequence` is canonical by default. Existing element durations are preserved, while
    startMs values are rebuilt into a serial one-pen timeline.
    """
    out = copy.deepcopy(annotation)
    ordered = ordered_elements(out, mode=mode)
    if not ordered:
        out["elements"] = []
        out["sceneDurationMs"] = max(_int(out.get("sceneDurationMs")), 1000)
        return out

    gap_ms = max(0, _int(gap_ms))
    gaze_ms = max(0, _int(gaze_ms))
    if lead_in_ms is None:
        lead_in_ms = max(0, min(_int(e.get("reveal", {}).get("startMs")) for e in ordered))
    else:
        lead_in_ms = max(0, _int(lead_in_ms))

    cursor = lead_in_ms
    for index, element in enumerate(ordered, start=1):
        element["sequence"] = index
        reveal = element.setdefault("reveal", {})
        duration = max(MIN_DURATION_MS, _int(reveal.get("durationMs"), 2000))
        reveal["startMs"] = cursor
        reveal["durationMs"] = duration
        reveal.setdefault("protectedRegions", [])
        cursor += duration
        if index < len(ordered):
            cursor += gap_ms

    out["elements"] = ordered
    required_duration = cursor + gaze_ms
    old_duration = _int(out.get("sceneDurationMs"))
    out["sceneDurationMs"] = max(required_duration, old_duration) if preserve_scene_duration else required_duration
    return out


def validate_annotation(annotation: dict, image_size: tuple[int, int] | None = None) -> list[dict]:
    """Return structured validation findings. Empty list means the annotation is valid."""
    findings: list[dict] = []
    canvas = annotation.get("canvas") or {}
    width = _int(canvas.get("width"))
    height = _int(canvas.get("height"))
    if width <= 0 or height <= 0:
        findings.append({"severity": "error", "code": "canvas.invalid", "message": "canvas.width/height 必须为正整数"})
        return findings

    if image_size and (width, height) != tuple(image_size):
        findings.append({
            "severity": "error",
            "code": "canvas.image_mismatch",
            "message": f"标注画布 {width}x{height} 与图片 {image_size[0]}x{image_size[1]} 不一致",
        })

    elements = annotation.get("elements") or []
    if not elements:
        findings.append({"severity": "error", "code": "elements.empty", "message": "annotation 中没有 elements"})
        return findings

    sequences: list[int] = []
    intervals: list[tuple[int, int, str]] = []
    for index, element in enumerate(elements):
        label = str(element.get("label") or element.get("id") or f"element-{index + 1}")
        sequence = _int(element.get("sequence"), index + 1)
        sequences.append(sequence)

        region = element.get("region") or {}
        x = _int(region.get("x")); y = _int(region.get("y"))
        w = _int(region.get("width")); h = _int(region.get("height"))
        if w <= 0 or h <= 0:
            findings.append({"severity": "error", "code": "region.invalid_size", "element": label, "message": "region.width/height 必须大于 0"})
        if x < 0 or y < 0 or x + w > width or y + h > height:
            findings.append({"severity": "error", "code": "region.out_of_bounds", "element": label, "message": f"region 超出画布: x={x}, y={y}, w={w}, h={h}"})

        reveal = element.get("reveal") or {}
        start = _int(reveal.get("startMs"))
        duration = _int(reveal.get("durationMs"))
        if start < 0:
            findings.append({"severity": "error", "code": "timeline.negative_start", "element": label, "message": "startMs 不能小于 0"})
        if duration < MIN_DURATION_MS:
            findings.append({"severity": "error", "code": "timeline.invalid_duration", "element": label, "message": f"durationMs 必须至少 {MIN_DURATION_MS}ms"})
        intervals.append((start, start + max(0, duration), label))

        for pindex, protected in enumerate(reveal.get("protectedRegions") or []):
            px = _int(protected.get("x")); py = _int(protected.get("y"))
            pw = _int(protected.get("width")); ph = _int(protected.get("height"))
            if pw <= 0 or ph <= 0 or px < 0 or py < 0 or px + pw > width or py + ph > height:
                findings.append({
                    "severity": "error",
                    "code": "protected_region.invalid",
                    "element": label,
                    "message": f"protectedRegions[{pindex}] 无效或超出画布",
                })

    expected = list(range(1, len(elements) + 1))
    if sorted(sequences) != expected:
        findings.append({"severity": "warning", "code": "sequence.non_contiguous", "message": f"sequence 应连续为 {expected}，当前为 {sequences}"})

    ordered_intervals = sorted(intervals)
    for previous, current in zip(ordered_intervals, ordered_intervals[1:]):
        if current[0] < previous[1]:
            findings.append({
                "severity": "warning",
                "code": "timeline.overlap",
                "element": current[2],
                "message": f"时间与 {previous[2]} 重叠；单笔白板动画建议串行",
            })

    last_end = max(end for _, end, _ in intervals)
    scene_duration = _int(annotation.get("sceneDurationMs"))
    if scene_duration and scene_duration < last_end:
        findings.append({"severity": "error", "code": "scene.too_short", "message": f"sceneDurationMs={scene_duration} 小于最后元素结束时间 {last_end}"})
    return findings


def _print_findings(findings: list[dict]) -> None:
    for finding in findings:
        prefix = "ERR" if finding["severity"] == "error" else "WARN"
        element = f" [{finding['element']}]" if finding.get("element") else ""
        print(f"[{prefix}] {finding['code']}{element}: {finding['message']}")
    if not findings:
        print("[ok] annotation 校验通过")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="白板动画 annotation 时序归一化与校验")
    parser.add_argument("annotation", help="annotation.json")
    parser.add_argument("--normalize", action="store_true", help="按 sequence/startMs 归一化为串行时间轴")
    parser.add_argument("--mode", choices=["sequence", "startMs"], default="sequence")
    parser.add_argument("--gap-ms", type=int, default=180)
    parser.add_argument("--lead-in-ms", type=int, default=None)
    parser.add_argument("--gaze-ms", type=int, default=500)
    parser.add_argument("--output", help="写入新文件；不填则只打印校验结果")
    parser.add_argument("--in-place", action="store_true", help="覆盖原 annotation.json")
    args = parser.parse_args(argv)

    path = Path(args.annotation)
    data = json.loads(path.read_text(encoding="utf-8"))
    if args.normalize:
        data = normalize_timeline(data, mode=args.mode, gap_ms=args.gap_ms, lead_in_ms=args.lead_in_ms, gaze_ms=args.gaze_ms)

    findings = validate_annotation(data)
    _print_findings(findings)

    if args.in_place and args.output:
        parser.error("--in-place 与 --output 不能同时使用")
    target = path if args.in_place else Path(args.output) if args.output else None
    if target:
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[ok] 已写入: {target}")

    return 1 if any(f["severity"] == "error" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
