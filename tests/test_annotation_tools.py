import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import annotation_tools as at


class AnnotationToolsTest(unittest.TestCase):
    def sample(self):
        return {
            "canvas": {"width": 1080, "height": 1920},
            "sceneDurationMs": 3000,
            "elements": [
                {
                    "id": "second",
                    "label": "second",
                    "sequence": 2,
                    "region": {"x": 0, "y": 0, "width": 100, "height": 100},
                    "reveal": {"startMs": 0, "durationMs": 1000, "protectedRegions": []},
                },
                {
                    "id": "first",
                    "label": "first",
                    "sequence": 1,
                    "region": {"x": 100, "y": 100, "width": 200, "height": 200},
                    "reveal": {"startMs": 2000, "durationMs": 500, "protectedRegions": []},
                },
            ],
        }

    def test_sequence_is_canonical_and_retimed(self):
        out = at.normalize_timeline(self.sample(), gap_ms=200, lead_in_ms=100, gaze_ms=500)
        self.assertEqual([e["id"] for e in out["elements"]], ["first", "second"])
        self.assertEqual(out["elements"][0]["reveal"]["startMs"], 100)
        self.assertEqual(out["elements"][1]["reveal"]["startMs"], 800)
        self.assertEqual([e["sequence"] for e in out["elements"]], [1, 2])

    def test_out_of_bounds_is_error(self):
        data = self.sample()
        data["elements"][0]["region"] = {"x": 1000, "y": 0, "width": 100, "height": 100}
        findings = at.validate_annotation(data)
        self.assertTrue(any(f["code"] == "region.out_of_bounds" for f in findings))

    def test_valid_normalized_annotation_has_no_errors(self):
        data = at.normalize_timeline(self.sample(), gap_ms=100, lead_in_ms=0)
        findings = at.validate_annotation(data)
        self.assertFalse(any(f["severity"] == "error" for f in findings))


if __name__ == "__main__":
    unittest.main()
