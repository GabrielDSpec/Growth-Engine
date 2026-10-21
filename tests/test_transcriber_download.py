import os
import unittest
from unittest.mock import patch

from core.transcriber import _youtube_audio_options


class YouTubeDownloadTests(unittest.TestCase):
    def test_audio_options_enable_resilience_and_javascript(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GROWTH_ENGINE_YOUTUBE_COOKIES", None)
            os.environ.pop("GROWTH_ENGINE_YOUTUBE_COOKIES_FROM_BROWSER", None)
            options = _youtube_audio_options("C:/temp/audio")
        self.assertEqual(options["socket_timeout"], 30)
        self.assertEqual(options["retries"], 4)
        self.assertEqual(options["fragment_retries"], 4)
        self.assertEqual(options["js_runtimes"], {"node": {}})
        self.assertTrue(options["noplaylist"])

    def test_audio_options_accept_cookie_file_or_browser(self):
        with patch.dict(os.environ, {"GROWTH_ENGINE_YOUTUBE_COOKIES": "C:/temp/cookies.txt"}, clear=False):
            options = _youtube_audio_options("C:/temp/audio")
        self.assertEqual(options["cookiefile"], "C:/temp/cookies.txt")

        with patch.dict(os.environ, {"GROWTH_ENGINE_YOUTUBE_COOKIES": "", "GROWTH_ENGINE_YOUTUBE_COOKIES_FROM_BROWSER": "chrome"}, clear=False):
            options = _youtube_audio_options("C:/temp/audio")
        self.assertEqual(options["cookiesfrombrowser"], ("chrome",))


if __name__ == "__main__":
    unittest.main()