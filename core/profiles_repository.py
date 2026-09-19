from core.database import get_connection, init_db


def create_profile(nome):
    init_db()
    conn = get_connection()
    try:
        cursor = conn.execute("INSERT INTO perfis (nome, tipo) VALUES (?, 'agency')", (nome.strip(),))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def delete_profile(perfil_id):
    if int(perfil_id) == 1:
        raise ValueError("O Perfil Padrão não pode ser removido.")
    init_db()
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for table in ("videos_historico", "oportunidades_conteudo", "cortes_gerados", "analises_conteudo", "tarefas_processamento", "tarefas_jobs", "perfis_conteudo", "classificacoes_conteudo", "falhas_classificacao_conteudo", "preferencias_usuario", "notificacoes", "perfis_google"):
            conn.execute(f"DELETE FROM {table} WHERE perfil_id=?", (perfil_id,))
        deleted = conn.execute("DELETE FROM perfis WHERE id=? AND id<>1", (perfil_id,)).rowcount
        if not deleted:
            raise ValueError("Perfil não encontrado.")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
