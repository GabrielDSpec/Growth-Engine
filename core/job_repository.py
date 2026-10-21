import json

from core.database import get_connection, init_db
from core.tenant import normalize_profile_id


def create_job(job_id, tipo, video_id, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO tarefas_jobs (job_id, perfil_id, tipo, video_id, status, progresso, mensagem)
            VALUES (?, ?, ?, ?, 'queued', 0, 'Na fila')
        """, (job_id, perfil_id, tipo, video_id))
        conn.commit()
    finally:
        conn.close()


def update_job(job_id, status=None, progress=None, message=None, error=None, result=None, perfil_id=1, stage=None, current_item=None, total_items=None, attempt=None, checkpoint=None):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        updates = ["atualizado_em=CURRENT_TIMESTAMP"]
        values = []
        checkpoint_value = None
        if checkpoint is not None:
            current = conn.execute(
                "SELECT checkpoint_json FROM tarefas_jobs WHERE job_id=? AND perfil_id=?",
                (job_id, perfil_id),
            ).fetchone()
            try:
                existing_checkpoint = json.loads((current[0] if current else None) or "{}")
            except (TypeError, ValueError):
                existing_checkpoint = {}
            if not isinstance(existing_checkpoint, dict):
                existing_checkpoint = {}
            existing_checkpoint.update(checkpoint)
            checkpoint_value = json.dumps(existing_checkpoint, ensure_ascii=False)
        for column, value in (("status", status), ("progresso", progress), ("mensagem", message), ("erro", error), ("resultado_json", result), ("etapa", stage), ("item_atual", current_item), ("total_itens", total_items), ("tentativa", attempt), ("checkpoint_json", checkpoint_value)):
            if value is not None:
                updates.append(f"{column}=?")
                values.append(value)
        if status == "running":
            updates.append("iniciado_em=COALESCE(iniciado_em, CURRENT_TIMESTAMP)")
        if status in {"completed", "failed", "rejected", "interrupted", "cancelled", "needs_review"}:
            updates.append("concluido_em=CURRENT_TIMESTAMP")
            updates.append("duracao_segundos=ROUND((julianday(CURRENT_TIMESTAMP) - julianday(COALESCE(iniciado_em, criado_em))) * 86400, 3)")
        values.extend((job_id, perfil_id))
        conn.execute(f"UPDATE tarefas_jobs SET {', '.join(updates)} WHERE job_id=? AND perfil_id=?", values)
        conn.commit()
    finally:
        conn.close()


def select_job(job_id, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM tarefas_jobs WHERE job_id=? AND perfil_id=?", (job_id, perfil_id)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_active_jobs(perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT job_id, perfil_id, tipo, video_id, status, progresso, mensagem, erro, resultado_json, atualizado_em FROM tarefas_jobs WHERE perfil_id=? AND status IN ('queued', 'running') ORDER BY criado_em",
            (perfil_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_resumable_jobs():
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM tarefas_jobs WHERE status='interrupted' AND concluido_em IS NULL AND tipo IN ('upload_local', 'transcription', 'editorial', 'cut', 'cut_render') ORDER BY atualizado_em"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def recover_running_jobs():
    init_db()
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE tarefas_jobs
            SET status='interrupted', mensagem='Interrompida pela reinicialização do servidor',
                atualizado_em=CURRENT_TIMESTAMP
            WHERE status IN ('queued', 'running', 'cancelling')
        """)
        conn.commit()
    finally:
        conn.close()
