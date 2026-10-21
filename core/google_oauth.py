import os
import json
import secrets

from cryptography.fernet import Fernet
from google_auth_oauthlib.flow import Flow

from core.app_secrets import carregar_segredos_no_ambiente


carregar_segredos_no_ambiente()


GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "http://127.0.0.1:4174/oauth/google/callback",
)
if GOOGLE_REDIRECT_URI.startswith("http://127.0.0.1:"):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

SCOPES_READ_ONLY = (
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
)
SCOPES_YOUTUBE = "https://www.googleapis.com/auth/youtube"
SCOPES_YOUTUBE_FORCE_SSL = "https://www.googleapis.com/auth/youtube.force-ssl"
SCOPES_PUBLISH = "https://www.googleapis.com/auth/youtube.upload"


def google_oauth_configured():
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def get_oauth_config(include_publish=False):
    if not google_oauth_configured():
        raise RuntimeError(
            "Configure GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no ambiente antes de conectar o Google."
        )
    scopes = list(SCOPES_READ_ONLY) + [SCOPES_YOUTUBE, SCOPES_YOUTUBE_FORCE_SSL]
    if include_publish:
        scopes.append(SCOPES_PUBLISH)
    return {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "scopes": scopes,
    }


def _client_config():
    config = get_oauth_config()
    return {
        "web": {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "redirect_uris": [config["redirect_uri"]],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def criar_fluxo_oauth(include_publish=False):
    config = get_oauth_config(include_publish=include_publish)
    return Flow.from_client_config(
        _client_config(),
        scopes=config["scopes"],
        redirect_uri=config["redirect_uri"],
    )


def criar_url_autorizacao(include_publish=False):
    flow = criar_fluxo_oauth(include_publish=include_publish)
    state = secrets.token_urlsafe(32)
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return state, url, flow.code_verifier


def concluir_autorizacao(state, authorization_response, code_verifier=None, include_publish=False):
    flow = criar_fluxo_oauth(include_publish=include_publish)
    flow.state = state
    flow.code_verifier = code_verifier
    flow.fetch_token(authorization_response=authorization_response)
    return flow.credentials


def cifrar_token(token):
    chave = os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY")
    if not chave:
        raise RuntimeError("Configure GOOGLE_TOKEN_ENCRYPTION_KEY antes de salvar tokens OAuth.")
    return Fernet(chave.encode("utf-8")).encrypt(token.encode("utf-8"))


def decifrar_token(token_ciphertext):
    chave = os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY")
    if not chave:
        raise RuntimeError("Configure GOOGLE_TOKEN_ENCRYPTION_KEY antes de ler tokens OAuth.")
    return Fernet(chave.encode("utf-8")).decrypt(bytes(token_ciphertext)).decode("utf-8")


def serializar_scopes(scopes):
    return json.dumps(list(scopes or []), ensure_ascii=False)