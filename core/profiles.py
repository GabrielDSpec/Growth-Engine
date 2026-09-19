import os
import json
from urllib.parse import urlparse

PROFILES_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "profiles.json"))


def validar_url_canal(url):
    parsed = urlparse((url or "").strip())
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"youtube.com", "www.youtube.com", "youtu.be"}

def carregar_perfis():
    if os.path.exists(PROFILES_PATH):
        try:
            with open(PROFILES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def salvar_perfis(perfis):
    with open(PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(perfis, f, ensure_ascii=False, indent=2)

def selecionar_perfil_canal():
    perfis = carregar_perfis()
    
    # 🐣 BOOTSTRAP (PRIMEIRO ACESSO / BASE VAZIA)
    if not perfis:
        print("\n🐣 [PRIMEIRO ACESSO] Nenhum perfil de canal cadastrado.")
        url = input("👉 Digite a URL do canal do YouTube (ex: https://www.youtube.com/@aquelecaradebigode): ").strip()
        nome = input("👉 Nome amigável do perfil (ex: Aquele Cara de Bigode): ").strip() or "Canal Principal"
        
        if not validar_url_canal(url):
            print("⚠️ URL inválida: use um endereço do YouTube.")
            return None
        novo_perfil = {"nome": nome, "url": url}
        perfis.append(novo_perfil)
        salvar_perfis(perfis)
        print(f"✅ Perfil '{nome}' registrado com sucesso em {PROFILES_PATH}!")
        return url

    # 📂 FLUXO PADRÃO (MULTICONTA / SELEÇÃO)
    while True:
        print("\n📂 Perfis de canal cadastrados:")
        for idx, p in enumerate(perfis, 1):
            print(f"  [{idx}] {p['nome']} ➔ {p['url']}")
        print("  [+] Adicionar nova conta")
        
        escolha = input(f"\nEscolha o número (1-{len(perfis)}) ou '+' para cadastrar novo: ").strip()
        
        if escolha == '+':
            url = input("👉 Digite a URL do canal do YouTube: ").strip()
            nome = input("👉 Nome amigável do perfil: ").strip() or f"Canal {len(perfis)+1}"
            if not validar_url_canal(url):
                print("⚠️ URL inválida: use um endereço do YouTube.")
                continue
            novo_perfil = {"nome": nome, "url": url}
            perfis.append(novo_perfil)
            salvar_perfis(perfis)
            print(f"✅ Perfil '{nome}' adicionado!")
            return url
        
        if escolha.isdigit():
            idx = int(escolha) - 1
            if 0 <= idx < len(perfis):
                print(f"🎯 Usando perfil: {perfis[idx]['nome']}")
                return perfis[idx]['url']
        
        print("⚠️ Opção inválida, tente novamente.")