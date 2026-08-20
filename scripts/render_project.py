#!/usr/bin/env python3
"""Batch project controller with final narration/BGM/SFX/subtitle assembly."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SCRIPT_DIR))
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")

import annotation_tools as at  # noqa: E402
from audio_mix import load_sfx_plan  # noqa: E402
from media_utils import probe_media  # noqa: E402
from sfx_plan import collect_scene_sfx, validate_sfx_fields, write_plan  # noqa: E402


def _natural_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def discover_scenes(source_dir: Path) -> list[dict]:
    scenes: list[dict] = []
    for ann in sorted(source_dir.glob("*.annotation.json"), key=_natural_key):
        stem = ann.name[:-len(".annotation.json")]
        image = next((source_dir / f"{stem}{ext}" for ext in _IMAGE_EXTS if (source_dir / f"{stem}{ext}").is_file()), None)
        scenes.append({"stem": stem, "annotation": ann, "image": image})
    return scenes


def _run(cmd: list[str]) -> None:
    print("$ " + " ".join(str(x) for x in cmd))
    completed = subprocess.run(cmd)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {cmd[1] if len(cmd) > 1 else cmd[0]}")


def _load_profile(value: str) -> dict:
    path = Path(value)
    if not path.exists():
        path = _ROOT / "profiles" / (value if value.endswith(".json") else f"{value}.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _normalized_annotation(path: Path, args: argparse.Namespace, profile: dict) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if args.no_retime:
        return data
    timeline = profile.get("timeline") or {}
    return at.normalize_timeline(
        data,
        mode=args.timeline_mode,
        gap_ms=int(timeline.get("gap_ms", 180)),
        lead_in_ms=timeline.get("lead_in_ms"),
        gaze_ms=int(timeline.get("gaze_ms", 500)),
    )


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="批量白板动画项目控制器")
    p.add_argument("source_dir", help="包含 *.png + *.annotation.json 的目录")
    p.add_argument("output", help="最终项目 MP4")
    p.add_argument("--profile", default="vertical-short-video")
    p.add_argument("--audio", "--narration", dest="narration", help="整条视频旁白/原声；--audio 保留兼容")
    p.add_argument("--bgm", help="整条背景音乐，自动循环 + 旁白 ducking")
    p.add_argument("--sfx-plan", help="额外的全局 SFX plan JSON")
    p.add_argument("--no-annotation-sfx", action="store_true", help="忽略 annotation 的 scene/element sfx")
    p.add_argument("--subtitles", help="整条视频 SRT，最终烧录")
    p.add_argument("--subtitle-font", default="Arial")
    p.add_argument("--subtitle-font-size", type=int)
    p.add_argument("--subtitle-margin-v", type=int)
    p.add_argument("--narration-gain-db", type=float, default=0.0)
    p.add_argument("--bgm-gain-db", type=float, default=-18.0)
    p.add_argument("--duck-ratio", type=float, default=8.0)
    p.add_argument("--max-drift-ms", type=int, default=250)
    p.add_argument("--max-source-mismatch-ms", type=int, default=1500,
                   help="旁白/字幕与画面允许的源时长差；负数禁用源素材时长保护")
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
        print(f"[err] source_dir 不存在: {source_dir}"); return 1
    try:
        profile = _load_profile(args.profile)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[err] profile 读取失败: {exc}"); return 1

    scenes = discover_scenes(source_dir)
    if not scenes:
        print("[err] 没有发现 *.annotation.json"); return 1
    missing = [s["stem"] for s in scenes if s["image"] is None]
    if missing:
        print("[err] 以下 annotation 找不到同名图片: " + ", ".join(missing)); return 1

    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(args.work_dir) if args.work_dir else out.with_name(out.stem + "_scenes")
    work_dir.mkdir(parents=True, exist_ok=True)
    merged_visual = out.with_name(out.stem + "_visual.mp4")

    scene_outputs: list[Path] = []
    project_sfx: list[dict] = []
    scene_meta: list[dict] = []
    scene_offset_ms = 0

    for index, scene in enumerate(scenes, start=1):
        scene_out = work_dir / f"{index:03d}-{scene['stem']}.mp4"
        scene_outputs.append(scene_out)
        cmd = [sys.executable, str(_SCRIPT_DIR / "render_short_video.py"), str(scene["image"]),
               str(scene["annotation"]), str(scene_out), "--profile", args.profile,
               "--timeline-mode", args.timeline_mode, "--no-annotation-sfx"]
        if args.no_retime: cmd.append("--no-retime")
        if args.ink_path: cmd += ["--ink-path", args.ink_path]
        if args.color_fill: cmd += ["--color-fill", args.color_fill]
        if args.bare_tip: cmd.append("--bare-tip")
        if args.strict_aspect: cmd.append("--strict-aspect")
        print(f"[scene {index}/{len(scenes)}] {scene['stem']}")
        try:
            normalized = _normalized_annotation(scene["annotation"], args, profile)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"[err] 场景 {scene['stem']} annotation 读取/归一化失败: {exc}")
            return 1

        if not args.no_annotation_sfx:
            sfx_findings = validate_sfx_fields(normalized)
            for finding in sfx_findings:
                prefix = "ERR" if finding["severity"] == "error" else "WARN"
                element = f" [{finding['element']}]" if finding.get("element") else ""
                print(f"[{prefix}] {finding['code']}{element}: {finding['message']}")
            if any(f["severity"] == "error" for f in sfx_findings):
                print(f"[err] 场景 {scene['stem']} 的 annotation SFX 配置无效")
                return 1

        if not args.dry_run:
            try:
                _run(cmd)
            except RuntimeError as exc:
                print(f"[err] {exc}"); return 1
            actual_ms = int(round(float(probe_media(scene_out)["duration"]) * 1000.0))
        else:
            print("$ " + " ".join(cmd))
            actual_ms = int(normalized.get("sceneDurationMs") or 0)

        if not args.no_annotation_sfx:
            project_sfx.extend(collect_scene_sfx(normalized, scene["annotation"], scene_offset_ms=scene_offset_ms))
        scene_meta.append({"index": index, "stem": scene["stem"], "offsetMs": scene_offset_ms,
                           "durationMs": actual_ms, "output": str(scene_out)})
        scene_offset_ms += actual_ms

    try:
        external_sfx = load_sfx_plan(args.sfx_plan) if args.sfx_plan else []
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[err] 外部 SFX plan 无效: {exc}")
        return 1
    all_sfx = sorted(project_sfx + external_sfx, key=lambda e: (int(round(float(e.get("startMs", 0)))), str(e.get("file", ""))))
    missing_sfx = [str(e.get("file")) for e in all_sfx if e.get("file") and not Path(e["file"]).is_file()]
    if missing_sfx:
        print("[err] SFX 文件不存在: " + ", ".join(missing_sfx)); return 1
    combined_sfx_path = work_dir / "project.sfx.json"
    if all_sfx and not args.dry_run:
        write_plan(all_sfx, combined_sfx_path)

    merge_cmd = [sys.executable, str(_SCRIPT_DIR / "merge_scenes.py"), "--inputs",
                 *[str(p) for p in scene_outputs], "--output", str(merged_visual)]
    if not args.dry_run:
        try:
            _run(merge_cmd)
        except RuntimeError as exc:
            print(f"[err] {exc}"); return 1
    else:
        print("$ " + " ".join(merge_cmd))

    needs_assembly = bool(args.narration or args.bgm or args.subtitles or all_sfx)
    if needs_assembly:
        assembly_cmd = [sys.executable, str(_SCRIPT_DIR / "assemble_media.py"), str(merged_visual), str(out)]
        if args.narration: assembly_cmd += ["--narration", str(args.narration)]
        if args.bgm: assembly_cmd += ["--bgm", str(args.bgm)]
        if all_sfx: assembly_cmd += ["--sfx-plan", str(combined_sfx_path)]
        if args.subtitles: assembly_cmd += ["--subtitles", str(args.subtitles), "--subtitle-font", args.subtitle_font]
        if args.subtitle_font_size: assembly_cmd += ["--subtitle-font-size", str(args.subtitle_font_size)]
        if args.subtitle_margin_v: assembly_cmd += ["--subtitle-margin-v", str(args.subtitle_margin_v)]
        assembly_cmd += ["--narration-gain-db", str(args.narration_gain_db),
                         "--bgm-gain-db", str(args.bgm_gain_db), "--duck-ratio", str(args.duck_ratio),
                         "--max-drift-ms", str(args.max_drift_ms),
                         "--max-source-mismatch-ms", str(args.max_source_mismatch_ms)]
        if not args.dry_run:
            try:
                _run(assembly_cmd)
            except RuntimeError as exc:
                print(f"[err] {exc}"); return 1
            merged_visual.unlink(missing_ok=True)
        else:
            print("$ " + " ".join(assembly_cmd))
    else:
        if not args.dry_run:
            out.unlink(missing_ok=True)
            shutil.move(str(merged_visual), str(out))

    manifest = {
        "sourceDir": str(source_dir), "profile": args.profile, "timelineMode": args.timeline_mode,
        "sceneCount": len(scenes), "scenes": scene_meta, "narration": args.narration,
        "bgm": args.bgm, "subtitles": args.subtitles, "sfxEventCount": len(all_sfx),
        "sfxPlan": str(combined_sfx_path) if all_sfx else None,
        "maxSourceMismatchMs": args.max_source_mismatch_ms, "output": str(out),
    }
    manifest_path = Path(args.manifest) if args.manifest else out.with_suffix(".manifest.json")
    if not args.dry_run:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SCENES={len(scenes)}"); print(f"SFX_EVENTS={len(all_sfx)}")
    print(f"MANIFEST={manifest_path}"); print(f"OUTPUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
