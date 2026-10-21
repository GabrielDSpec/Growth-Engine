import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.transcriber import (
    TranscriptionCancelled,
    _directcompute_finalization_timeout,
    _directcompute_reached_finalization,
    _directcompute_threads,
    _transcricao_dominada_por_marcadores_audio,
    _transcrever_faster_whisper_em_chunks,
)


class TranscriberStepsTests(unittest.TestCase):
    def test_detecta_transcricao_dominada_por_marcadores_acusticos(self):
        marcadores = [
            {"inicio": indice * 2, "fim": indice * 2 + 2, "texto": "[MÚSICA DE FUNDO]"}
            for indice in range(5)
        ]
        self.assertTrue(_transcricao_dominada_por_marcadores_audio(marcadores))
        self.assertFalse(_transcricao_dominada_por_marcadores_audio(marcadores[:2] + [{"inicio": 4, "fim": 8, "texto": "A entrevista começa agora."}]))

    def test_directcompute_finalization_timeout_is_configurable(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_directcompute_finalization_timeout(), 300.0)

        with patch.dict("os.environ", {"WHISPER_DIRECTCOMPUTE_FINALIZATION_TIMEOUT": "45"}, clear=False):
            self.assertEqual(_directcompute_finalization_timeout(), 45.0)

        with patch.dict("os.environ", {"WHISPER_DIRECTCOMPUTE_FINALIZATION_TIMEOUT": "invalid"}, clear=False):
            self.assertEqual(_directcompute_finalization_timeout(), 300.0)

    def test_directcompute_nao_inicia_finalizacao_com_estimativa(self):
        self.assertFalse(_directcompute_reached_finalization(600, 600, False))
        self.assertTrue(_directcompute_reached_finalization(600, 600, True))
        self.assertFalse(_directcompute_reached_finalization(599, 600, True))

    def test_directcompute_threads_e_configuravel(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_directcompute_threads(), 8)
        with patch.dict("os.environ", {"WHISPER_DIRECTCOMPUTE_THREADS": "12"}, clear=False):
            self.assertEqual(_directcompute_threads(), 12)
        with patch.dict("os.environ", {"WHISPER_DIRECTCOMPUTE_THREADS": "invalid"}, clear=False):
            self.assertEqual(_directcompute_threads(), 8)

    def test_resume_skips_completed_audio_chunks(self):
        class Model:
            def __init__(self):
                self.calls = []

            def transcribe(self, _path, **kwargs):
                self.calls.append(kwargs["clip_timestamps"])
                start, end = kwargs["clip_timestamps"]
                segment = SimpleNamespace(start=start + 1, end=min(start + 3, end), text=f"fala {start}")
                return [segment], SimpleNamespace(duration=125)

        with tempfile.TemporaryDirectory() as temporary_dir, patch.dict(
            "os.environ",
            {"WHISPER_CHUNK_SECONDS": "60", "WHISPER_CHUNK_OVERLAP_SECONDS": "0"},
            clear=False,
        ):
            cache_path = str(Path(temporary_dir) / "transcription.json.chunks")
            first_model = Model()
            callback_count = 0

            def cancel_after_first_chunk():
                nonlocal callback_count
                callback_count += 1
                return callback_count > 1

            with self.assertRaises(TranscriptionCancelled):
                _transcrever_faster_whisper_em_chunks(
                    "video.mp4",
                    first_model,
                    125,
                    True,
                    cancel_callback=cancel_after_first_chunk,
                    started_at=time.monotonic(),
                    chunk_cache_path=cache_path,
                )

            self.assertEqual(first_model.calls, [[0.0, 60.0]])

            resumed_model = Model()
            segments, _ = _transcrever_faster_whisper_em_chunks(
                "video.mp4",
                resumed_model,
                125,
                True,
                started_at=time.monotonic(),
                chunk_cache_path=cache_path,
            )

            self.assertEqual(resumed_model.calls, [[60.0, 120.0], [120.0, 125]])
            self.assertEqual([segment["texto"] for segment in segments], ["fala 0.0", "fala 60.0", "fala 120.0"])


if __name__ == "__main__":
    unittest.main()
