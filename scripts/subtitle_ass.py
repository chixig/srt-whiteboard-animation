#!/usr/bin/env python3
"""Convert SRT cues into deterministic ASS captions for whiteboard videos."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from parse_srt import parse_srt  # noqa: E402


def _ass_time(ms: int) -> str:
    cs = max(0, int(round(ms / 10.0)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cent = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cent:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def build_ass(
    srt_text: str,
    *,
    width: int = 1080,
    height: int = 1920,
    font: str = "Arial",
    font_size: int | None = None,
    margin_v: int | None = None,
    outline: float = 2.0,
    shadow: float = 0.0,
) -> str:
    cues = parse_srt(srt_text)
    if font_size is None:
        font_size = max(28, int(round(height * 0.034)))
    if margin_v is None:
        margin_v = max(36, int(round(height * 0.055)))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{font_size},&H00FFFFFF,&H000000FF,&HB00000000,&H78000000,0,0,0,0,100,100,0,0,1,{outline},{shadow},2,54,54,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for cue in cues:
        text = _escape(cue["text"])
        events.append(f"Dialogue: 0,{_ass_time(cue['startMs'])},{_ass_time(cue['endMs'])},Default,,0,0,0,,{text}")
    return header + "\n".join(events) + ("\n" if events else "")


def write_ass(srt: str | Path, output: str | Path, **kwargs) -> Path:
    srt = Path(srt); output = Path(output)
    output.write_text(build_ass(srt.read_text(encoding="utf-8-sig"), **kwargs), encoding="utf-8")
    return output


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="SRT → ASS 字幕样式文件")
    p.add_argument("srt"); p.add_argument("output")
    p.add_argument("--width", type=int, default=1080); p.add_argument("--height", type=int, default=1920)
    p.add_argument("--font", default="Arial"); p.add_argument("--font-size", type=int)
    p.add_argument("--margin-v", type=int)
    args = p.parse_args(argv)
    write_ass(args.srt, args.output, width=args.width, height=args.height, font=args.font,
              font_size=args.font_size, margin_v=args.margin_v)
    print(f"OUTPUT={args.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
