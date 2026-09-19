import yt_dlp
import re
from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from core.database import DB_PATH, get_connection, init_db
from core.google_oauth import decifrar_token, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET


def _youtube_api_client(perfil_id=1):
    conn = get_connection()
    try:
        profile = conn.execute(
            "SELECT refresh_token_ciphertext, canal_id FROM perfis_google WHERE perfil_id=? AND status = 'conectado' ORDER BY atualizado_em DESC LIMIT 1",
            (perfil_id,),
        ).fetchone()
    finally:
        conn.close()
    if not profile or not profile["refresh_token_ciphertext"]:
        return None
    refresh_token = decifrar_token(profile["refresh_token_ciphertext"])
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/youtube.readonly"],
    )
    return build("youtube", "v3", credentials=credentials), profile["canal_id"]


def _fetch_api_entries(youtube_api, channel_id, existing_ids=None, pending_ids=None):
    existing_ids = set(existing_ids or [])
    pending_ids = set(pending_ids or [])
    channel = youtube_api.channels().list(part="contentDetails", id=channel_id).execute()
    uploads_id = channel["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    video_ids = []
    page_token = None
    page_count = 0
    max_pages = None if not existing_ids else 2
    while True:
        response = youtube_api.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=uploads_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for item in response.get("items", []):
            video_id = item.get("contentDetails", {}).get("videoId")
            if video_id:
                video_ids.append(video_id)
        page_count += 1
        page_token = response.get("nextPageToken")
        if not page_token or (max_pages and page_count >= max_pages):
            break

    video_ids.extend(video_id for video_id in pending_ids if video_id not in video_ids)

    entries = []
    for start in range(0, len(video_ids), 50):
        response = youtube_api.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(video_ids[start:start + 50]),
        ).execute()
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})
            content_details = item.get("contentDetails", {})
            published_at = snippet.get("publishedAt", "")
            entries.append({
                "id": item["id"],
                "title": snippet.get("title"),
                "description": snippet.get("description"),
                "upload_date": published_at[:10].replace("-", "") if published_at else "",
                "view_count": statistics.get("viewCount"),
                "like_count": statistics.get("likeCount"),
                "duration": _duration_seconds(content_details.get("duration")),
                "api_statistics": statistics,
                "content_duration": content_details.get("duration"),
            })
    return entries


def _duration_seconds(value):
    if not value:
        return None
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return None
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds

def sincronizar_canal_youtube(channel_base_url: str, perfil_id=1, progress_callback=None):
    init_db()
    
    # Limpa a base URL removendo subpaths antigos se houver
    base = channel_base_url.split('/videos')[0].split('/shorts')[0].rstrip('/')
    urls_alvo = [f"{base}/videos", f"{base}/shorts"]
    
    ydl_opts = {
        # Lista IDs sem reprocessar detalhes de vídeos já presentes no cache.
        'extract_flat': True,
        'quiet': True,
        'skip_download': True,
        'ignoreerrors': True,
        'socket_timeout': 30,
        'retries': 1,
        'fragment_retries': 1,
        'js_runtimes': {'node': {}},
    }
    
    conn = get_connection()
    cursor = conn.cursor()
    existing_records = {
        row["video_id"]: dict(row)
        for row in cursor.execute(
            "SELECT video_id, titulo, descricao, data_publicacao, hora_publicacao, tipo, views, likes, duracao_segundos FROM videos_historico WHERE perfil_id=?",
            (perfil_id,),
        ).fetchall()
    }
    existing_likes = {
        video_id: int(record["likes"] or 0)
        for video_id, record in existing_records.items()
    }
    pending_ids = [
        video_id for video_id, record in existing_records.items()
        if not record["likes"]
    ]
    youtube_api = None
    channel_id = None
    try:
        youtube_api, channel_id = _youtube_api_client(perfil_id)
    except Exception as error:
        print(f"⚠️ API YouTube indisponível; usando descoberta alternativa: {error}")
    
    sincronizados = 0
    shorts_count = 0
    videos_count = 0
    seen_ids = set()
    processed_entries = 0
    total_entries = 0

    if youtube_api and channel_id:
        urls_alvo = [f"{base}/videos"]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for url_alvo in urls_alvo:
            if progress_callback:
                formato = "Shorts" if "/shorts" in url_alvo else "vídeos longos"
                progress_callback(processed_entries, total_entries, f"Buscando {formato}...")
            print(f"📡 Conectando ao YouTube para varredura: {url_alvo}...")
            try:
                if youtube_api and channel_id:
                    entries = _fetch_api_entries(
                        youtube_api,
                        channel_id,
                        existing_ids=existing_records,
                        pending_ids=pending_ids,
                    )
                else:
                    result = ydl.extract_info(url_alvo, download=False)
                    entries = result.get('entries', []) or []
            except Exception as e:
                print(f"⚠️ Erro ao varrer {url_alvo}: {e}")
                continue
            total_entries += len(entries)
            if progress_callback:
                progress_callback(processed_entries, total_entries, f"Encontrados {total_entries} vídeos")

            api_statistics = {}
            if youtube_api:
                video_ids = [entry.get("id") for entry in entries if entry and entry.get("id")]
                for start in range(0, len(video_ids), 50):
                    try:
                        response = youtube_api.videos().list(
                            part="statistics",
                            id=",".join(video_ids[start:start + 50]),
                        ).execute()
                        api_statistics.update({
                            item["id"]: item.get("statistics", {})
                            for item in response.get("items", [])
                        })
                    except Exception as error:
                        print(f"⚠️ Não foi possível atualizar estatísticas pela API: {error}")
                        break

            for entry in entries:
                if not entry:
                    continue
                vid_id = entry.get('id')
                if not vid_id or vid_id in seen_ids:
                    continue
                seen_ids.add(vid_id)
                
                cached = existing_records.get(vid_id, {})
                title = entry.get('title') or cached.get('titulo') or 'Sem Título'
                duration = entry.get('duration')
                url_item = str(entry.get('url', '')) or str(entry.get('original_url', ''))
                
                # Força short se veio da aba /shorts ou URL/duração indicarem
                # Shorts podem ter até 3 minutos; a API não fornece um campo
                # confiável separando Short de vídeo comum.
                is_short = ('/shorts/' in url_alvo) or ('/shorts/' in url_item) or (duration is not None and duration <= 180)
                tipo = 'short' if is_short else 'video'
                
                if tipo == 'short':
                    shorts_count += 1
                else:
                    videos_count += 1
                    
                statistics = api_statistics.get(vid_id, {})
                views = int(statistics.get("viewCount") or entry.get("view_count") or 0)
                likes = int(statistics["likeCount"]) if statistics.get("likeCount") is not None else existing_likes.get(vid_id, 0)
                descricao = entry.get('description') or cached.get('descricao') or ''
                data_publicacao = entry.get('upload_date') or cached.get('data_publicacao') or ''
                hora_publicacao = ''
                if entry.get('timestamp'):
                    hora_publicacao = datetime.fromtimestamp(entry['timestamp']).strftime('%H:%M')
                else:
                    hora_publicacao = cached.get('hora_publicacao') or ''
                if len(data_publicacao) == 8:
                    data_publicacao = f"{data_publicacao[:4]}-{data_publicacao[4:6]}-{data_publicacao[6:]}"
                
                cursor.execute("""
                INSERT INTO videos_historico (perfil_id, video_id, titulo, descricao, data_publicacao, hora_publicacao, tipo, status, views, likes, duracao_segundos, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'publicado_externo', ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(video_id) DO UPDATE SET
                    titulo=EXCLUDED.titulo,
                    descricao=CASE WHEN EXCLUDED.descricao <> '' THEN EXCLUDED.descricao ELSE videos_historico.descricao END,
                    data_publicacao=CASE WHEN EXCLUDED.data_publicacao <> '' THEN EXCLUDED.data_publicacao ELSE videos_historico.data_publicacao END,
                    hora_publicacao=CASE WHEN EXCLUDED.hora_publicacao <> '' THEN EXCLUDED.hora_publicacao ELSE videos_historico.hora_publicacao END,
                    views=EXCLUDED.views,
                    likes=EXCLUDED.likes,
                    duracao_segundos=EXCLUDED.duracao_segundos,
                    tipo=EXCLUDED.tipo,
                    atualizado_em=CURRENT_TIMESTAMP
                """, (perfil_id, vid_id, title, descricao, data_publicacao, hora_publicacao, tipo, views, likes, duration))
                sincronizados += 1
                processed_entries += 1
                if progress_callback:
                    progress_callback(processed_entries, total_entries, f"Processando {processed_entries}/{total_entries}")

    conn.commit()
    conn.close()
    print(f"✅ Sincronização concluída! {sincronizados} total processados ({shorts_count} shorts, {videos_count} vídeos longos).")