import json
import os

from core.database import get_connection, init_db
from core.tenant import normalize_profile_id


def create_cut(job_id, video_id, source_path, data, perfil_id=1, status="pendente", video_title="", round_name=""):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        job = conn.execute(
            "SELECT perfil_id, video_id FROM tarefas_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        if job and (int(job["perfil_id"]) != perfil_id or str(job["video_id"]) != str(video_id)):
            raise ValueError(
                f"Identidade inconsistente ao criar corte: job={job_id}, "
                f"esperado perfil_id={job['perfil_id']} video_id={job['video_id']}, "
                f"recebido perfil_id={perfil_id} video_id={video_id}."
            )
        cursor = conn.execute("""
            INSERT INTO cortes_gerados
            (job_id, perfil_id, video_id, arquivo_origem, segmento_inicio, segmento_fim,
             inicio_segundos, fim_segundos, titulo, gancho, promessa, virada,
                         conclusao, descricao_publicacao, score_vaca_roxa, pontuacoes_json, montagem_json, status, video_titulo, nome_rodada, numero_rodada)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (job_id, perfil_id, video_id, source_path, data.get("segmento_inicio"), data.get("segmento_fim"),
              data["inicio"], data["fim"], data.get("titulo", ""), data.get("gancho", ""),
                            data.get("promessa", ""), data.get("virada", ""), data.get("conclusao", ""), data.get("descricao_publicacao", ""),
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


def update_cut_metadata(cut_id, title, description, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        conn.execute("UPDATE cortes_gerados SET titulo=?, descricao_publicacao=?, atualizado_em=CURRENT_TIMESTAMP WHERE id=? AND perfil_id=?", (title.strip(), description.strip(), cut_id, perfil_id))
        conn.commit()
    finally:
        conn.close()


def update_cut_related_video(cut_id, video_id, video_title, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE cortes_gerados
            SET related_video_id=?, related_video_title=?, related_video_status='pendente',
                related_video_error=NULL, related_video_updated_at=CURRENT_TIMESTAMP, atualizado_em=CURRENT_TIMESTAMP
            WHERE id=? AND perfil_id=?
        """, (video_id or None, video_title or None, cut_id, perfil_id))
        conn.commit()
    finally:
        conn.close()


def delete_cuts_for_job(job_id, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, caminho_saida, arquivo_origem FROM cortes_gerados WHERE job_id=? AND perfil_id=?",
            (job_id, perfil_id),
        ).fetchall()
        conn.execute("DELETE FROM cortes_gerados WHERE job_id=? AND perfil_id=?", (job_id, perfil_id))
        conn.commit()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def prune_unavailable_cuts(perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT cuts.id, cuts.caminho_saida
            FROM cortes_gerados cuts
            LEFT JOIN videos_historico videos
              ON videos.video_id=cuts.video_id AND videos.perfil_id=cuts.perfil_id
             AND videos.tipo='video' AND videos.status IN ('upload_local', 'publicado_externo', 'publicado')
            WHERE cuts.perfil_id=?
              AND videos.video_id IS NULL
        """, (perfil_id,)).fetchall()
        removable_ids = [
            row["id"] for row in rows
            if not row["caminho_saida"] or not os.path.isfile(row["caminho_saida"])
        ]
        if removable_ids:
            placeholders = ",".join("?" for _ in removable_ids)
            conn.execute(
                f"DELETE FROM cortes_gerados WHERE perfil_id=? AND id IN ({placeholders})",
                (perfil_id, *removable_ids),
            )
        conn.commit()
        output_paths = [row["caminho_saida"] for row in rows if row["id"] in removable_ids and row["caminho_saida"]]
    finally:
        conn.close()
    for output_path in output_paths:
        if os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
    return len(rows)


def repair_unavailable_completed_cuts(perfil_id=1, video_id=None):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        clauses = ["perfil_id=?", "status='concluido'"]
        values = [perfil_id]
        if video_id:
            clauses.append("video_id=?")
            values.append(video_id)
        rows = conn.execute(
            f"SELECT id, caminho_saida FROM cortes_gerados WHERE {' AND '.join(clauses)}",
            values,
        ).fetchall()
        unavailable_ids = []
        for row in rows:
            try:
                available = bool(row["caminho_saida"]) and os.path.isfile(row["caminho_saida"]) and os.path.getsize(row["caminho_saida"]) > 0
            except OSError:
                available = False
            if not available:
                unavailable_ids.append(row["id"])
        if unavailable_ids:
            placeholders = ",".join("?" for _ in unavailable_ids)
            conn.execute(
                f"UPDATE cortes_gerados SET status='falhou', erro=?, atualizado_em=CURRENT_TIMESTAMP WHERE perfil_id=? AND status='concluido' AND id IN ({placeholders})",
                ("Arquivo físico ausente ou corrompido", perfil_id, *unavailable_ids),
            )
            conn.commit()
        return len(unavailable_ids)
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
        clauses.append("NOT EXISTS (SELECT 1 FROM tarefas_jobs jobs WHERE jobs.job_id=cortes_gerados.job_id AND jobs.perfil_id=cortes_gerados.perfil_id AND jobs.status IN ('cancelled', 'interrupted'))")
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
