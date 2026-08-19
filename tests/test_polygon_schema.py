import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import polygon_schema as ps


class PolygonSchemaTests(unittest.TestCase):
    def test_valid_polygon_accepts_dict_and_pair_points(self):
        ann = {"canvas": {"width": 100, "height": 80}, "elements": [{
            "label": "subject",
            "maskPolygon": [{"x": 5, "y": 5}, [60, 5], [50, 50], [8, 48]],
            "reveal": {"protectedPolygons": [[[20, 20], [30, 20], [25, 30]]]},
        }]}
        self.assertEqual(ps.validate_polygon_fields(ann), [])

    def test_invalid_polygon_reports_errors(self):
        ann = {"canvas": {"width": 100, "height": 80}, "elements": [{
            "label": "subject",
            "maskPolygon": [[5, 5], [120, 5]],
            "reveal": {"protectedPolygons": [[[20, 20], [30, 20]]]},
        }]}
        codes = [f["code"] for f in ps.validate_polygon_fields(ann)]
        self.assertGreaterEqual(codes.count("polygon.too_few_points"), 2)


if __name__ == "__main__":
    unittest.main()
