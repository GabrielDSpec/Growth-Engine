import os
import tempfile
import unittest
from unittest.mock import patch

from core.media_tools import MediaToolError, _run, renderizar_corte


class MediaToolsTests(unittest.TestCase):
    def test_run_rejects_nonzero_returncode(self):
        with patch('core.media_tools.subprocess.run', return_value=type('Result', (), {'returncode': 1, 'stderr': 'ffmpeg failed', 'stdout': ''})()):
            with self.assertRaises(MediaToolError):
                _run(['ffmpeg'], 5)

    def test_run_converts_timeout_to_media_error(self):
        import subprocess
        with patch('core.media_tools.subprocess.run', side_effect=subprocess.TimeoutExpired(['ffmpeg'], 5)):
            with self.assertRaises(MediaToolError):
                _run(['ffmpeg'], 5)

    def test_render_rejects_missing_source_before_process(self):
        with self.assertRaises(MediaToolError):
            renderizar_corte('missing.mp4', 'out.mp4', 0, 2)

    def test_render_removes_invalid_partial_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, 'source.mp4')
            output = os.path.join(folder, 'out.mp4')
            open(source, 'wb').close()
            with patch('core.media_tools.obter_duracao', return_value=10), patch('core.media_tools.localizar_ferramentas', return_value=('ffmpeg', 'ffprobe')), patch('core.media_tools._run', side_effect=MediaToolError('timeout')):
                with self.assertRaises(MediaToolError):
                    renderizar_corte(source, output, 0, 2)
            self.assertFalse(os.path.exists(output))


if __name__ == '__main__':
    unittest.main()
