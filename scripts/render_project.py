#!/usr/bin/env python3
"""Batch project controller for SRT whiteboard animation.

Discovers image + annotation pairs, renders every scene with the production wrapper,
merges scene videos, then optionally muxes one narration/original-audio track onto the
final project video.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _natural_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", path.name)]


def discover_scenes(source_dir: Path) -> list[dict]:
    scenes: list[dict] = []
    for ann in sorted(source_dir.glob("*.annotation.json"), key=_natural_key):
        stem = ann.name[:-len(".annotation.json")]
        image = next((source_dir / f"{stem}{ext}" for ext in _IMAGE_EXTS
                      if (source_dir / f"{stem}{ext}").is_file()), None)
        scenes.append({
            "stem": stem,
            "annotation": ann,
            "image": image,
        })
    return scenes


def _run(cmd: list[str]) -> None:
    print("$ " + " ".join(str(x) for x in cmd))
    completed = subprocess.run(cmd)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {cmd[1] if len(cmd) > 1 else cmd[0]}")


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="批量白板动画项目控制器")
    p.add_argument("source_dir", help="包含 *.png + *.annotation.json 的目录")
    p.add_argument("output", help="最终项目 MP4")
    p.add_argument("--profile", default="vertical-short-video")
    p.add_argument("--audio", help="整条视频的旁白/原声；在所有场景合并后 mux")
    p.add_argument("--audio-fit", choices=["video", "shortest"], default="video")
    p.add_argument("--timeline-mode", choices=["sequence", "startMs"], default="sequence")
    p.add_argument("--no-retime", action="store_true")
    p.add_argument("--ink-path", choices=["grid", "skeleton"])
    p.add_argument("--color-fill", choices=["contour-wipe", "brush"])
    p.add_argument("--bare-tip", action="store_true")
    p.add_argument("--strict-aspect", action="store_true")
    p.add_argument("--work-dir", help="中间场景目录，默认 <output_stem>_scenes")
    p.add_argument("--manifest", help="输出项目 manifest JSON")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    source_dir = Path(args.source_dir)
    if not source_dir.is_dir():
        print(f"[err] source_dir 不存在: {source_dir}")
        return 1

    scenes = discover_scenes(source_dir)
    if not scenes:
        print("[err] 没有发现 *.annotation.json")
        return 1

    missing = [s["stem"] for s in scenes if s["image"] is None]
    if missing:
        print("[err] 以下 annotation 找不到同名图片: " + ", ".join(missing))
        return 1

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(args.work_dir) if args.work_dir else out.with_name(out.stem + "_scenes")
    work_dir.mkdir(parents=True, exist_ok=True)
    merged_video = out if not args.audio else out.with_name(out.stem + "_video.mp4")

    scene_outputs: list[Path] = []
    for index, scene in enumerate(scenes, start=1):
        scene_out = work_dir / f"{index:03d}-{scene['stem']}.mp4"
        scene_outputs.append(scene_out)
        cmd = [
            sys.executable,
            str(_SCRIPT_DIR / "render_short_video.py"),
            str(scene["image"]),
            str(scene["annotation"]),
            str(scene_out),
            "--profile", args.profile,
            "--timeline-mode", args.timeline_mode,
        ]
        if args.no_retime:
            cmd.append("--no-retime")
        if args.ink_path:
            cmd += ["--ink-path", args.ink_path]
        if args.color_fill:
            cmd += ["--color-fill", args.color_fill]
        if args.bare_tip:
            cmd.append("--bare-tip")
        if args.strict_aspect:
            cmd.append("--strict-aspect")
        print(f"[scene {index}/{len(scenes)}] {scene['stem']}")
        if not args.dry_run:
            try:
                _run(cmd)
            except RuntimeError as exc:
                print(f"[err] {exc}")
                return 1

    merge_cmd = [
        sys.executable,
        str(_SCRIPT_DIR / "merge_scenes.py"),
        "--inputs",
        *[str(p) for p in scene_outputs],
        "--output",
        str(merged_video),
    ]
    if not args.dry_run:
        try:
            _run(merge_cmd)
        except RuntimeError as exc:
            print(f"[err] {exc}")
            return 1
    else:
        print("$ " + " ".join(merge_cmd))

    if args.audio:
        mux_cmd = [
            sys.executable,
            str(_SCRIPT_DIR / "mux_audio.py"),
            str(merged_video),
            str(args.audio),
            str(out),
            "--fit",
            args.audio_fit,
        ]
        if not args.dry_run:
            try:
                _run(mux_cmd)
            except RuntimeError as exc:
                print(f"[err] {exc}")
                return 1
            if merged_video != out:
                merged_video.unlink(missing_ok=True)
        else:
            print("$ " + " ".join(mux_cmd))

    manifest = {
        "sourceDir": str(source_dir),
        "profile": args.profile,
        "timelineMode": args.timeline_mode,
        "sceneCount": len(scenes),
        "scenes": [
            {
                "index": i,
                "stem": s["stem"],
                "image": str(s["image"]),
                "annotation": str(s["annotation"]),
                "output": str(scene_outputs[i - 1]),
            }
            for i, s in enumerate(scenes, start=1)
        ],
        "audio": args.audio,
        "output": str(out),
    }
    manifest_path = Path(args.manifest) if args.manifest else out.with_suffix(".manifest.json")
    if not args.dry_run:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SCENES={len(scenes)}")
    print(f"MANIFEST={manifest_path}")
    print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
