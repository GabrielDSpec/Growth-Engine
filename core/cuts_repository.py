import json

from core.database import get_connection, init_db
from core.tenant import normalize_profile_id


def create_cut(job_id, video_id, source_path, data, perfil_id=1, status="pendente", video_title="", round_name=""):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO cortes_gerados
            (job_id, perfil_id, video_id, arquivo_origem, segmento_inicio, segmento_fim,
             inicio_segundos, fim_segundos, titulo, gancho, promessa, virada,
             conclusao, score_vaca_roxa, pontuacoes_json, montagem_json, status, video_titulo, nome_rodada, numero_rodada)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (job_id, perfil_id, video_id, source_path, data.get("segmento_inicio"), data.get("segmento_fim"),
              data["inicio"], data["fim"], data.get("titulo", ""), data.get("gancho", ""),
              data.get("promessa", ""), data.get("virada", ""), data.get("conclusao", ""),
              data.get("score_vaca_roxa", 0), json.dumps(data.get("pontuacoes", {}), ensure_ascii=False), json.dumps(data.get("montagem_intervalos", []), ensure_ascii=False), status,
              video_title, round_name or f"rodada-{data.get('numero_rodada', 1):02d}", data.get("numero_rodada", 1)))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_cut(cut_id, status=None, output_path=None, error=None, selected=None, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        changes = ["atualizado_em=CURRENT_TIMESTAMP"]
        values = []
        for column, value in (("status", status), ("caminho_saida", output_path), ("erro", error), ("selecionado", selected)):
            if value is not None:
                changes.append(f"{column}=?")
                values.append(value)
        if status == "concluido":
            changes.append("concluido_em=CURRENT_TIMESTAMP")
        values.extend((cut_id, perfil_id))
        conn.execute(f"UPDATE cortes_gerados SET {', '.join(changes)} WHERE id=? AND perfil_id=?", values)
        conn.commit()
    finally:
        conn.close()


def update_cut_schedule_recommendation(cut_id, recommendation, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        conn.execute("UPDATE cortes_gerados SET horario_recomendado_json=?, atualizado_em=CURRENT_TIMESTAMP WHERE id=? AND perfil_id=?", (json.dumps(recommendation, ensure_ascii=False), cut_id, perfil_id))
        conn.commit()
    finally:
        conn.close()


def update_cut_title(cut_id, title, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        conn.execute("UPDATE cortes_gerados SET titulo=?, atualizado_em=CURRENT_TIMESTAMP WHERE id=? AND perfil_id=?", (title, cut_id, perfil_id))
        conn.commit()
    finally:
        conn.close()


def list_cycle_cuts(video_id, round_name, perfil_id=1):
    return [cut for cut in list_cuts(video_id=video_id, perfil_id=perfil_id) if cut.get("nome_rodada") == round_name]


def list_cuts(job_id=None, video_id=None, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        clauses, values = ["perfil_id=?"], [perfil_id]
        if job_id:
            clauses.append("job_id=?"); values.append(job_id)
        if video_id:
            clauses.append("video_id=?"); values.append(video_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        cuts = [dict(row) for row in conn.execute(f"SELECT * FROM cortes_gerados{where} ORDER BY id", values).fetchall()]
        for cut in cuts:
            try:
                cut["montagem_intervalos"] = json.loads(cut.get("montagem_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                cut["montagem_intervalos"] = []
            try:
                cut["horario_recomendado"] = json.loads(cut.get("horario_recomendado_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                cut["horario_recomendado"] = {}
            if not cut.get("nome_rodada") or cut["nome_rodada"] == "rodada-01" or "-curadoria-" in cut["nome_rodada"]:
                cut["nome_rodada"] = f"{cut.get('video_titulo') or cut.get('video_id') or 'Vídeo'} · ciclo {str(cut.get('job_id') or cut.get('id'))[:8]}"
        return cuts
    finally:
        conn.close()
