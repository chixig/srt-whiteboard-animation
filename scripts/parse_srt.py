#!/usr/bin/env python3
"""
SRT parsing + scene planning.

Two grouping modes:
- semantic (default): duration constraints + punctuation + pauses + discourse markers.
- duration: legacy duration-only grouping.

The semantic mode is deterministic and offline. It does not claim LLM-level semantic
understanding; instead it picks natural narrative boundaries inside a duration window.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")
_SENTENCE_END = re.compile(r"[。！？!?；;：:]$|[”’」』）》】]$")
_SOFT_END = re.compile(r"[，,、…—-]$")
_TRANSITION_PREFIXES = (
    "但是", "但", "然而", "不过", "于是", "所以", "因此", "后来", "随后", "接着",
    "与此同时", "另一方面", "更重要的是", "问题是", "结果", "最终", "最后", "其实",
    "那么", "这时", "此时", "从此", "可", "而", "反过来", "换句话说",
)


def _to_ms(h: str, m: str, s: str, ms: str) -> int:
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms.ljust(3, "0"))


def parse_srt(text: str) -> list[dict]:
    """Parse SRT, tolerating BOM, extra blank lines and comma/dot milliseconds."""
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text.strip())
    cues: list[dict] = []
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        time_line_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if time_line_idx is None:
            continue
        times = _TIME.findall(lines[time_line_idx])
        if len(times) < 2:
            continue
        start = _to_ms(*times[0])
        end = _to_ms(*times[1])
        body = " ".join(lines[time_line_idx + 1:]).strip()
        cues.append({
            "index": len(cues) + 1,
            "startMs": start,
            "endMs": end,
            "durMs": max(0, end - start),
            "text": body,
        })
    return cues


def _scene(bucket: list[dict], index: int, *, boundary_reason: str) -> dict:
    start = bucket[0]["startMs"]
    end = bucket[-1]["endMs"]
    return {
        "sceneIndex": index,
        "startMs": start,
        "endMs": end,
        "sceneDurationMs": max(0, end - start),
        "cueRange": [bucket[0]["index"], bucket[-1]["index"]],
        "text": " ".join(c["text"] for c in bucket).strip(),
        "boundaryReason": boundary_reason,
    }


def group_scenes_duration(cues: list[dict], target_sec: float, min_sec: float, max_sec: float) -> list[dict]:
    """Legacy duration-only grouping."""
    scenes: list[dict] = []
    bucket: list[dict] = []
    target_ms, min_ms, max_ms = target_sec * 1000, min_sec * 1000, max_sec * 1000

    def flush(reason: str) -> None:
        if not bucket:
            return
        scenes.append(_scene(bucket, len(scenes) + 1, boundary_reason=reason))
        bucket.clear()

    for cue in cues:
        if bucket:
            span_with = cue["endMs"] - bucket[0]["startMs"]
            if span_with > max_ms:
                flush("max-duration")
        bucket.append(cue)
        span = bucket[-1]["endMs"] - bucket[0]["startMs"]
        if span >= target_ms and span >= min_ms:
            flush("target-duration")
    flush("end-of-srt")
    return scenes


def _cut_score(cues: list[dict], start_idx: int, end_idx: int, target_ms: float) -> tuple[float, list[str]]:
    """Score a candidate cut after cues[end_idx]. Higher is better."""
    first = cues[start_idx]
    cur = cues[end_idx]
    span = cur["endMs"] - first["startMs"]
    score = -abs(span - target_ms) / max(target_ms, 1) * 4.0
    reasons: list[str] = []

    text = cur["text"].strip()
    if _SENTENCE_END.search(text):
        score += 3.0
        reasons.append("sentence-end")
    elif _SOFT_END.search(text):
        score += 0.7
        reasons.append("soft-punctuation")

    if end_idx + 1 < len(cues):
        nxt = cues[end_idx + 1]
        gap = max(0, nxt["startMs"] - cur["endMs"])
        if gap >= 1200:
            score += 4.0
            reasons.append(f"pause-{gap}ms")
        elif gap >= 650:
            score += 2.2
            reasons.append(f"pause-{gap}ms")
        elif gap >= 350:
            score += 0.8
            reasons.append(f"pause-{gap}ms")

        next_text = nxt["text"].lstrip()
        marker = next((m for m in _TRANSITION_PREFIXES if next_text.startswith(m)), None)
        if marker:
            score += 2.2
            reasons.append(f"transition:{marker}")

    if len(text) <= 4:
        score -= 1.0
        reasons.append("short-fragment")

    return score, reasons


def group_scenes_semantic(cues: list[dict], target_sec: float, min_sec: float, max_sec: float) -> list[dict]:
    """Choose natural boundaries within min/target/max duration constraints."""
    if not cues:
        return []
    target_ms, min_ms, max_ms = target_sec * 1000, min_sec * 1000, max_sec * 1000
    scenes: list[dict] = []
    start_idx = 0

    while start_idx < len(cues):
        if start_idx == len(cues) - 1:
            scenes.append(_scene([cues[start_idx]], len(scenes) + 1, boundary_reason="end-of-srt"))
            break

        candidates: list[tuple[float, int, list[str]]] = []
        forced_end = start_idx

        for end_idx in range(start_idx, len(cues)):
            span = cues[end_idx]["endMs"] - cues[start_idx]["startMs"]
            if span <= max_ms:
                forced_end = end_idx
            if min_ms <= span <= max_ms:
                score, reasons = _cut_score(cues, start_idx, end_idx, target_ms)
                candidates.append((score, end_idx, reasons))
            if span > max_ms:
                break

        remaining_span = cues[-1]["endMs"] - cues[start_idx]["startMs"]
        if remaining_span <= max_ms:
            end_idx = len(cues) - 1
            scenes.append(_scene(
                cues[start_idx:end_idx + 1],
                len(scenes) + 1,
                boundary_reason="end-of-srt",
            ))
            break

        if candidates:
            _, end_idx, reasons = max(candidates, key=lambda item: item[0])
            reason = "+".join(reasons) if reasons else "duration-fit"
        else:
            end_idx = max(start_idx, forced_end)
            reason = "forced-max-window"

        scenes.append(_scene(
            cues[start_idx:end_idx + 1],
            len(scenes) + 1,
            boundary_reason=reason,
        ))
        start_idx = end_idx + 1

    return scenes


def group_scenes(
    cues: list[dict],
    target_sec: float,
    min_sec: float,
    max_sec: float,
    *,
    mode: str = "semantic",
) -> list[dict]:
    if min_sec <= 0 or target_sec <= 0 or max_sec <= 0:
        raise ValueError("scene durations must be positive")
    if not (min_sec <= target_sec <= max_sec):
        raise ValueError("expected min-sec <= target-sec <= max-sec")
    if mode == "duration":
        return group_scenes_duration(cues, target_sec, min_sec, max_sec)
    if mode == "semantic":
        return group_scenes_semantic(cues, target_sec, min_sec, max_sec)
    raise ValueError(f"unknown grouping mode: {mode}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="SRT 解析 + 语义分镜建议")
    p.add_argument("srt", help="字幕文件路径 (.srt)")
    p.add_argument("--mode", choices=["semantic", "duration"], default="semantic",
                   help="semantic=停顿/标点/转折+时长；duration=旧版纯时长")
    p.add_argument("--target-sec", type=float, default=30.0)
    p.add_argument("--min-sec", type=float, default=25.0)
    p.add_argument("--max-sec", type=float, default=35.0)
    args = p.parse_args(argv)

    try:
        raw = Path(args.srt).read_text(encoding="utf-8-sig")
    except OSError as e:
        print(f"[err] 无法读取字幕: {e}", file=sys.stderr)
        return 1

    cues = parse_srt(raw)
    if not cues:
        print("[err] 未解析到任何字幕条，请检查 SRT 格式", file=sys.stderr)
        return 1
    try:
        scenes = group_scenes(
            cues, args.target_sec, args.min_sec, args.max_sec, mode=args.mode
        )
    except ValueError as e:
        print(f"[err] {e}", file=sys.stderr)
        return 1

    total_ms = cues[-1]["endMs"] - cues[0]["startMs"]
    print(
        f"字幕条: {len(cues)}  总时长: {total_ms/1000:.1f}s  "
        f"模式: {args.mode}  建议场景: {len(scenes)}",
        file=sys.stderr,
    )
    for s in scenes:
        print(
            f"  幕{s['sceneIndex']:>2}  {s['startMs']/1000:6.1f}-{s['endMs']/1000:6.1f}s "
            f"({s['sceneDurationMs']/1000:4.1f}s, 字幕{s['cueRange'][0]}-{s['cueRange'][1]}) "
            f"[{s['boundaryReason']}]: {s['text'][:40]}",
            file=sys.stderr,
        )

    json.dump(
        {"groupingMode": args.mode, "cues": cues, "scenes": scenes},
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
