from core.database import get_connection, init_db


def atualizar_tarefa(nome, status=None, processados=None, total=None, progresso=None, mensagem=None, erro=None, iniciado=False, concluido=False, perfil_id=1):
    init_db()
    conn = get_connection()
    try:
        existing = conn.execute("SELECT nome FROM tarefas_processamento WHERE nome=? AND perfil_id=?", (nome, perfil_id)).fetchone()
        if not existing:
            conn.execute("INSERT INTO tarefas_processamento (nome, perfil_id) VALUES (?, ?)", (nome, perfil_id))
        changes = []
        values = []
        for column, value in (("status", status), ("processados", processados), ("total", total), ("progresso", progresso), ("mensagem", mensagem), ("erro", erro)):
            if value is not None:
                changes.append(f"{column}=?")
                values.append(value)
        if iniciado:
            changes.append("iniciado_em=CURRENT_TIMESTAMP")
        if concluido:
            changes.append("concluido_em=CURRENT_TIMESTAMP")
        changes.append("atualizado_em=CURRENT_TIMESTAMP")
        values.extend((nome, perfil_id))
        conn.execute(f"UPDATE tarefas_processamento SET {', '.join(changes)} WHERE nome=? AND perfil_id=?", values)
        conn.commit()
    finally:
        conn.close()


def obter_tarefa(nome, perfil_id=1):
    init_db()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM tarefas_processamento WHERE nome=? AND perfil_id=?", (nome, perfil_id)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
