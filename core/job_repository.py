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


def update_job(job_id, status=None, progress=None, message=None, error=None, result=None, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        updates = ["atualizado_em=CURRENT_TIMESTAMP"]
        values = []
        for column, value in (("status", status), ("progresso", progress), ("mensagem", message), ("erro", error), ("resultado_json", result)):
            if value is not None:
                updates.append(f"{column}=?")
                values.append(value)
        if status == "running":
            updates.append("iniciado_em=COALESCE(iniciado_em, CURRENT_TIMESTAMP)")
        if status in {"completed", "failed", "rejected", "interrupted", "cancelled", "needs_review"}:
            updates.append("concluido_em=CURRENT_TIMESTAMP")
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


def recover_running_jobs():
    init_db()
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE tarefas_jobs
            SET status='interrupted', mensagem='Interrompida pela reinicialização do servidor',
                concluido_em=CURRENT_TIMESTAMP, atualizado_em=CURRENT_TIMESTAMP
            WHERE status IN ('queued', 'running')
        """)
        conn.commit()
    finally:
        conn.close()
