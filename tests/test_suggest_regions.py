import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from suggest_regions import suggest_regions


class SuggestRegionsTests(unittest.TestCase):
    def test_two_separated_objects_produce_multiple_proposals(self):
        image = np.full((500, 300, 3), (215, 235, 245), dtype=np.uint8)
        cv2.circle(image, (80, 120), 45, (40, 40, 40), 5)
        cv2.rectangle(image, (180, 280), (260, 390), (40, 40, 40), 5)
        proposals = suggest_regions(image, merge_gap=8, min_area_ratio=0.00002, max_regions=6)
        self.assertGreaterEqual(len(proposals), 2)
        self.assertTrue(all(len(p["maskPolygon"]) >= 3 for p in proposals))


if __name__ == "__main__":
    unittest.main()
