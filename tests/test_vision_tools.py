import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from core.cutter import _montar_prompt
from core.vision_tools import (
    MediaTrigger,
    _audio_peak_triggers,
    _parse_audio_samples,
    _parse_scene_timestamps,
    annotate_transcript_segments,
    format_annotated_segments_for_prompt,
    detect_audio_peaks,
    detect_scene_changes,
)


class VisionToolsTests(unittest.TestCase):
    def test_scene_cache_avoids_reexecutar_ffmpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            video.write_bytes(b"video")
            output = "[Parsed_showinfo_1 @ 0x1] pts_time:3.500"
            with patch("core.vision_tools._run_ffmpeg", return_value=output) as run_ffmpeg:
                self.assertEqual(detect_scene_changes(video), [MediaTrigger(3.5, "scene_change")])
                self.assertEqual(detect_scene_changes(video), [MediaTrigger(3.5, "scene_change")])
            self.assertEqual(run_ffmpeg.call_count, 1)

    def test_audio_cache_avoids_reexecutar_ffmpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            video.write_bytes(b"video")
            output = "\n".join(["frame:0 pts_time:0.000", "lavfi.astats.Overall.RMS_level=-30.0", "frame:1 pts_time:0.500", "lavfi.astats.Overall.RMS_level=-10.0"])
            with patch("core.vision_tools._run_ffmpeg", return_value=output) as run_ffmpeg:
                self.assertEqual(len(detect_audio_peaks(video)), 1)
                self.assertEqual(len(detect_audio_peaks(video)), 1)
            self.assertEqual(run_ffmpeg.call_count, 1)
    def test_parse_scene_showinfo_timestamps(self):
        output = "[Parsed_showinfo_1 @ 0x1] n: 12 pts_time:3.500\n[Parsed_showinfo_1 @ 0x1] pts_time:9.250"
        self.assertEqual(_parse_scene_timestamps(output), [3.5, 9.25])

    def test_parse_audio_metadata_samples(self):
        output = "\n".join([
            "frame:0 pts_time:0.000",
            "lavfi.astats.Overall.RMS_level=-30.0",
            "frame:1 pts_time:0.500",
            "lavfi.astats.Overall.RMS_level=-10.0",
            "lavfi.astats.Overall.RMS_level=-inf",
        ])
        self.assertEqual(_parse_audio_samples(output), [(0.0, -30.0), (0.5, -10.0)])

    def test_audio_peak_uses_energy_above_baseline(self):
        triggers = _audio_peak_triggers([(0.0, -30.0), (0.5, -10.0), (1.0, -30.0)], 6.0)
        self.assertEqual([trigger.timestamp for trigger in triggers], [0.5])
        self.assertEqual(triggers[0].kind, "audio_peak")

    def test_association_and_semantic_format(self):
        segments = [
            {"indice": 0, "inicio": 0.0, "fim": 2.0, "texto": "Abertura"},
            {"indice": 1, "inicio": 2.1, "fim": 5.0, "texto": "Virada"},
        ]
        triggers = [
            MediaTrigger(1.0, "scene_change"),
            MediaTrigger(4.0, "audio_peak", score=12.0),
        ]
        annotated = annotate_transcript_segments(segments, triggers)
        rendered = format_annotated_segments_for_prompt(annotated)
        self.assertEqual(annotated[0]["roteiro_tags"], ["[🎬 CORTE DE CÂMERA]"])
        self.assertEqual(annotated[1]["roteiro_tags"], ["[🔊 PICO DE ÁUDIO]"])
        self.assertIn("[0] [00:00 - 00:02] [🎬 CORTE DE CÂMERA] Texto: 'Abertura'", rendered)
        self.assertNotIn("score", rendered.lower())

    def test_prompt_explains_multimodal_tags(self):
        prompt = _montar_prompt(
            "[0] 0.000-12.000: Uma fala",
            12,
            [],
            1,
            [],
            [],
            contexto_multimodal="[0] [00:00 - 00:12] [🎬 CORTE DE CÂMERA] Texto: 'Uma fala'",
        )
        self.assertIn("[🎬 CORTE DE CÂMERA]", prompt)
        self.assertIn("[🔊 PICO DE ÁUDIO]", prompt)
        self.assertIn("nunca as inclua no título", prompt)


if __name__ == "__main__":
    unittest.main()
