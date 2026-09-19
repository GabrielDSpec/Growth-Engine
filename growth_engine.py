import os
import sys

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from core.database import init_db
from core.profiles import selecionar_perfil_canal
from core.sync_channel import sincronizar_canal_youtube
from core.autopsia import listar_ranking, rodar_autopsia_com_qwen, auditar_amostra_empirica
from core.autopsia import listar_ranking, rodar_autopsia_com_qwen, rodar_autopsia_top15, auditar_amostra_empirica
from core.transcriber import pre_transcrever_pendentes
from core.cutter import executar_cortes
from core.scheduler import executar_agendamento
from core.pipeline import rodar_pipeline_completo


nome_dinamico = "canal"

print(f"⚡ EXECUTANDO ARQUIVO: {__file__} (PID: {os.getpid()})")


def menu_principal():
    while True:
        print("\n" + "="*50)
        print(f"🎯 GROWTH ENGINE - PAINEL DE CONTROLE ({nome_dinamico})")
        print("="*50)
        print("  [1] 🧠 Analisar Títulos e Cliques (Qwen + Metadados))")
        print("  [2] ✂️ Executar Garimpo e Corte (Longos ➔ Shorts)")
        print("  [8] 👁️ Prévia dos cortes (sem renderizar/mover arquivos)")
        print("  [3] 🔄 Forçar resync do canal com o YouTube")
        print("  [4] 🔬 Analisar Roteiros e Retenção (Qwen + Whisper)")
        print("  [5] 🎙️ Pré-transcrever base pendente (Cache perpétuo)")
        print("  [6] 🚀 Executar Agendamento/Upload (Playwright)")
        print("  [7] 🚂 RODAR PIPELINE COMPLETO (Corte + Agendamento)")
        print("  [0] 🚪 Sair")
        print("="*50)
        
        escolha = input("👉 Escolha uma opção: ").strip()
        
        if escolha == '1':
            rodar_autopsia_top15()
        elif escolha == '2':
            executar_cortes()
        elif escolha == '8':
            executar_cortes(dry_run=True)
        elif escolha == '3':
            url = selecionar_perfil_canal()
            if url:
                sincronizar_canal_youtube(url)
        elif escolha == '4':
            auditar_amostra_empirica(2, 2)
        elif escolha == '5':
            pre_transcrever_pendentes()
        elif escolha == '6':
            executar_agendamento()
        elif escolha == '7':
            rodar_pipeline_completo()
        elif escolha == '0':
            print("👋 Saindo da Growth Engine. Até logo!")
            sys.exit(0)
        else:
            print("⚠️ Opção inválida, tente novamente.")

if __name__ == "__main__":
    init_db()
    print("🚀 Iniciando Growth Engine...")
    url_canal_selecionado = selecionar_perfil_canal()
    if url_canal_selecionado:
        nome_dinamico = url_canal_selecionado.rstrip('/').split('/')[-1] or "canal"
        print(f"🎯 Canal ativo: {nome_dinamico}")

    menu_principal()