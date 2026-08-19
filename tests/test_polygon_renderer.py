import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from polygon_renderer import _paint_element_shape, _subtract_polygon


class PolygonRendererMaskTests(unittest.TestCase):
    def test_polygon_limits_region_shape(self):
        mask = np.zeros((100, 100), dtype=bool)
        element = {
            "region": {"x": 10, "y": 10, "width": 80, "height": 80},
            "maskPolygon": [[20, 20], [80, 20], [50, 80]],
        }
        _paint_element_shape(mask, element, 1.0, 1.0, True)
        self.assertTrue(mask[40, 50])
        self.assertFalse(mask[75, 80])  # inside bbox, outside triangle

    def test_protected_polygon_subtracts_pixels(self):
        mask = np.ones((100, 100), dtype=bool)
        _subtract_polygon(mask, [[40, 40], [60, 40], [60, 60], [40, 60]], 1.0, 1.0)
        self.assertFalse(mask[50, 50])
        self.assertTrue(mask[20, 20])


if __name__ == "__main__":
    unittest.main()
