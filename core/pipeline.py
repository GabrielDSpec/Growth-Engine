import time
from core.cutter import executar_cortes
from core.scheduler import executar_agendamento

def rodar_pipeline_completo():
    print("\n" + "="*50)
    print("🚂 INICIANDO PIPELINE COMPLETO (CORTE + AGENDAMENTO)")
    print("="*50)
    
    # PASSO 1: Cortar tudo que está na pasta 'pracortar'
    print("\n▶️ PASSO 1: Acionando Fábrica de Cortes...")
    executar_cortes()
    
    print("\n⏳ Pausa para respiro do sistema...")
    time.sleep(2)
    
    # PASSO 2: Agendar tudo que foi parar na pasta 'shorts'
    print("\n▶️ PASSO 2: Acionando Upload e Agendamento...")
    executar_agendamento()
    
    print("\n" + "="*50)
    print("🎉 PIPELINE COMPLETO FINALIZADO COM SUCESSO!")
    print("="*50)