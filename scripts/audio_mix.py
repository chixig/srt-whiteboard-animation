#!/usr/bin/env python3
"""Final audio bus: narration + ducked BGM + timed SFX, fitted to video duration."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from media_utils import db_to_linear, find_ffmpeg


def load_sfx_plan(path: str | Path | None) -> list[dict]:
    if not path:
        return []
    plan_path = Path(path).resolve()
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    events = data.get("events") if isinstance(data, dict) else data
    if not isinstance(events, list):
        raise ValueError("SFX plan 必须是数组或 {events:[...]} JSON")
    out = []
    for raw in events:
        if not isinstance(raw, dict):
            continue
        event = dict(raw)
        file = event.get("file")
        if file:
            p = Path(file)
            event["file"] = str(p if p.is_absolute() else (plan_path.parent / p).resolve())
        out.append(event)
    return out


def mix_audio(output: str | Path, *, duration: float, narration: str | Path | None = None,
              bgm: str | Path | None = None, sfx_events: list[dict] | None = None,
              narration_gain_db: float = 0.0, bgm_gain_db: float = -18.0,
              duck_ratio: float = 8.0, duck_threshold: float = 0.03,
              duck_attack_ms: int = 20, duck_release_ms: int = 300) -> Path:
    if duration <= 0:
        raise ValueError("duration 必须大于 0")
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg(); sfx_events = sfx_events or []

    cmd = [ffmpeg, "-y"]
    inputs: list[tuple[str, dict]] = []
    if narration:
        cmd += ["-i", str(narration)]; inputs.append(("narration", {}))
    if bgm:
        cmd += ["-stream_loop", "-1", "-i", str(bgm)]; inputs.append(("bgm", {}))
    for event in sfx_events:
        file = event.get("file")
        if not file:
            continue
        cmd += ["-i", str(file)]; inputs.append(("sfx", event))

    if not inputs:
        cmd += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={duration:.6f}"]
        inputs.append(("silence", {}))

    filters: list[str] = []
    labels: list[str] = []
    narr_idx = next((i for i, x in enumerate(inputs) if x[0] == "narration"), None)
    bgm_idx = next((i for i, x in enumerate(inputs) if x[0] == "bgm"), None)

    if narr_idx is not None:
        filters.append(f"[{narr_idx}:a]aresample=48000,volume={db_to_linear(narration_gain_db):.8f},apad,atrim=duration={duration:.6f}[narr]")
    if bgm_idx is not None:
        filters.append(f"[{bgm_idx}:a]aresample=48000,volume={db_to_linear(bgm_gain_db):.8f},apad,atrim=duration={duration:.6f}[bgmraw]")
        if narr_idx is not None:
            filters.append("[narr]asplit=2[narrmix][narside]")
            filters.append(
                f"[bgmraw][narside]sidechaincompress=threshold={duck_threshold}:ratio={duck_ratio}:"
                f"attack={duck_attack_ms}:release={duck_release_ms}[bgmduck]"
            )
            labels += ["[narrmix]", "[bgmduck]"]
        else:
            labels.append("[bgmraw]")
    elif narr_idx is not None:
        labels.append("[narr]")

    for i, (kind, meta) in enumerate(inputs):
        if kind != "sfx":
            continue
        delay = max(0, int(round(float(meta.get("startMs") or 0))))
        gain = db_to_linear(float(meta.get("gainDb") or 0.0))
        name = f"sfx{i}"
        filters.append(f"[{i}:a]aresample=48000,volume={gain:.8f},adelay={delay}:all=1,apad,atrim=duration={duration:.6f}[{name}]")
        labels.append(f"[{name}]")

    if inputs and inputs[0][0] == "silence":
        filters.append(f"[0:a]atrim=duration={duration:.6f}[silence]")
        labels.append("[silence]")

    if len(labels) == 1:
        filters.append(f"{labels[0]}alimiter=limit=0.95,atrim=duration={duration:.6f}[aout]")
    else:
        filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,alimiter=limit=0.95,atrim=duration={duration:.6f}[aout]")

    cmd += ["-filter_complex", ";".join(filters), "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", str(output)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"音频混音失败:\n{result.stderr}")
    return output


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="旁白 + BGM ducking + SFX 混音")
    p.add_argument("output"); p.add_argument("--duration", type=float, required=True)
    p.add_argument("--narration"); p.add_argument("--bgm"); p.add_argument("--sfx-plan")
    p.add_argument("--narration-gain-db", type=float, default=0.0)
    p.add_argument("--bgm-gain-db", type=float, default=-18.0)
    p.add_argument("--duck-ratio", type=float, default=8.0)
    args = p.parse_args(argv)
    events = load_sfx_plan(args.sfx_plan)
    out = mix_audio(args.output, duration=args.duration, narration=args.narration, bgm=args.bgm,
                    sfx_events=events, narration_gain_db=args.narration_gain_db,
                    bgm_gain_db=args.bgm_gain_db, duck_ratio=args.duck_ratio)
    print(f"OUTPUT={out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
