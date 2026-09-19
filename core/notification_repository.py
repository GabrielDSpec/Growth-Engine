from core.database import get_connection, init_db
from core.tenant import normalize_profile_id


def insert_notification(titulo, mensagem, tipo="sistema", perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO notificacoes (perfil_id, tipo, titulo, mensagem) VALUES (?, ?, ?, ?)",
            (perfil_id, tipo, titulo, mensagem),
        )
        conn.commit()
    finally:
        conn.close()


def select_notifications(limit=30, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM notificacoes WHERE perfil_id=? ORDER BY criada_em DESC, id DESC LIMIT ?",
            (perfil_id, limit),
        ).fetchall()
        unread = conn.execute("SELECT COUNT(*) FROM notificacoes WHERE perfil_id=? AND lida=0", (perfil_id,)).fetchone()[0]
        return {"notificacoes": [dict(row) for row in rows], "nao_lidas": unread}
    finally:
        conn.close()


def mark_notification_read(notification_id, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        conn.execute("UPDATE notificacoes SET lida=1 WHERE id=? AND perfil_id=?", (notification_id, perfil_id))
        conn.commit()
    finally:
        conn.close()


def delete_read_notifications(perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM notificacoes WHERE perfil_id=? AND lida=1", (perfil_id,))
        conn.commit()
    finally:
        conn.close()
