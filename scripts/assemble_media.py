#!/usr/bin/env python3
"""Final assembly: fit/mix audio, mux video, burn subtitles, validate duration."""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from audio_mix import load_sfx_plan, mix_audio
from burn_subtitles import burn_subtitles
from media_utils import probe_media
from mux_audio import mux_audio


def assemble_media(video: str | Path, output: str | Path, *, narration: str | Path | None = None,
                   bgm: str | Path | None = None, sfx_plan: str | Path | None = None,
                   sfx_events: list[dict] | None = None, subtitles: str | Path | None = None,
                   subtitle_font: str = "Arial", subtitle_font_size: int | None = None,
                   subtitle_margin_v: int | None = None, narration_gain_db: float = 0.0,
                   bgm_gain_db: float = -18.0, duck_ratio: float = 8.0,
                   max_drift_ms: int = 250) -> Path:
    video = Path(video).resolve(); output = Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    source_info = probe_media(video); duration = float(source_info["duration"])
    if duration <= 0:
        raise RuntimeError("无法取得视频时长")
    plan_events = load_sfx_plan(sfx_plan)
    sfx_events = list(plan_events) + list(sfx_events or [])
    needs_audio = bool(narration or bgm or sfx_events)

    with tempfile.TemporaryDirectory(prefix="whiteboard-final-") as td:
        td = Path(td)
        current = video
        if needs_audio:
            audio_path = td / "mix.m4a"
            mix_audio(audio_path, duration=duration, narration=narration, bgm=bgm,
                      sfx_events=sfx_events, narration_gain_db=narration_gain_db,
                      bgm_gain_db=bgm_gain_db, duck_ratio=duck_ratio)
            muxed = td / "muxed.mp4"
            mux_audio(current, audio_path, muxed, fit="video")
            current = muxed
        if subtitles:
            burn_subtitles(current, subtitles, output, font=subtitle_font,
                           font_size=subtitle_font_size, margin_v=subtitle_margin_v)
        else:
            shutil.copy2(current, output)

    final_info = probe_media(output)
    drift_ms = abs(float(final_info["duration"]) - duration) * 1000.0
    if drift_ms > max_drift_ms:
        raise RuntimeError(f"最终成片时长漂移 {drift_ms:.0f}ms，超过阈值 {max_drift_ms}ms")
    print(f"[timing] source={duration:.3f}s final={final_info['duration']:.3f}s drift={drift_ms:.0f}ms")
    return output


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="白板视频最终音视频装配")
    p.add_argument("video"); p.add_argument("output")
    p.add_argument("--narration"); p.add_argument("--bgm"); p.add_argument("--sfx-plan")
    p.add_argument("--subtitles"); p.add_argument("--subtitle-font", default="Arial")
    p.add_argument("--subtitle-font-size", type=int); p.add_argument("--subtitle-margin-v", type=int)
    p.add_argument("--narration-gain-db", type=float, default=0.0); p.add_argument("--bgm-gain-db", type=float, default=-18.0)
    p.add_argument("--duck-ratio", type=float, default=8.0); p.add_argument("--max-drift-ms", type=int, default=250)
    args = p.parse_args(argv)
    out = assemble_media(args.video, args.output, narration=args.narration, bgm=args.bgm,
                         sfx_plan=args.sfx_plan, subtitles=args.subtitles,
                         subtitle_font=args.subtitle_font, subtitle_font_size=args.subtitle_font_size,
                         subtitle_margin_v=args.subtitle_margin_v, narration_gain_db=args.narration_gain_db,
                         bgm_gain_db=args.bgm_gain_db, duck_ratio=args.duck_ratio, max_drift_ms=args.max_drift_ms)
    print(f"OUTPUT={out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
