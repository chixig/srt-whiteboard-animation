import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("parse_srt_module", ROOT / "scripts" / "parse_srt.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def cue(i, start, end, text):
    return {"index": i, "startMs": start, "endMs": end, "durMs": end - start, "text": text}


class SemanticGroupingTests(unittest.TestCase):
    def test_transition_boundary(self):
        cues = [
            cue(1, 0, 4800, "故事开始。"),
            cue(2, 5000, 9800, "继续前进"),
            cue(3, 10000, 14800, "事情变化。"),
            cue(4, 15000, 19800, "众人沉默。"),
            cue(5, 20000, 24800, "后来，他做了决定。"),
            cue(6, 25000, 29800, "再次出发"),
            cue(7, 30000, 34800, "天色渐暗。"),
            cue(8, 35000, 39800, "最终抵达。"),
        ]
        scenes = mod.group_scenes(cues, 15, 10, 20, mode="semantic")
        self.assertEqual(scenes[0]["cueRange"], [1, 4])
        self.assertIn("transition:后来", scenes[0]["boundaryReason"])

    def test_duration_mode(self):
        cues = [cue(i + 1, i * 5000, (i + 1) * 5000 - 100, f"cue{i+1}") for i in range(6)]
        scenes = mod.group_scenes(cues, 10, 8, 15, mode="duration")
        self.assertGreaterEqual(len(scenes), 2)


if __name__ == "__main__":
    unittest.main()
