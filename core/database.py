import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "canal_inteligencia.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS perfis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'canal',
            canal_url TEXT NOT NULL DEFAULT '',
            canal_id TEXT,
            ativo INTEGER NOT NULL DEFAULT 1,
            is_admin INTEGER NOT NULL DEFAULT 0,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("INSERT OR IGNORE INTO perfis (id, nome, tipo) VALUES (1, 'Perfil Padrão', 'legacy')")
        cursor.execute(
            "UPDATE perfis SET nome='Aquele Cara de Bigode', tipo='legacy', atualizado_em=CURRENT_TIMESTAMP "
            "WHERE id=1 AND nome='Perfil Padrão'"
        )
        try:
            cursor.execute("ALTER TABLE perfis ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        cursor.execute("UPDATE perfis SET is_admin=1 WHERE id IN (1, 915361)")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS videos_historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT UNIQUE,
            file_hash TEXT,
            titulo TEXT,
            data_publicacao TEXT,
            hora_publicacao TEXT,
            slot_hora TEXT,
            tipo TEXT DEFAULT 'short',
            status TEXT DEFAULT 'agendado',
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            duracao_segundos INTEGER,
            descricao TEXT,
            transcricao TEXT,
            transcricao_segmentos TEXT,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS perfis_google (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            canal_url TEXT NOT NULL,
            canal_id TEXT UNIQUE,
            canal_nome TEXT,
            google_account_id TEXT,
            google_account_email TEXT,
            avatar_url TEXT,
            scopes TEXT NOT NULL DEFAULT '',
            access_token_ciphertext BLOB,
            refresh_token_ciphertext BLOB,
            token_expira_em TEXT,
            fuso_horario TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
            status TEXT NOT NULL DEFAULT 'pendente_conexao',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS analises_conteudo (
            video_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pendente',
            resultado_json TEXT,
            erro TEXT,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS preferencias_usuario (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            bairro TEXT NOT NULL DEFAULT '',
            cidade TEXT NOT NULL DEFAULT '',
            estado TEXT NOT NULL DEFAULT '',
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS oportunidades_conteudo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            contexto TEXT NOT NULL DEFAULT '',
            tema TEXT NOT NULL DEFAULT '',
            fonte TEXT NOT NULL DEFAULT 'autoria interna',
            fonte_url TEXT NOT NULL DEFAULT '',
            atualidade REAL NOT NULL DEFAULT 0,
            relevancia_canal REAL NOT NULL DEFAULT 0,
            potencial_local REAL NOT NULL DEFAULT 0,
            facilidade_gravacao REAL NOT NULL DEFAULT 0,
            potencial_short REAL NOT NULL DEFAULT 0,
            evidencia REAL NOT NULL DEFAULT 0,
            evidencia_json TEXT NOT NULL DEFAULT '{}',
            origem_tipo TEXT NOT NULL DEFAULT 'autoria_interna',
            origem_video_ids TEXT NOT NULL DEFAULT '[]',
            origem_resumo TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'nova',
            criada_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            atualizada_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        for coluna, tipo, padrao in (
            ("evidencia_json", "TEXT", "'{}'"),
            ("origem_tipo", "TEXT", "'autoria_interna'"),
            ("origem_video_ids", "TEXT", "'[]'"),
            ("origem_resumo", "TEXT", "''"),
        ):
            try:
                cursor.execute(f"ALTER TABLE oportunidades_conteudo ADD COLUMN {coluna} {tipo} NOT NULL DEFAULT {padrao}")
            except sqlite3.OperationalError:
                pass
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tarefas_processamento (
            nome TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'idle',
            processados INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0,
            progresso REAL NOT NULL DEFAULT 0,
            mensagem TEXT NOT NULL DEFAULT '',
            erro TEXT,
            iniciado_em TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            concluido_em TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tarefas_jobs (
            job_id TEXT PRIMARY KEY,
            tipo TEXT NOT NULL,
            video_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            progresso REAL NOT NULL DEFAULT 0,
            mensagem TEXT NOT NULL DEFAULT '',
            erro TEXT,
            resultado_json TEXT,
            duracao_segundos REAL,
            etapa TEXT NOT NULL DEFAULT 'queued',
            item_atual INTEGER NOT NULL DEFAULT 0,
            total_itens INTEGER NOT NULL DEFAULT 0,
            tentativa INTEGER NOT NULL DEFAULT 0,
            checkpoint_json TEXT NOT NULL DEFAULT '{}',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            iniciado_em TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            concluido_em TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cortes_gerados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            arquivo_origem TEXT NOT NULL,
            segmento_inicio INTEGER,
            segmento_fim INTEGER,
            inicio_segundos REAL NOT NULL,
            fim_segundos REAL NOT NULL,
            titulo TEXT NOT NULL DEFAULT '',
            gancho TEXT NOT NULL DEFAULT '',
            promessa TEXT NOT NULL DEFAULT '',
            virada TEXT NOT NULL DEFAULT '',
            conclusao TEXT NOT NULL DEFAULT '',
            score_vaca_roxa REAL NOT NULL DEFAULT 0,
            pontuacoes_json TEXT NOT NULL DEFAULT '{}',
            caminho_saida TEXT,
            status TEXT NOT NULL DEFAULT 'pendente',
            erro TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            concluido_em TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS perfis_conteudo (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            resumo TEXT NOT NULL DEFAULT '',
            perfil_json TEXT NOT NULL DEFAULT '{}',
            videos_base INTEGER NOT NULL DEFAULT 0,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS notificacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL DEFAULT 'sistema',
            titulo TEXT NOT NULL,
            mensagem TEXT NOT NULL,
            lida INTEGER NOT NULL DEFAULT 0,
            criada_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS classificacoes_conteudo (
            video_id TEXT PRIMARY KEY,
            tema_abstrato TEXT NOT NULL,
            pilar TEXT NOT NULL,
            formato TEXT NOT NULL,
            peso REAL NOT NULL DEFAULT 0,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS falhas_classificacao_conteudo (
            video_id TEXT PRIMARY KEY,
            motivo TEXT NOT NULL,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_videos_tipo_views ON videos_historico (tipo, views DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_analises_status ON analises_conteudo (status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_classificacoes_tema ON classificacoes_conteudo (tema_abstrato)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_classificacoes_pilar ON classificacoes_conteudo (pilar)")
        for coluna, tipo in (("descricao", "TEXT"), ("hora_publicacao", "TEXT"), ("transcricao", "TEXT"), ("transcricao_segmentos", "TEXT"), ("duracao_segundos", "INTEGER"), ("arquivo_origem", "TEXT")):
            try:
                cursor.execute(f"ALTER TABLE videos_historico ADD COLUMN {coluna} {tipo}")
            except sqlite3.OperationalError:
                pass
        try:
            cursor.execute("ALTER TABLE tarefas_jobs ADD COLUMN duracao_segundos REAL")
        except sqlite3.OperationalError:
            pass
        for coluna, tipo in (("etapa", "TEXT NOT NULL DEFAULT 'queued'"), ("item_atual", "INTEGER NOT NULL DEFAULT 0"), ("total_itens", "INTEGER NOT NULL DEFAULT 0"), ("tentativa", "INTEGER NOT NULL DEFAULT 0"), ("checkpoint_json", "TEXT NOT NULL DEFAULT '{}'")):
            try:
                cursor.execute(f"ALTER TABLE tarefas_jobs ADD COLUMN {coluna} {tipo}")
            except sqlite3.OperationalError:
                pass
        cursor.execute("""
            UPDATE tarefas_jobs
            SET duracao_segundos=ROUND((julianday(concluido_em) - julianday(COALESCE(iniciado_em, criado_em))) * 86400, 3)
            WHERE duracao_segundos IS NULL AND concluido_em IS NOT NULL
        """)
        for coluna, tipo in (("video_titulo", "TEXT"), ("descricao_publicacao", "TEXT NOT NULL DEFAULT ''"), ("nome_rodada", "TEXT"), ("numero_rodada", "INTEGER"), ("selecionado", "INTEGER NOT NULL DEFAULT 0"), ("motivo_rejeicao", "TEXT"), ("montagem_json", "TEXT NOT NULL DEFAULT ''"), ("horario_recomendado_json", "TEXT NOT NULL DEFAULT '{}'")):
            try:
                cursor.execute(f"ALTER TABLE cortes_gerados ADD COLUMN {coluna} {tipo}")
            except sqlite3.OperationalError:
                pass
        for coluna, tipo in (("google_account_email", "TEXT"), ("avatar_url", "TEXT"), ("inscritos", "INTEGER"), ("views_canal", "INTEGER"), ("videos_canal", "INTEGER")):
            try:
                cursor.execute(f"ALTER TABLE perfis_google ADD COLUMN {coluna} {tipo}")
            except sqlite3.OperationalError:
                pass
        for coluna, tipo in (("related_video_id", "TEXT"), ("related_video_title", "TEXT"), ("related_video_status", "TEXT NOT NULL DEFAULT 'pendente'"), ("related_video_error", "TEXT"), ("related_video_updated_at", "TIMESTAMP")):
            try:
                cursor.execute(f"ALTER TABLE cortes_gerados ADD COLUMN {coluna} {tipo}")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute(f"ALTER TABLE videos_historico ADD COLUMN {coluna} {tipo}")
            except sqlite3.OperationalError:
                pass
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_perfis_google_account_email ON perfis_google (google_account_email) WHERE google_account_email IS NOT NULL AND google_account_email <> ''")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_perfis_google_account_id ON perfis_google (google_account_id) WHERE google_account_id IS NOT NULL AND google_account_id <> ''")
        for tabela in ("videos_historico", "oportunidades_conteudo", "cortes_gerados", "analises_conteudo", "tarefas_processamento", "tarefas_jobs", "perfis_conteudo", "classificacoes_conteudo", "falhas_classificacao_conteudo", "preferencias_usuario", "notificacoes", "perfis_google"):
            try:
                cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN perfil_id INTEGER NOT NULL DEFAULT 1 REFERENCES perfis(id)")
            except sqlite3.OperationalError:
                pass
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{tabela}_perfil ON {tabela}(perfil_id)")
        conn.commit()
    finally:
        conn.close()


def registrar_historico(video_id, file_hash, titulo, data_str, hora_str, tipo="short", status="agendado"):
    init_db()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO videos_historico (video_id, file_hash, titulo, data_publicacao, slot_hora, tipo, status, atualizado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(video_id) DO UPDATE SET
            file_hash=excluded.file_hash,
            titulo=excluded.titulo,
            data_publicacao=excluded.data_publicacao,
            slot_hora=excluded.slot_hora,
            tipo=excluded.tipo,
            status=excluded.status,
            atualizado_em=CURRENT_TIMESTAMP
        """, (video_id, file_hash, titulo, data_str, hora_str, tipo, status))
        conn.commit()
    finally:
        conn.close()


def salvar_perfil_google(nome, canal_url, canal_id, canal_nome, google_account_id, scopes,
                         access_token_ciphertext, refresh_token_ciphertext, token_expira_em,
                         google_account_email="", avatar_url="", fuso_horario="America/Sao_Paulo", perfil_id=1):
    init_db()
    conn = get_connection()
    try:
        duplicate = conn.execute("""
            SELECT perfil_id FROM perfis_google
            WHERE perfil_id <> ? AND (
                (? <> '' AND google_account_email = ?)
                OR (? <> '' AND google_account_id = ?)
            )
            LIMIT 1
        """, (perfil_id, google_account_email or "", google_account_email or "", google_account_id or "", google_account_id or "")).fetchone()
        if duplicate:
            raise ValueError(f"Esta conta Google já está adicionada ao perfil {duplicate['perfil_id']}.")
        conn.execute("""
            INSERT INTO perfis_google (
                perfil_id, nome, canal_url, canal_id, canal_nome, google_account_id, google_account_email, avatar_url, scopes,
                access_token_ciphertext, refresh_token_ciphertext, token_expira_em,
                fuso_horario, status, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'conectado', CURRENT_TIMESTAMP)
            ON CONFLICT(canal_id) DO UPDATE SET
                nome=excluded.nome,
                canal_url=excluded.canal_url,
                canal_nome=excluded.canal_nome,
                google_account_id=excluded.google_account_id,
                google_account_email=excluded.google_account_email,
                avatar_url=excluded.avatar_url,
                scopes=excluded.scopes,
                access_token_ciphertext=excluded.access_token_ciphertext,
                refresh_token_ciphertext=COALESCE(excluded.refresh_token_ciphertext, perfis_google.refresh_token_ciphertext),
                token_expira_em=excluded.token_expira_em,
                fuso_horario=excluded.fuso_horario,
                status='conectado',
                atualizado_em=CURRENT_TIMESTAMP
            """, (perfil_id, nome, canal_url, canal_id, canal_nome, google_account_id, google_account_email, avatar_url, scopes,
              access_token_ciphertext, refresh_token_ciphertext, token_expira_em, fuso_horario))
        conn.commit()
    finally:
        conn.close()


def consultar_historico():
    if not os.path.exists(DB_PATH):
        return []
    init_db()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        rows = cursor.execute("SELECT * FROM videos_historico ORDER BY atualizado_em DESC").fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def print_historico():
    registros = consultar_historico()
    if not registros:
        print("📭 Nenhum vídeo registrado na base histórica ainda.")
        return
    print(f"\n📜 HISTÓRICO DE EXECuÇÃO ({len(registros)} registros):")
    print("-" * 65)
    for r in registros:
        print(f"[{r['status'].upper()}] {r['data_publicacao']} às {r['slot_hora']} | {r['titulo'][:35]}... (Views: {r['views']})")
    print("-" * 65)