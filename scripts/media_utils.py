#!/usr/bin/env python3
"""Shared ffmpeg/ffprobe helpers for final whiteboard media assembly."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def find_ffmpeg() -> str:
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("找不到 ffmpeg；请安装系统 ffmpeg 或 imageio-ffmpeg") from exc


def find_ffprobe() -> str | None:
    return shutil.which("ffprobe")


def ffmpeg_has_filter(name: str, ffmpeg: str | None = None) -> bool:
    ffmpeg = ffmpeg or find_ffmpeg()
    result = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == name:
            return True
    return False


def probe_media(path: str | Path) -> dict[str, Any]:
    """Return duration/size/stream metadata using ffprobe, with a PyAV fallback."""
    path = Path(path)
    ffprobe = find_ffprobe()
    if ffprobe:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "format=duration:stream=index,codec_type,width,height,duration",
             "-of", "json", str(path)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            payload = json.loads(result.stdout or "{}")
            streams = payload.get("streams") or []
            duration = float((payload.get("format") or {}).get("duration") or 0.0)
            video = next((s for s in streams if s.get("codec_type") == "video"), None)
            audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
            if not duration:
                duration = max((float(s.get("duration") or 0.0) for s in streams), default=0.0)
            return {
                "duration": duration,
                "width": int((video or {}).get("width") or 0),
                "height": int((video or {}).get("height") or 0),
                "hasVideo": video is not None,
                "hasAudio": audio is not None,
            }

    try:
        import av
        container = av.open(str(path))
        duration = float(container.duration or 0) / 1_000_000.0
        video = next((s for s in container.streams if s.type == "video"), None)
        audio = next((s for s in container.streams if s.type == "audio"), None)
        info = {
            "duration": duration,
            "width": int(getattr(video.codec_context, "width", 0) if video else 0),
            "height": int(getattr(video.codec_context, "height", 0) if video else 0),
            "hasVideo": video is not None,
            "hasAudio": audio is not None,
        }
        container.close()
        return info
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"无法探测媒体信息: {path}") from exc


def db_to_linear(db: float) -> float:
    return 10.0 ** (float(db) / 20.0)
