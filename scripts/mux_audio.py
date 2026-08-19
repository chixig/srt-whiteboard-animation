#!/usr/bin/env python3
"""Mux narration/audio into an MP4 using system ffmpeg or imageio-ffmpeg."""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def find_ffmpeg() -> str:
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - environment specific
        raise RuntimeError(
            "找不到 ffmpeg。请运行 scripts/prepare_env.py 安装 imageio-ffmpeg，"
            "或在系统中安装 ffmpeg。"
        ) from exc


def mux_audio(video: str | Path, audio: str | Path, output: str | Path, *, fit: str = "video") -> Path:
    video = Path(video)
    audio = Path(audio)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg()

    cmd = [
        ffmpeg, "-y",
        "-i", str(video),
        "-i", str(audio),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
    ]
    if fit == "video":
        cmd += ["-af", "apad", "-shortest"]
    elif fit == "shortest":
        cmd += ["-shortest"]
    else:
        raise ValueError(f"unsupported fit mode: {fit}")
    cmd += ["-movflags", "+faststart", str(output)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"音频合成失败:\n{result.stderr}")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="给白板 MP4 合成旁白/原声")
    parser.add_argument("video")
    parser.add_argument("audio")
    parser.add_argument("output")
    parser.add_argument("--fit", choices=["video", "shortest"], default="video",
                        help="video=音频不足时补静音并以视频长度为准；shortest=以较短轨为准")
    args = parser.parse_args(argv)
    final = mux_audio(args.video, args.audio, args.output, fit=args.fit)
    print(f"OUTPUT={final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
