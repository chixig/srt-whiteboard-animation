#!/usr/bin/env python3
"""Burn SRT subtitles into MP4 via generated ASS and libass."""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from media_utils import find_ffmpeg, ffmpeg_has_filter, probe_media
from subtitle_ass import write_ass


def burn_subtitles(video: str | Path, srt: str | Path, output: str | Path, *,
                   font: str = "Arial", font_size: int | None = None,
                   margin_v: int | None = None, crf: int = 20) -> Path:
    video = Path(video).resolve(); srt = Path(srt).resolve(); output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg()
    if not ffmpeg_has_filter("ass", ffmpeg):
        raise RuntimeError("当前 ffmpeg 未启用 libass/ass filter，无法烧录字幕；请安装带 libass 的系统 ffmpeg")
    info = probe_media(video)
    width = info["width"] or 1080; height = info["height"] or 1920
    with tempfile.TemporaryDirectory(prefix="whiteboard-ass-") as td:
        td_path = Path(td)
        ass_path = td_path / "captions.ass"
        write_ass(srt, ass_path, width=width, height=height, font=font,
                  font_size=font_size, margin_v=margin_v)
        cmd = [ffmpeg, "-y", "-i", str(video), "-vf", "ass=captions.ass",
               "-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p",
               "-c:a", "copy", "-movflags", "+faststart", str(output)]
        result = subprocess.run(cmd, cwd=td_path, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"字幕烧录失败:\n{result.stderr}")
    return output


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="把 SRT 字幕烧录进 MP4")
    p.add_argument("video"); p.add_argument("srt"); p.add_argument("output")
    p.add_argument("--font", default="Arial"); p.add_argument("--font-size", type=int)
    p.add_argument("--margin-v", type=int); p.add_argument("--crf", type=int, default=20)
    args = p.parse_args(argv)
    out = burn_subtitles(args.video, args.srt, args.output, font=args.font,
                         font_size=args.font_size, margin_v=args.margin_v, crf=args.crf)
    print(f"OUTPUT={out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
