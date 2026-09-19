import os
import shutil
import time
import requests
import re
from tqdm import tqdm
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from core.config import DIRETORIO_PROJETO, PASTA_SHORTS, PASTA_ARQUIVO, HORARIOS_PICO
from core.utils import registrar_log, carregar_cache_metadados, salvar_cache_metadados, calcular_hash_arquivo
from core.database import registrar_historico


def limpar_hashtag_shorts(texto):
    return re.sub(r"(?i)(^|\s)#shorts\b", " ", texto or "").strip()

def gerar_metadados_short(caminho_short):
    t_fmt = os.path.splitext(os.path.basename(caminho_short))[0].replace("_", " ")
    prompt = f"[INST] Responda APENAS PT-BR. Tema: '{t_fmt}'. Crie Descrição magnética + hashtags (DESCRICAO: ...) e 15 tags SEO (TAGS: ...)[/INST]"
    try:
        resp = requests.post("http://localhost:11434/api/generate", json={"model": "qwen2.5:14b", "prompt": prompt, "stream": False}, timeout=45)
        if resp.status_code == 200:
            txt = resp.json().get("response", "")
            if "---" in txt:
                partes = txt.split("---", 1)
                desc = partes[0].replace("DESCRICAO:", "").strip()
                tags = partes[1].replace("TAGS:", "").strip()
                if desc and tags:
                    return desc, tags
    except Exception as e:
        registrar_log(f"Erro metadados {caminho_short}: {e}")
    return f"Detalhes de {t_fmt.lower()} 👀 Comenta aí!", "viral"

def agendar_no_youtube(caminho_video, titulo, descricao, tags, data_str, hora_str, browser_context, file_hash):
    page = browser_context.new_page()
    titulo = limpar_hashtag_shorts(titulo)
    descricao = limpar_hashtag_shorts(descricao)
    try:
        page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        page.evaluate("document.querySelector('#create-icon, ytcp-button-shape#create-button')?.click()")
        time.sleep(1.5)
        page.evaluate("document.querySelector('tp-yt-paper-item:has-text(\"Enviar vídeos\"), ytcp-ve:has-text(\"Enviar vídeos\")')?.click()")
        page.wait_for_selector("input[type='file']", state="attached", timeout=30000)
        page.locator("input[type='file']").first.set_input_files(caminho_video)
        page.wait_for_selector("#textbox", state="visible", timeout=45000)
        textboxes = page.locator("#textbox")
        textboxes.nth(0).fill(titulo.replace("_", " "))
        textboxes.nth(1).fill(descricao)
        try:
            page.locator("tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']").click(timeout=5000)
        except Exception:
            pass
        page.locator("tp-yt-paper-radio-button[name='PUBLIC']").first.click(force=True, timeout=5000)
        page.locator("#second-container").first.click(force=True, timeout=5000)
        time.sleep(1)
        time.sleep(5)
        registrar_historico(
            video_id=os.path.splitext(os.path.basename(caminho_video))[0],
            file_hash=file_hash,
            titulo=titulo,
            data_str=data_str,
            hora_str=hora_str,
            tipo="short",
            status="programado"
        )
        return True
    except Exception as e:
        registrar_log(f"Erro agendar {titulo}: {e}")
        return False
    finally:
        try:
            page.close()
        except Exception:
            pass

def gerar_slots_futuros(quantidade):
    slots = []
    agora, dia_atual, idx = datetime.now(), datetime.now(), 0
    while len(slots) < quantidade:
        slots.append({"data": dia_atual.strftime("%d/%m/%Y"), "hora": HORARIOS_PICO[idx]})
        idx += 1
        if idx >= len(HORARIOS_PICO): idx = 0; dia_atual += timedelta(days=1)
    return slots

def planejar_estrategia_com_ia(videos_info, slots_disponiveis):
    return [{"arquivo": v['arquivo'], "data": slots_disponiveis[i]["data"], "hora": slots_disponiveis[i]["hora"]} for i, v in enumerate(videos_info)]

def executar_agendamento():
    print("========================================")
    print("🚀 FÁBRICA DE AGENDAMENTO (ESTÁGIO 2)")
    print("========================================\n")
    shorts = [f for f in os.listdir(PASTA_SHORTS) if f.endswith(".mp4")]
    if not shorts:
        print("📭 Nenhum short na pasta 'shorts/' para agendar.")
        return

    precisa_logar = input("🚨 Precisa logar no YouTube Studio nesta sessão? (s/n): ").strip().lower() == 's'
    
    cache_meta, v_info = carregar_cache_metadados(), []
    for s in shorts:
        c_short = os.path.join(PASTA_SHORTS, s)
        t = limpar_hashtag_shorts(os.path.splitext(s)[0].replace("_", " "))
        h = calcular_hash_arquivo(c_short)
        desc, tags = (cache_meta[h]["descricao"], cache_meta[h]["tags"]) if h in cache_meta else gerar_metadados_short(c_short)
        if h not in cache_meta: cache_meta[h] = {"arquivo": s, "titulo": t, "descricao": desc, "tags": tags}
        v_info.append({"arquivo": s, "caminho": c_short, "titulo": t, "descricao": desc, "tags": tags})
    salvar_cache_metadados(cache_meta)
    cronograma = planejar_estrategia_com_ia(v_info, gerar_slots_futuros(len(v_info)))
    
    with sync_playwright() as p:
        chrome_profile = os.getenv(
            "GROWTH_ENGINE_CHROME_PROFILE",
            os.path.join(os.getenv("LOCALAPPDATA", DIRETORIO_PROJETO), "GrowthEngine", "ChromeProfile"),
        )
        os.makedirs(chrome_profile, exist_ok=True)
        browser = p.chromium.launch_persistent_context(chrome_profile, headless=False)
        if precisa_logar:
            pg = browser.new_page(); pg.goto("https://studio.youtube.com"); time.sleep(240); pg.close()
        for item in tqdm(cronograma, desc="🚀 Postando no YouTube"):
            v_curr = next((v for v in v_info if v['arquivo'] == item['arquivo']), None)
            if v_curr:
                agendar_no_youtube(v_curr['caminho'], v_curr['titulo'], v_curr['descricao'], v_curr['tags'], item['data'], item['hora'], browser, calcular_hash_arquivo(v_curr['caminho']))
                if os.path.exists(v_curr['caminho']): shutil.move(v_curr['caminho'], os.path.join(PASTA_ARQUIVO, v_curr['arquivo']))
                time.sleep(35)
        browser.close()
    print("✅ Agendamento concluído!")