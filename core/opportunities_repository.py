import json

from core.database import get_connection, init_db
from core.tenant import normalize_profile_id


def insert_opportunity(data):
    perfil_id = normalize_profile_id(data.get("perfil_id"))
    init_db()
    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO oportunidades_conteudo
            (perfil_id, titulo, contexto, tema, fonte, fonte_url, atualidade, relevancia_canal,
             potencial_local, facilidade_gravacao, potencial_short, evidencia,
             evidencia_json, origem_tipo, origem_video_ids, origem_resumo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            perfil_id, data["titulo"], data.get("contexto", ""), data.get("tema", ""),
            data.get("fonte", "autoria interna"), data.get("fonte_url", ""),
            data["atualidade"], data["relevancia_canal"], data["potencial_local"],
            data["facilidade_gravacao"], data["potencial_short"], data["evidencia"],
            json.dumps(data.get("evidencia_json", {}), ensure_ascii=False),
            data.get("origem_tipo", "autoria_interna"),
            json.dumps(data.get("origem_video_ids", []), ensure_ascii=False),
            data.get("origem_resumo", ""),
        ))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def select_opportunities(limit=30, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM oportunidades_conteudo WHERE perfil_id=? ORDER BY atualizada_em DESC LIMIT ?", (perfil_id, limit)
        ).fetchall()]
    finally:
        conn.close()


def select_opportunity(opportunity_id, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM oportunidades_conteudo WHERE id=? AND perfil_id=?", (opportunity_id, perfil_id)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def select_video_names(video_ids, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    if not video_ids:
        return {}
    init_db()
    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in video_ids)
        rows = conn.execute(
            f"SELECT video_id, titulo FROM videos_historico WHERE perfil_id=? AND video_id IN ({placeholders})",
            [perfil_id] + list(video_ids),
        ).fetchall()
        return {row["video_id"]: row["titulo"] for row in rows}
    finally:
        conn.close()


def select_top15_analyzed_videos(perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute("""
            SELECT v.video_id, v.titulo, v.views, v.likes, a.resultado_json
            FROM videos_historico v JOIN analises_conteudo a ON a.video_id=v.video_id AND a.perfil_id=v.perfil_id
            WHERE v.tipo='video' AND v.perfil_id=? AND a.perfil_id=? AND a.status='concluida'
            ORDER BY (CAST(v.views AS INTEGER) + v.likes * 20) DESC LIMIT 15
        """, (perfil_id, perfil_id)).fetchall()]
    finally:
        conn.close()
