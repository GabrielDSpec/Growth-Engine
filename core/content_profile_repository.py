import json

from core.database import get_connection, init_db
from core.tenant import normalize_profile_id


def select_profile_videos(limite=15, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT v.video_id, v.titulo, v.tipo, v.views, v.likes,
                   a.resultado_json
            FROM videos_historico v
            LEFT JOIN analises_conteudo a ON a.video_id=v.video_id AND a.perfil_id=v.perfil_id AND a.status='concluida'
            WHERE v.tipo='video' AND v.perfil_id=? AND a.status='concluida' AND a.perfil_id=?
            ORDER BY (CAST(v.views AS INTEGER) + (v.likes * 20)) DESC LIMIT ?
        """, (perfil_id, perfil_id, limite)).fetchall()
        data = [dict(row) for row in rows]
    finally:
        conn.close()
    for item in data:
        raw_analysis = item.pop("resultado_json", None)
        if raw_analysis:
            try:
                item["analise"] = json.loads(raw_analysis)
            except json.JSONDecodeError:
                pass
    return data


def save_classifications(classified, failures, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        for video_id, motivo in failures:
            conn.execute("""
                INSERT INTO falhas_classificacao_conteudo (video_id, perfil_id, motivo, atualizado_em)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(video_id) DO UPDATE SET motivo=excluded.motivo,
                atualizado_em=CURRENT_TIMESTAMP
            """, (video_id, perfil_id, motivo))
        for item in classified:
            conn.execute("""
                INSERT INTO classificacoes_conteudo (video_id, perfil_id, tema_abstrato, pilar, formato, peso, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(video_id) DO UPDATE SET tema_abstrato=excluded.tema_abstrato,
                pilar=excluded.pilar, formato=excluded.formato, peso=excluded.peso,
                atualizado_em=CURRENT_TIMESTAMP
            """, (item["video_id"], perfil_id, item["tema_abstrato"], item["pilar"], item["formato"], item["peso"]))
            conn.execute("DELETE FROM falhas_classificacao_conteudo WHERE video_id = ? AND perfil_id = ?", (item["video_id"], perfil_id))
        conn.commit()
        placeholders = ",".join("?" for _ in classified)
        persisted = conn.execute(
            f"SELECT COUNT(*) AS total FROM classificacoes_conteudo WHERE perfil_id=? AND video_id IN ({placeholders})",
            [perfil_id] + [item["video_id"] for item in classified],
        ).fetchone()["total"]
        if persisted != len(classified):
            raise RuntimeError(f"Persistência incompleta das classificações: {persisted}/{len(classified)}")
        return {
            "temas": conn.execute("SELECT tema_abstrato, SUM(peso) AS peso FROM classificacoes_conteudo WHERE perfil_id=? GROUP BY tema_abstrato ORDER BY peso DESC LIMIT 8", (perfil_id,)).fetchall(),
            "pilares": conn.execute("SELECT pilar, SUM(peso) AS peso FROM classificacoes_conteudo WHERE perfil_id=? GROUP BY pilar ORDER BY peso DESC LIMIT 8", (perfil_id,)).fetchall(),
            "formatos": conn.execute("SELECT formato, SUM(peso) AS peso FROM classificacoes_conteudo WHERE perfil_id=? GROUP BY formato ORDER BY peso DESC LIMIT 8", (perfil_id,)).fetchall(),
        }
    finally:
        conn.close()


def save_profile(profile, videos_base, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO perfis_conteudo (id, perfil_id, resumo, perfil_json, videos_base, atualizado_em)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET resumo=excluded.resumo, perfil_json=excluded.perfil_json,
            videos_base=excluded.videos_base, atualizado_em=CURRENT_TIMESTAMP
        """, (perfil_id, perfil_id, profile.get("resumo", ""), json.dumps(profile, ensure_ascii=False), videos_base))
        conn.commit()
    finally:
        conn.close()


def select_profile(perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        row = conn.execute("SELECT resumo, perfil_json, videos_base, atualizado_em FROM perfis_conteudo WHERE perfil_id=?", (perfil_id,)).fetchone()
        if not row:
            return None
        result = json.loads(row["perfil_json"])
        result.update({"resumo": row["resumo"], "videos_base": row["videos_base"], "atualizado_em": row["atualizado_em"]})
        return result
    finally:
        conn.close()
