#!/usr/bin/env python3
"""Suggest visual regions/polygons from a whiteboard source image using deterministic CV.

This is deliberately a visual proposal tool, not semantic understanding. The Agent should
map proposals to subtitle events and may merge/split/reorder them before production.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np


def _imread_any(path: str) -> np.ndarray | None:
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _paper_active_mask(image: np.ndarray, color_threshold: int, dark_threshold: int) -> np.ndarray:
    h, w = image.shape[:2]
    margin = max(3, min(h, w) // 50)
    samples = [image[:margin, :margin], image[:margin, -margin:], image[-margin:, :margin], image[-margin:, -margin:]]
    bg = np.median(np.concatenate([s.reshape(-1, 3) for s in samples]), axis=0)
    distance = np.sqrt(np.square(image.astype(np.float32) - bg.astype(np.float32)).sum(axis=2))
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    bg_gray = float(np.median(cv2.cvtColor(np.uint8([[bg]]), cv2.COLOR_BGR2GRAY)))
    active = (distance >= color_threshold) | (gray <= bg_gray - dark_threshold)
    return active.astype(np.uint8)


def _component_proposals(active: np.ndarray, merge_gap: int, min_area_ratio: float, max_regions: int) -> list[dict]:
    h, w = active.shape
    if merge_gap > 0:
        k = merge_gap * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        grouped = cv2.dilate(active * 255, kernel, iterations=1)
    else:
        grouped = active * 255
    n, labels, stats, _ = cv2.connectedComponentsWithStats((grouped > 0).astype(np.uint8), connectivity=8)
    min_pixels = max(12, int(h * w * min_area_ratio))
    proposals: list[dict] = []
    for cid in range(1, n):
        x, y, bw, bh, _ = stats[cid].tolist()
        crop_label = labels[y:y+bh, x:x+bw] == cid
        crop_active = active[y:y+bh, x:x+bw].astype(bool)
        ink = crop_label & crop_active
        ink_pixels = int(ink.sum())
        if ink_pixels < min_pixels:
            continue
        ys, xs = np.where(ink)
        if not len(xs):
            continue
        x0, y0, x1, y1 = int(xs.min()+x), int(ys.min()+y), int(xs.max()+x), int(ys.max()+y)
        pad = max(4, int(round(min(w, h) * 0.008)))
        x0, y0 = max(0, x0-pad), max(0, y0-pad)
        x1, y1 = min(w-1, x1+pad), min(h-1, y1+pad)

        contour_mask = np.zeros((h, w), dtype=np.uint8)
        contour_mask[y:y+bh, x:x+bw][ink] = 255
        contours, _ = cv2.findContours(contour_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        points = np.vstack([c.reshape(-1, 2) for c in contours if len(c) >= 3]) if contours else np.empty((0, 2), dtype=np.int32)
        if len(points) >= 3:
            hull = cv2.convexHull(points)
            eps = max(2.0, 0.018 * cv2.arcLength(hull, True))
            approx = cv2.approxPolyDP(hull, eps, True).reshape(-1, 2)
            polygon = [{"x": int(px), "y": int(py)} for px, py in approx]
        else:
            polygon = [
                {"x": x0, "y": y0}, {"x": x1, "y": y0},
                {"x": x1, "y": y1}, {"x": x0, "y": y1},
            ]
        proposals.append({
            "inkPixels": ink_pixels,
            "region": {"x": x0, "y": y0, "width": x1-x0+1, "height": y1-y0+1},
            "maskPolygon": polygon,
        })
    proposals.sort(key=lambda p: (-p["inkPixels"], p["region"]["y"], p["region"]["x"]))
    return proposals[:max_regions]


def suggest_regions(image: np.ndarray, *, merge_gap: int = 16, min_area_ratio: float = 0.00008,
                    max_regions: int = 12, color_threshold: int = 24, dark_threshold: int = 22) -> list[dict]:
    active = _paper_active_mask(image, color_threshold=color_threshold, dark_threshold=dark_threshold)
    return _component_proposals(active, merge_gap=merge_gap, min_area_ratio=min_area_ratio, max_regions=max_regions)


def _annotation_template(proposals: list[dict], width: int, height: int, scene_id: str, duration_ms: int) -> dict:
    gap = 180
    lead = 300
    each = max(600, int((max(duration_ms, 1000) - lead - 500 - gap * max(0, len(proposals)-1)) / max(1, len(proposals))))
    cursor = lead
    elements = []
    for i, proposal in enumerate(proposals, start=1):
        elements.append({
            "id": f"proposal-{i:02d}",
            "label": f"候选区域 {i}",
            "sequence": i,
            "narrativeRole": "待 Agent 结合字幕确认",
            "subtitle": "",
            "type": "proposal",
            "region": proposal["region"],
            "maskPolygon": proposal["maskPolygon"],
            "reveal": {"direction": "top_to_bottom", "startMs": cursor, "durationMs": each,
                       "protectedRegions": [], "protectedPolygons": []},
            "handPath": {},
        })
        cursor += each + gap
    return {
        "sceneId": scene_id,
        "canvas": {"width": width, "height": height},
        "storyBasis": "CV 自动区域建议；需 Agent 结合字幕复核语义与顺序",
        "sceneDurationMs": max(duration_ms, cursor - gap + 500),
        "elements": elements,
    }


def _draw_preview(image: np.ndarray, proposals: list[dict], output: Path) -> None:
    out = image.copy()
    for i, proposal in enumerate(proposals, start=1):
        polygon = np.asarray([[p["x"], p["y"]] for p in proposal["maskPolygon"]], dtype=np.int32)
        if len(polygon) >= 3:
            cv2.polylines(out, [polygon], True, (0, 0, 255), 3, cv2.LINE_AA)
        r = proposal["region"]
        cv2.rectangle(out, (r["x"], r["y"]), (r["x"]+r["width"], r["y"]+r["height"]), (255, 80, 0), 2)
        cv2.putText(out, str(i), (r["x"]+6, r["y"]+26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(output.suffix or ".png", out)[1].tofile(str(output))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="白板源图自动区域/Polygon 建议（CV proposal）")
    p.add_argument("image")
    p.add_argument("--output", help="建议 JSON 输出；默认 stdout")
    p.add_argument("--annotation-output", help="同时写 annotation 模板")
    p.add_argument("--preview", help="写带编号/Polygon 的检查图")
    p.add_argument("--scene-id", default=None)
    p.add_argument("--duration-ms", type=int, default=12000)
    p.add_argument("--merge-gap", type=int, default=16)
    p.add_argument("--min-area-ratio", type=float, default=0.00008)
    p.add_argument("--max-regions", type=int, default=12)
    p.add_argument("--color-threshold", type=int, default=24)
    p.add_argument("--dark-threshold", type=int, default=22)
    args = p.parse_args(argv)

    image = _imread_any(args.image)
    if image is None:
        print(f"[err] 无法读取图片: {args.image}", file=sys.stderr)
        return 1
    h, w = image.shape[:2]
    proposals = suggest_regions(image, merge_gap=args.merge_gap, min_area_ratio=args.min_area_ratio,
                                max_regions=args.max_regions, color_threshold=args.color_threshold,
                                dark_threshold=args.dark_threshold)
    payload = {"canvas": {"width": w, "height": h}, "proposalCount": len(proposals), "proposals": proposals,
               "note": "仅为视觉 CV proposal；语义、顺序、拆分/合并需结合字幕复核。"}
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.annotation_output:
        scene_id = args.scene_id or Path(args.image).stem
        ann = _annotation_template(proposals, w, h, scene_id, args.duration_ms)
        Path(args.annotation_output).write_text(json.dumps(ann, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.preview:
        _draw_preview(image, proposals, Path(args.preview))
    print(f"[ok] proposals={len(proposals)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
