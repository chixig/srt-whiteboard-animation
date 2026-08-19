import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("render_project_module", ROOT / "scripts" / "render_project.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class ProjectDiscoveryTests(unittest.TestCase):
    def test_natural_scene_order_and_image_match(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for stem in ("scene-10", "scene-2", "scene-1"):
                (root / f"{stem}.annotation.json").write_text("{}", encoding="utf-8")
                (root / f"{stem}.png").write_bytes(b"x")
            scenes = mod.discover_scenes(root)
            self.assertEqual([s["stem"] for s in scenes], ["scene-1", "scene-2", "scene-10"])
            self.assertTrue(all(s["image"] is not None for s in scenes))


if __name__ == "__main__":
    unittest.main()
