import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from assemble_media import assemble_media
from audio_mix import mix_audio
from burn_subtitles import burn_subtitles
from media_utils import ffmpeg_has_filter, probe_media
from sfx_plan import collect_scene_sfx, validate_sfx_fields
from subtitle_ass import build_ass


class Phase4PureTests(unittest.TestCase):
    def test_ass_timing_and_text(self):
        srt = "1\n00:00:00,250 --> 00:00:01,100\nHello\n"
        ass = build_ass(srt, width=640, height=360, font="Arial")
        self.assertIn("0:00:00.25,0:00:01.10", ass)
        self.assertIn("Hello", ass)

    def test_annotation_sfx_offsets(self):
        ann = {
            "sfx": [{"file": "scene.wav", "startMs": 100, "gainDb": -3}],
            "elements": [{
                "id": "hero", "reveal": {"startMs": 700},
                "sfx": [{"file": "hit.wav", "offsetMs": 50, "gainDb": -6}],
            }],
        }
        events = collect_scene_sfx(ann, "/tmp/project/scene.annotation.json", scene_offset_ms=2000)
        self.assertEqual([e["startMs"] for e in events], [2100, 2750])
        self.assertTrue(events[1]["file"].endswith("/tmp/project/hit.wav"))

    def test_invalid_annotation_sfx_is_rejected(self):
        ann = {
            "sfx": [{"file": "", "startMs": -10, "gainDb": "loud"}],
            "elements": [{"id": "hero", "reveal": {"startMs": 0}, "sfx": {"file": "hit.wav", "offsetMs": "soon"}}],
        }
        codes = [f["code"] for f in validate_sfx_fields(ann)]
        self.assertIn("sfx.file_required", codes)
        self.assertIn("sfx.invalid_time", codes)
        self.assertIn("sfx.invalid_gain", codes)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
class Phase4RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        ffmpeg = shutil.which("ffmpeg")
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=white:s=320x240:d=1.6:r=25", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        str(self.d / "video.mp4")], check=True)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=1.0", str(self.d / "narr.wav")], check=True)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=120:duration=0.5", str(self.d / "bgm.wav")], check=True)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=880:duration=0.12", str(self.d / "sfx.wav")], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_mix_is_fitted_to_target_duration(self):
        out = self.d / "mix.m4a"
        mix_audio(out, duration=1.6, narration=self.d / "narr.wav", bgm=self.d / "bgm.wav",
                  sfx_events=[{"file": str(self.d / "sfx.wav"), "startMs": 700, "gainDb": -6}])
        self.assertAlmostEqual(probe_media(out)["duration"], 1.6, delta=0.08)

    def test_burn_subtitles_keeps_duration(self):
        if not ffmpeg_has_filter("ass"):
            self.skipTest("ffmpeg has no ass/libass filter")
        srt = self.d / "cap.srt"
        srt.write_text("1\n00:00:00,200 --> 00:00:01,000\nHello\n", encoding="utf-8")
        out = self.d / "sub.mp4"
        burn_subtitles(self.d / "video.mp4", srt, out, font="Arial")
        self.assertAlmostEqual(probe_media(out)["duration"], 1.6, delta=0.08)

    def test_full_assembly_has_audio_and_keeps_duration(self):
        if not ffmpeg_has_filter("ass"):
            self.skipTest("ffmpeg has no ass/libass filter")
        srt = self.d / "cap.srt"
        srt.write_text("1\n00:00:00,200 --> 00:00:01,000\nHello\n", encoding="utf-8")
        plan = self.d / "sfx.json"
        plan.write_text(json.dumps({"events": [{"file": "sfx.wav", "startMs": 650, "gainDb": -6}]}), encoding="utf-8")
        out = self.d / "final.mp4"
        assemble_media(self.d / "video.mp4", out, narration=self.d / "narr.wav",
                       bgm=self.d / "bgm.wav", sfx_plan=plan, subtitles=srt,
                       subtitle_font="Arial", max_drift_ms=100)
        info = probe_media(out)
        self.assertTrue(info["hasAudio"])
        self.assertTrue(info["hasVideo"])
        self.assertAlmostEqual(info["duration"], 1.6, delta=0.08)


if __name__ == "__main__":
    unittest.main()
