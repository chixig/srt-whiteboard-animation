#!/usr/bin/env python3
"""Render a true low-resolution stream preview using the production renderer."""
from __future__ import annotations

import argparse
from pathlib import Path

import render_short_video


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="生成真实 stream 低清预览 MP4")
    p.add_argument("image")
    p.add_argument("annotation")
    p.add_argument("output", nargs="?", help="默认 <图片名>-preview.mp4")
    p.add_argument("--profile", default="vertical-short-video")
    p.add_argument("--fps", type=int, default=20)
    p.add_argument("--cap-long-edge", type=int, default=540)
    p.add_argument("--ink-path", choices=["grid", "skeleton"], default="grid")
    p.add_argument("--color-fill", choices=["contour-wipe", "brush"], default="contour-wipe")
    p.add_argument("--bare-tip", action="store_true")
    args = p.parse_args(argv)

    image = Path(args.image)
    output = Path(args.output) if args.output else image.with_name(image.stem + "-preview.mp4")
    cmd = [
        str(image), str(args.annotation), str(output),
        "--profile", args.profile,
        "--fps", str(args.fps),
        "--cap-long-edge", str(args.cap_long_edge),
        "--ink-path", args.ink_path,
        "--color-fill", args.color_fill,
    ]
    if args.bare_tip:
        cmd.append("--bare-tip")
    print(f"[preview] true stream preview -> {output}")
    return render_short_video.main(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
