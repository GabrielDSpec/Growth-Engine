import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "core" / "canal_inteligencia.db"
LEGACY_PROFILE_ID = 1
SCOPED_TABLES = (
    "videos_historico", "oportunidades_conteudo", "cortes_gerados",
    "analises_conteudo", "tarefas_processamento", "tarefas_jobs",
    "perfis_conteudo", "classificacoes_conteudo", "falhas_classificacao_conteudo",
    "preferencias_usuario", "notificacoes", "perfis_google",
)


def backup_database():
    checkpoint = sqlite3.connect(DB_PATH)
    try:
        checkpoint.execute("PRAGMA wal_checkpoint(FULL)")
    finally:
        checkpoint.close()
    backup = DB_PATH.with_name(f"{DB_PATH.stem}.backup-{datetime.now():%Y%m%d-%H%M%S}{DB_PATH.suffix}")
    shutil.copy2(DB_PATH, backup)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(DB_PATH) + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, Path(str(backup) + suffix))
    return backup


def migrate():
    if not DB_PATH.exists():
        raise FileNotFoundError(DB_PATH)
    backup = backup_database()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS perfis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'canal',
                canal_url TEXT NOT NULL DEFAULT '',
                canal_id TEXT,
                ativo INTEGER NOT NULL DEFAULT 1,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO perfis (id, nome, tipo, canal_url, canal_id)
            VALUES (1, 'Perfil Padrão', 'legacy', '', '')
        """)
        for table in SCOPED_TABLES:
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if not columns:
                continue
            if "perfil_id" not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN perfil_id INTEGER NOT NULL DEFAULT 1 REFERENCES perfis(id)")
            conn.execute(f"UPDATE {table} SET perfil_id=1 WHERE perfil_id IS NULL")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_perfil ON {table}(perfil_id)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_perfis_google_perfil_canal ON perfis_google(perfil_id, canal_id)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()
    return backup


if __name__ == "__main__":
    print(f"BACKUP={migrate()}")
    print("MULTITENANT_MIGRATION_OK")
