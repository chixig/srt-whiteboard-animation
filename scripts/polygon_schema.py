#!/usr/bin/env python3
"""Pure-Python polygon helpers and validation for whiteboard annotations."""
from __future__ import annotations

from typing import Any


def point_xy(point: Any) -> tuple[float, float] | None:
    if isinstance(point, dict):
        x, y = point.get("x"), point.get("y")
    elif isinstance(point, (list, tuple)) and len(point) >= 2:
        x, y = point[0], point[1]
    else:
        return None
    try:
        return float(x), float(y)
    except (TypeError, ValueError):
        return None


def normalize_polygon(polygon: Any) -> list[dict[str, int]]:
    points: list[dict[str, int]] = []
    if not isinstance(polygon, list):
        return points
    for point in polygon:
        xy = point_xy(point)
        if xy is None:
            continue
        x, y = xy
        points.append({"x": int(round(x)), "y": int(round(y))})
    return points


def validate_polygon(polygon: Any, width: int, height: int, *, name: str) -> list[dict]:
    """Validate canvas-edge geometry.

    Polygon coordinates describe geometry edges, so x==width / y==height are valid edge
    coordinates even though they are not pixel indices. The renderer clips them to the
    last output pixel when rasterizing.
    """
    findings: list[dict] = []
    points = normalize_polygon(polygon)
    if len(points) < 3:
        findings.append({"severity": "error", "code": "polygon.too_few_points", "message": f"{name} 至少需要 3 个有效顶点"})
        return findings
    for i, point in enumerate(points):
        x, y = point["x"], point["y"]
        if x < 0 or y < 0 or x > width or y > height:
            findings.append({
                "severity": "error",
                "code": "polygon.out_of_bounds",
                "message": f"{name}[{i}] 超出画布: ({x}, {y})",
            })
    return findings


def validate_polygon_fields(annotation: dict) -> list[dict]:
    canvas = annotation.get("canvas") or {}
    try:
        width = int(canvas.get("width") or 0)
        height = int(canvas.get("height") or 0)
    except (TypeError, ValueError):
        return []
    if width <= 0 or height <= 0:
        return []

    findings: list[dict] = []
    for index, element in enumerate(annotation.get("elements") or []):
        label = str(element.get("label") or element.get("id") or f"element-{index + 1}")
        if "maskPolygon" in element and element.get("maskPolygon") is not None:
            for finding in validate_polygon(element.get("maskPolygon"), width, height, name="maskPolygon"):
                finding["element"] = label
                findings.append(finding)

        reveal = element.get("reveal") or {}
        polygons = reveal.get("protectedPolygons") or []
        if not isinstance(polygons, list):
            findings.append({
                "severity": "error",
                "code": "protected_polygon.invalid_container",
                "element": label,
                "message": "protectedPolygons 必须是 polygon 数组",
            })
            continue
        for pindex, polygon in enumerate(polygons):
            for finding in validate_polygon(polygon, width, height, name=f"protectedPolygons[{pindex}]"):
                finding["element"] = label
                findings.append(finding)
    return findings
