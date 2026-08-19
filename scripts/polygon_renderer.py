#!/usr/bin/env python3
"""Polygon-aware extension of the upstream region stream renderer.

Schema additions (all coordinates use the annotation canvas coordinate system):
- element.maskPolygon: optional polygon limiting the element's drawable shape.
- element.reveal.protectedPolygons: optional polygons to subtract from this element.

Legacy rectangular region/protectedRegions remain fully supported.
"""
from __future__ import annotations

import cv2
import numpy as np

import polygon_schema as ps
import render_stream_whiteboard as base


def _scaled_polygon(polygon, sx: float, sy: float, out_w: int, out_h: int) -> np.ndarray | None:
    points = ps.normalize_polygon(polygon)
    if len(points) < 3:
        return None
    scaled = []
    for point in points:
        x = int(round(point["x"] * sx))
        y = int(round(point["y"] * sy))
        x = max(0, min(out_w - 1, x))
        y = max(0, min(out_h - 1, y))
        scaled.append([x, y])
    return np.asarray(scaled, dtype=np.int32)


def _paint_element_shape(mask: np.ndarray, element: dict, sx: float, sy: float, value: bool) -> None:
    polygon = _scaled_polygon(element.get("maskPolygon"), sx, sy, mask.shape[1], mask.shape[0])
    if polygon is not None:
        layer = np.zeros(mask.shape, dtype=np.uint8)
        cv2.fillPoly(layer, [polygon], 255)
        mask[layer > 0] = value
        return
    x0, y0, x1, y1 = base._scaled_rect(element["region"], sx, sy, mask.shape[1], mask.shape[0])
    mask[y0:y1, x0:x1] = value


def _subtract_polygon(mask: np.ndarray, polygon, sx: float, sy: float) -> None:
    scaled = _scaled_polygon(polygon, sx, sy, mask.shape[1], mask.shape[0])
    if scaled is None:
        return
    layer = np.zeros(mask.shape, dtype=np.uint8)
    cv2.fillPoly(layer, [scaled], 255)
    mask[layer > 0] = False


class PolygonRegionStreamRenderer(base.RegionStreamRenderer):
    """RegionStreamRenderer with polygon masks while preserving legacy rectangle behavior."""

    def _allowed_mask(self, element: dict, later_elements: list[dict]) -> np.ndarray:
        mask = np.zeros((self.out_h, self.out_w), dtype=bool)
        _paint_element_shape(mask, element, self.sx, self.sy, True)

        # Future content is subtracted using its polygon when available; otherwise region.
        for later in later_elements:
            _paint_element_shape(mask, later, self.sx, self.sy, False)

        reveal = element.get("reveal") or {}
        for protected in reveal.get("protectedRegions") or []:
            px0, py0, px1, py1 = base._scaled_rect(protected, self.sx, self.sy, self.out_w, self.out_h)
            mask[py0:py1, px0:px1] = False
        for polygon in reveal.get("protectedPolygons") or []:
            _subtract_polygon(mask, polygon, self.sx, self.sy)
        return mask
