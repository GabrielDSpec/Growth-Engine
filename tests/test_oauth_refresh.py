import json
import tempfile
import unittest
from unittest.mock import patch

from core.database import get_connection, salvar_perfil_google
from core.google_oauth import criar_url_autorizacao
from core.publisher import _youtube_client


class OAuthRefreshTests(unittest.TestCase):
    def test_authorization_requests_offline_consent(self):
        class FakeFlow:
            code_verifier = "verifier"

            def authorization_url(self, **kwargs):
                self.arguments = kwargs
                return "https://accounts.google.test/auth", "ignored"

        flow = FakeFlow()
        with patch("core.google_oauth.criar_fluxo_oauth", return_value=flow), patch(
            "core.google_oauth.secrets.token_urlsafe", return_value="state"
        ):
            state, url, verifier = criar_url_autorizacao(include_publish=True)

        self.assertEqual((state, url, verifier), ("state", "https://accounts.google.test/auth", "verifier"))
        self.assertEqual(flow.arguments["access_type"], "offline")
        self.assertEqual(flow.arguments["prompt"], "consent")

    def test_reconnect_without_new_refresh_token_preserves_old_value(self):
        with tempfile.TemporaryDirectory() as directory, patch("core.database.DB_PATH", f"{directory}/oauth.db"):
            salvar_perfil_google(
                "Canal", "https://youtube.test/channel", "channel-1", "Canal", "account-1", "[]",
                b"access-1", b"refresh-old", None, perfil_id=1,
            )
            salvar_perfil_google(
                "Canal atualizado", "https://youtube.test/channel", "channel-1", "Canal atualizado", "account-1", "[]",
                b"access-2", None, None, perfil_id=1,
            )
            conn = get_connection()
            try:
                row = conn.execute("SELECT access_token_ciphertext, refresh_token_ciphertext FROM perfis_google WHERE canal_id='channel-1'").fetchone()
            finally:
                conn.close()

        self.assertEqual(row["access_token_ciphertext"], b"access-2")
        self.assertEqual(row["refresh_token_ciphertext"], b"refresh-old")

    @patch("core.publisher.build")
    @patch("core.publisher.Credentials")
    @patch("core.publisher.decifrar_token", side_effect=lambda value: value.decode("utf-8") if isinstance(value, bytes) else value)
    @patch("core.publisher.get_connection")
    @patch("core.publisher.init_db")
    def test_publisher_credentials_include_current_access_and_refresh_tokens(self, _init_db, get_connection_mock, _decifrar, credentials_mock, build_mock):
        get_connection_mock.return_value.execute.return_value.fetchone.return_value = {
            "access_token_ciphertext": b"access-current",
            "refresh_token_ciphertext": b"refresh-stable",
            "scopes": json.dumps([
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube",
                "https://www.googleapis.com/auth/youtube.force-ssl",
            ]),
        }
        credentials_mock.return_value = object()

        _youtube_client(perfil_id=7)

        kwargs = credentials_mock.call_args.kwargs
        self.assertEqual(kwargs["token"], "access-current")
        self.assertEqual(kwargs["refresh_token"], "refresh-stable")
        self.assertEqual(kwargs["token_uri"], "https://oauth2.googleapis.com/token")
        self.assertIn("client_id", kwargs)
        self.assertIn("client_secret", kwargs)
        build_mock.assert_called_once()
        get_connection_mock.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
