import os
import time

from core.config import DIRETORIO_PROJETO
from core.database import get_connection, init_db
from core.notifications import criar_notificacao
from core.publisher import aguardar_processamento_video


STUDIO_PROFILE_ENV = "GROWTH_ENGINE_CHROME_PROFILE"


def _profile_path():
    return os.getenv(
        STUDIO_PROFILE_ENV,
        os.path.join(os.getenv("LOCALAPPDATA", DIRETORIO_PROJETO), "GrowthEngine", "ChromeProfile"),
    )


def _set_status(short_video_id, perfil_id, status, error=None):
    init_db()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT related_video_id, related_video_title FROM videos_historico WHERE video_id=? AND perfil_id=?",
            (short_video_id, perfil_id),
        ).fetchone()
        conn.execute(
            """
            UPDATE videos_historico
            SET related_video_status=?, related_video_error=?, related_video_updated_at=CURRENT_TIMESTAMP,
                atualizado_em=CURRENT_TIMESTAMP
            WHERE video_id=? AND perfil_id=?
            """,
            (status, error, short_video_id, perfil_id),
        )
        conn.execute(
            """
            UPDATE cortes_gerados
            SET related_video_status=?, related_video_error=?, related_video_updated_at=CURRENT_TIMESTAMP,
                atualizado_em=CURRENT_TIMESTAMP
            WHERE perfil_id=? AND related_video_id=? AND related_video_status IN ('pendente', 'aplicando')
            """,
            (status, error, perfil_id, row["related_video_id"] if row else None),
        )
        conn.commit()
    finally:
        conn.close()
    if status in {"aplicado", "falhou"}:
        title = "Vídeo relacionado aplicado" if status == "aplicado" else "Falha ao aplicar vídeo relacionado"
        message = (
            f"O Short {short_video_id} foi relacionado ao vídeo “{row['related_video_title'] if row else 'selecionado'}”."
            if status == "aplicado"
            else f"Short {short_video_id}: {error or 'o YouTube Studio não confirmou a relação.'}"
        )
        criar_notificacao(title, message, tipo="erro" if status == "falhou" else "sistema", perfil_id=perfil_id)


def _click_first(page, selectors, timeout=5000):
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


def _related_video_title(short_video_id, related_video_id, perfil_id):
    init_db()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT related_video_title FROM videos_historico WHERE video_id=? AND perfil_id=?",
            (short_video_id, perfil_id),
        ).fetchone()
        return row["related_video_title"] if row and row["related_video_title"] else related_video_id
    finally:
        conn.close()


def _select_related_result(page, related_video_id, related_video_title):
    selectors = [
        f"[data-video-id='{related_video_id}']",
        f"[data-video-id=\"{related_video_id}\"]",
    ]
    for selector in selectors:
        try:
            page.locator(selector).filter(visible=True).first.click(timeout=5000)
            return True
        except Exception:
            continue
    for selector in ("ytcp-video-picker-item", "ytcp-video-picker-item-renderer", "[role='option']"):
        try:
            result = page.locator(selector).filter(has_text=related_video_title).filter(visible=True).first
            result.click(timeout=5000)
            return True
        except Exception:
            continue
    return _click_first(page, [f"text={related_video_id}", f"text={related_video_title}"], timeout=5000)


def _capture_studio_diagnostics(page):
    try:
        page.screenshot(path=str(DIRETORIO_PROJETO / "youtube_studio_error.png"), full_page=True)
    except Exception:
        pass
    try:
        html = page.content()
        (DIRETORIO_PROJETO / "youtube_studio_error.html").write_text(html, encoding="utf-8")
    except Exception:
        pass


def _fill_related_search(page, value, timeout_error=Exception):
    selectors = [
        "ytcp-content-pick-dialog input[placeholder*='Pesquisar' i]",
        "ytcp-content-pick-dialog input[placeholder*='Search' i]",
        "ytcp-content-pick-dialog input[type='search']",
        "ytcp-content-pick-dialog input[aria-label*='Pesquisar' i]",
        "ytcp-content-pick-dialog input[aria-label*='Search' i]",
        "ytcp-content-pick-dialog input[type='text']",
        "input[placeholder*='Pesquisar' i]",
        "input[placeholder*='Search' i]",
        "input[aria-label*='Pesquisar' i]",
        "input[aria-label*='Search' i]",
        "ytcp-video-picker-dialog input",
        "ytcp-entity-picker-dialog input",
        "[role='dialog'] input",
        "input:visible",
    ]
    semantic_locators = [
        lambda: page.get_by_placeholder("Pesquise", exact=False).first,
        lambda: page.get_by_role("textbox").first,
    ]
    _click_first(page, [
        "ytcp-content-pick-dialog button[aria-label*='Pesquisar' i]",
        "ytcp-content-pick-dialog button[aria-label*='Search' i]",
        "ytcp-video-picker-dialog button[aria-label*='Pesquisar' i]",
        "ytcp-video-picker-dialog button[aria-label*='Search' i]",
        "[role='dialog'] button[aria-label*='Pesquisar' i]",
        "[role='dialog'] button[aria-label*='Search' i]",
    ], timeout=2500)
    diagnostics_captured = False

    def try_fill(search):
        nonlocal diagnostics_captured
        try:
            search.wait_for(state="visible", timeout=2500)
            search.click(timeout=2500)
            search.fill(value, timeout=5000)
            search.press("Enter")
            return True
        except timeout_error:
            if not diagnostics_captured:
                _capture_studio_diagnostics(page)
                diagnostics_captured = True
            return False

    for selector in selectors:
        try:
            search = page.locator(selector).filter(visible=True).first
            if try_fill(search):
                return True
        except timeout_error:
            if not diagnostics_captured:
                _capture_studio_diagnostics(page)
                diagnostics_captured = True
        except Exception:
            continue
    for locator_factory in semantic_locators:
        try:
            if try_fill(locator_factory()):
                return True
        except timeout_error:
            if not diagnostics_captured:
                _capture_studio_diagnostics(page)
                diagnostics_captured = True
        except Exception:
            continue
    return False


def aplicar_video_relacionado(short_video_id, related_video_id, perfil_id=1):
    """Aplica a relação nativa no Studio usando uma sessão Chrome persistente."""
    if not short_video_id or not related_video_id:
        raise ValueError("IDs de vídeo relacionados são obrigatórios.")
    _set_status(short_video_id, perfil_id, "aplicando")
    criar_notificacao(
        "Aplicando vídeo relacionado",
        f"O YouTube Studio está relacionando o Short {short_video_id} ao vídeo {related_video_id}.",
        perfil_id=perfil_id,
    )
    browser = None
    try:
        criar_notificacao(
            "Aguardando processamento do Short",
            f"O YouTube ainda está preparando o vídeo {short_video_id}; o Studio será aberto quando ele estiver pronto.",
            perfil_id=perfil_id,
        )
        aguardar_processamento_video(short_video_id, perfil_id=perfil_id)
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
        except ImportError as error:
            message = "Playwright não está instalado. Instale com: pip install playwright e playwright install chromium."
            _set_status(short_video_id, perfil_id, "falhou", message)
            return {"status": "falhou", "error": message, "short_video_id": short_video_id, "related_video_id": related_video_id}
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch_persistent_context(
                _profile_path(),
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.new_page()
            page.goto(f"https://studio.youtube.com/video/{short_video_id}/edit", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            if "accounts.google.com" in page.url:
                raise RuntimeError("A sessão do YouTube Studio precisa ser autenticada.")

            related_title = _related_video_title(short_video_id, related_video_id, perfil_id)
            opened = _click_first(page, [
                "ytcp-shorts-content-links-picker #linked-video-editor-link",
                "ytcp-text-dropdown-trigger#linked-video-editor-link",
                "text=Vídeo relacionado",
                "text=Related video",
                "[aria-label*='relacionado' i]",
                "[aria-label*='related video' i]",
            ])
            if not opened:
                raise RuntimeError("O campo de vídeo relacionado não foi encontrado no YouTube Studio.")

            page.wait_for_timeout(1000)
            if not _fill_related_search(page, related_video_id, timeout_error=PlaywrightTimeoutError):
                raise RuntimeError("O campo de busca do vídeo relacionado não apareceu no YouTube Studio.")
            page.wait_for_timeout(1500)
            if not _select_related_result(page, related_video_id, related_title):
                raise RuntimeError("O vídeo relacionado não apareceu nos resultados do Studio.")
            if not _click_first(page, [
                "ytcp-content-pick-dialog ytcp-button#done",
                "ytcp-content-pick-dialog ytcp-button[aria-label='Concluído']",
                "ytcp-content-pick-dialog ytcp-button[aria-label='Done']",
                "text=Concluído",
                "text=Done",
            ], timeout=10000):
                raise RuntimeError("Não foi possível confirmar o vídeo relacionado no Studio.")
            page.wait_for_timeout(1000)
            if not _click_first(page, [
                "ytcp-button#save button",
                "ytcp-button#save",
                "button[aria-label='Salvar']",
                "button[aria-label='Save']",
            ], timeout=10000):
                raise RuntimeError("Não foi possível salvar as alterações do Short no Studio.")
            page.wait_for_timeout(2000)
            _set_status(short_video_id, perfil_id, "aplicado")
            return {"status": "aplicado", "short_video_id": short_video_id, "related_video_id": related_video_id}
    except (RuntimeError, ValueError) as error:
        _set_status(short_video_id, perfil_id, "falhou", str(error))
        return {"status": "falhou", "error": str(error), "short_video_id": short_video_id, "related_video_id": related_video_id}
    except Exception as error:
        _set_status(short_video_id, perfil_id, "falhou", f"Erro inesperado no Studio: {error}")
        return {"status": "falhou", "error": str(error), "short_video_id": short_video_id, "related_video_id": related_video_id}
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
