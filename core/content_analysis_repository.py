import json

from core.database import get_connection, init_db
from core.tenant import normalize_profile_id


def select_pending_long_videos(limite=None, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        query = """
            SELECT v.video_id, v.titulo, v.descricao, v.data_publicacao,
                   v.tipo, v.views, v.likes, v.transcricao,
                   COALESCE(a.status, 'pendente') AS analise_status
            FROM videos_historico v
            LEFT JOIN analises_conteudo a ON a.video_id = v.video_id AND a.perfil_id = v.perfil_id
            WHERE v.tipo = 'video'
                            AND v.perfil_id = ? AND (a.perfil_id = ? OR a.perfil_id IS NULL)
              AND COALESCE(a.status, 'pendente') <> 'concluida'
            ORDER BY CAST(v.views AS INTEGER) DESC
        """
        params = (perfil_id, perfil_id)
        if limite is not None:
            query += " LIMIT ?"
            params = (perfil_id, perfil_id, limite)
        return [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def mark_processing(video_id, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO analises_conteudo (video_id, perfil_id, status, atualizado_em)
            VALUES (?, ?, 'processando', CURRENT_TIMESTAMP)
            ON CONFLICT(video_id) DO UPDATE SET status='processando', erro=NULL,
            atualizado_em=CURRENT_TIMESTAMP
        """, (video_id, perfil_id))
        conn.commit()
    finally:
        conn.close()


def save_result(video_id, status, resultado, erro=None, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO analises_conteudo (video_id, perfil_id, status, resultado_json, erro, atualizado_em)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(video_id) DO UPDATE SET status=excluded.status,
            resultado_json=excluded.resultado_json, erro=excluded.erro,
            atualizado_em=CURRENT_TIMESTAMP
        """, (video_id, perfil_id, status, json.dumps(resultado, ensure_ascii=False), erro))
        conn.commit()
    finally:
        conn.close()


def save_failure(video_id, error, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE analises_conteudo SET status='falhou', erro=?, atualizado_em=CURRENT_TIMESTAMP WHERE video_id=? AND perfil_id=?",
            (str(error), video_id, perfil_id),
        )
        conn.commit()
    finally:
        conn.close()


def select_analysis_status(perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM videos_historico WHERE tipo='video' AND perfil_id=?", (perfil_id,)).fetchone()[0]
        concluidas = conn.execute("SELECT COUNT(*) FROM analises_conteudo WHERE status='concluida' AND perfil_id=?", (perfil_id,)).fetchone()[0]
        processando = conn.execute("SELECT COUNT(*) FROM analises_conteudo WHERE status='processando' AND perfil_id=?", (perfil_id,)).fetchone()[0]
        return {"total": total, "concluidas": concluidas, "pendentes": max(total - concluidas, 0), "processando": processando}
    finally:
        conn.close()
