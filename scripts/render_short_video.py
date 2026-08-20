#!/usr/bin/env python3
"""Production wrapper for SRT whiteboard animation.

Sequence-driven timing + validation + profiles + Polygon masks + final media assembly.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SCRIPT_DIR))

import annotation_tools as at  # noqa: E402
import polygon_schema as ps  # noqa: E402
import render_stream_whiteboard as rsw  # noqa: E402
import stream_render as sr  # noqa: E402
from assemble_media import assemble_media  # noqa: E402
from mux_audio import mux_audio  # noqa: E402
from polygon_renderer import PolygonRegionStreamRenderer  # noqa: E402
from sfx_plan import collect_scene_sfx, validate_sfx_fields  # noqa: E402

PROFILE_DIR = _ROOT / "profiles"
PROFILE_KEYS = {
    "fps", "grid_edge", "sample_step", "cap_long_edge", "brush_radius",
    "ink_weight", "color_weight", "ink_threshold", "ink_reveal_radius",
    "target_hand_height", "canvas_hex", "match_bg", "match_bg_threshold",
    "color_fill", "wipe_decay", "wipe_delay_ratio", "wipe_blocks",
    "pause_mode", "ink_path_mode", "skeleton_min_points",
    "skeleton_resample_spacing",
}


def load_profile(value: str) -> dict:
    path = Path(value)
    if not path.exists():
        path = PROFILE_DIR / (value if value.endswith(".json") else f"{value}.json")
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in PROFILE_DIR.glob("*.json")))
        raise FileNotFoundError(f"找不到 profile: {value}。可用: {available}")
    return json.loads(path.read_text(encoding="utf-8"))


def _profile_cfg(profile: dict, args: argparse.Namespace) -> sr.Config:
    renderer = dict(profile.get("renderer") or {})
    renderer = {k: v for k, v in renderer.items() if k in PROFILE_KEYS}
    overrides = {
        "fps": args.fps,
        "cap_long_edge": args.cap_long_edge,
        "canvas_hex": args.canvas_hex,
        "ink_path_mode": args.ink_path,
        "color_fill": args.color_fill,
        "target_hand_height": args.target_hand_height,
    }
    for key, value in overrides.items():
        if value is not None:
            renderer[key] = value
    return sr.Config(**renderer)


def _aspect_warning(profile: dict, width: int, height: int, strict: bool) -> None:
    canvas = profile.get("canvas") or {}
    pw = int(canvas.get("width") or 0); ph = int(canvas.get("height") or 0)
    if not pw or not ph:
        return
    expected = pw / ph; actual = width / height
    delta = abs(actual - expected) / expected
    if delta <= 0.02:
        return
    message = f"输入图片比例 {width}:{height} 与 profile 目标 {pw}:{ph} 不一致"
    if strict:
        raise ValueError(message)
    print(f"[warn] {message}；渲染器会保持输入图片比例，不会强行拉伸。")


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="白板动画生产包装器：时序 + Polygon + 最终音视频装配")
    p.add_argument("image", help="线稿图")
    p.add_argument("annotation", help="annotation.json")
    p.add_argument("output", help="最终 MP4")
    p.add_argument("--profile", default="vertical-short-video")
    p.add_argument("--audio", "--narration", dest="narration", help="旁白/原声；--audio 保留兼容")
    p.add_argument("--audio-fit", choices=["video", "shortest"], default="video",
                   help="兼容旧版；shortest 仅在只有旁白时走旧 mux")
    p.add_argument("--bgm", help="背景音乐；自动循环并在旁白出现时 ducking")
    p.add_argument("--sfx-plan", help="额外 SFX plan JSON")
    p.add_argument("--no-annotation-sfx", action="store_true", help="忽略 annotation 中的 sfx 事件")
    p.add_argument("--subtitles", help="要烧录的 SRT 字幕")
    p.add_argument("--subtitle-font", default="Arial")
    p.add_argument("--subtitle-font-size", type=int)
    p.add_argument("--subtitle-margin-v", type=int)
    p.add_argument("--narration-gain-db", type=float, default=0.0)
    p.add_argument("--bgm-gain-db", type=float, default=-18.0)
    p.add_argument("--duck-ratio", type=float, default=8.0)
    p.add_argument("--max-drift-ms", type=int, default=250)
    p.add_argument("--timeline-mode", choices=["sequence", "startMs"], default="sequence")
    p.add_argument("--no-retime", action="store_true")
    p.add_argument("--gap-ms", type=int, default=None)
    p.add_argument("--lead-in-ms", type=int, default=None)
    p.add_argument("--gaze-ms", type=int, default=None)
    p.add_argument("--total-ms", type=int, default=None)
    p.add_argument("--strict-aspect", action="store_true")
    p.add_argument("--keep-intermediate", action="store_true")
    p.add_argument("--hand", default=str(rsw.DEFAULT_HAND))
    p.add_argument("--bare-tip", action="store_true")
    p.add_argument("--fps", type=int, default=None)
    p.add_argument("--cap-long-edge", type=int, default=None)
    p.add_argument("--canvas-hex", default=None)
    p.add_argument("--ink-path", choices=["grid", "skeleton"], default=None)
    p.add_argument("--color-fill", choices=["contour-wipe", "brush"], default=None)
    p.add_argument("--target-hand-height", type=int, default=None)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    try:
        profile = load_profile(args.profile)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[err] {exc}"); return 1
    cfg = _profile_cfg(profile, args)

    image = sr._imread_any(args.image)
    if image is None:
        print(f"[err] 无法读取图片: {args.image}"); return 1
    h, w = image.shape[:2]
    try:
        _aspect_warning(profile, w, h, args.strict_aspect)
    except ValueError as exc:
        print(f"[err] {exc}"); return 1

    ann_path = Path(args.annotation)
    try:
        annotation = json.loads(ann_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[err] 无法读取 annotation: {exc}"); return 1

    timeline = profile.get("timeline") or {}
    if not args.no_retime:
        annotation = at.normalize_timeline(
            annotation,
            mode=args.timeline_mode,
            gap_ms=args.gap_ms if args.gap_ms is not None else int(timeline.get("gap_ms", 180)),
            lead_in_ms=args.lead_in_ms if args.lead_in_ms is not None else timeline.get("lead_in_ms"),
            gaze_ms=args.gaze_ms if args.gaze_ms is not None else int(timeline.get("gaze_ms", 500)),
        )

    findings = at.validate_annotation(annotation, image_size=(w, h))
    findings.extend(ps.validate_polygon_fields(annotation))
    if not args.no_annotation_sfx:
        findings.extend(validate_sfx_fields(annotation))
    for finding in findings:
        prefix = "ERR" if finding["severity"] == "error" else "WARN"
        element = f" [{finding['element']}]" if finding.get("element") else ""
        print(f"[{prefix}] {finding['code']}{element}: {finding['message']}")
    if any(f["severity"] == "error" for f in findings):
        return 1

    annotation_sfx = [] if args.no_annotation_sfx else collect_scene_sfx(annotation, ann_path)
    missing_sfx = [e["file"] for e in annotation_sfx if not Path(e["file"]).is_file()]
    if missing_sfx:
        print("[err] annotation SFX 文件不存在: " + ", ".join(missing_sfx)); return 1

    total_ms = args.total_ms or int(annotation.get("sceneDurationMs") or 0)
    if not total_ms:
        total_ms = max(e["reveal"]["startMs"] + e["reveal"]["durationMs"] for e in annotation["elements"]) + 500

    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    raw = out.with_name(out.stem + "_raw.mp4")
    phase4_features = bool(args.bgm or args.sfx_plan or args.subtitles or annotation_sfx)
    legacy_shortest = bool(args.narration and args.audio_fit == "shortest" and not phase4_features)
    needs_assembly = bool(args.narration or phase4_features) and not legacy_shortest
    video_only = out if not (needs_assembly or legacy_shortest) else out.with_name(out.stem + "_video.mp4")

    hand_png = Path(args.hand) if args.hand else None
    renderer = PolygonRegionStreamRenderer(image, annotation, cfg, hand_png, args.bare_tip)
    polygon_count = sum(1 for e in annotation["elements"] if e.get("maskPolygon"))
    print(f"[profile] {profile.get('name', args.profile)}")
    print(f"[render] {renderer.out_w}x{renderer.out_h} @ {cfg.fps}fps, canvas={cfg.canvas_hex}")
    print(f"[timeline] mode={args.timeline_mode}, elements={len(annotation['elements'])}, polygons={polygon_count}, total={total_ms}ms")

    renderer.render_to(raw, total_ms)
    final_video = sr.transcode_h264(raw, video_only)
    final = final_video

    if legacy_shortest:
        final = mux_audio(final_video, args.narration, out, fit="shortest")
    elif needs_assembly:
        try:
            final = assemble_media(
                final_video, out,
                narration=args.narration,
                bgm=args.bgm,
                sfx_plan=args.sfx_plan,
                sfx_events=annotation_sfx,
                subtitles=args.subtitles,
                subtitle_font=args.subtitle_font,
                subtitle_font_size=args.subtitle_font_size,
                subtitle_margin_v=args.subtitle_margin_v,
                narration_gain_db=args.narration_gain_db,
                bgm_gain_db=args.bgm_gain_db,
                duck_ratio=args.duck_ratio,
                max_drift_ms=args.max_drift_ms,
            )
        except (RuntimeError, ValueError, OSError) as exc:
            print(f"[err] 最终音视频装配失败: {exc}"); return 1

    if not args.keep_intermediate:
        if raw.exists() and raw != final:
            raw.unlink(missing_ok=True)
        if video_only.exists() and video_only != final:
            video_only.unlink(missing_ok=True)

    print(f"OUTPUT={final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
