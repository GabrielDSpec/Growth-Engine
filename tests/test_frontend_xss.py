import re
import unittest
from pathlib import Path


APP_JS = Path(__file__).parents[1] / "frontend" / "app.js"
SOURCE = APP_JS.read_text(encoding="utf-8")


def function_body(name, occurrence=-1):
    matches = list(re.finditer(rf"function\s+{name}\s*\([^)]*\)\s*\{{", SOURCE))
    start_match = matches[occurrence]
    start = start_match.end()
    depth = 1
    index = start
    while depth and index < len(SOURCE):
        if SOURCE[index] == "{":
            depth += 1
        elif SOURCE[index] == "}":
            depth -= 1
        index += 1
    return SOURCE[start:index - 1]


class FrontendXssContractsTests(unittest.TestCase):
    def test_safe_link_allows_only_http_and_https_and_blocks_javascript(self):
        safe_link = function_body("setSafeLink")
        self.assertIn("http:", safe_link)
        self.assertIn("https:", safe_link)
        self.assertIn("href = '#'", safe_link)
        self.assertIn("aria-disabled", safe_link)

    def test_radar_cards_use_safe_links_and_dom_text(self):
        radar_card = function_body("renderRadarCard")
        self.assertIn("setSafeLink", radar_card)
        self.assertIn("domText", radar_card)
        self.assertNotIn("innerHTML", radar_card)

    def test_cuts_use_text_content_helpers_for_untrusted_content(self):
        cuts = function_body("renderCuts")
        self.assertIn("contentSummary", cuts)
        self.assertNotIn("segment.texto", cuts)
        self.assertIn("cut.titulo", cuts)
        self.assertIn("cut.gancho", cuts)
        self.assertIn("domText", cuts)
        self.assertNotIn("innerHTML", cuts)

    def test_active_opportunity_renderer_does_not_interpolate_html(self):
        opportunities = function_body("renderOpportunities", occurrence=-1)
        self.assertIn("domText", opportunities)
        self.assertNotIn("innerHTML", opportunities)

    def test_cut_job_review_state_is_rendered_without_html_interpolation(self):
        polling = function_body("pollCutJob")
        cuts = function_body("renderCuts")
        self.assertIn("needs_review", polling)
        self.assertIn("parseJobDiagnostics", cuts)
        self.assertIn("renderedCandidates", cuts)
        self.assertIn("candidato(s) encontrado(s) neste bloco", cuts)
        self.assertIn("nenhum candidato local foi renderizado nesta rodada", cuts)
        self.assertIn("task-review-details", cuts)
        self.assertIn("candidate-toggle", cuts)
        self.assertIn("render-selected-cuts", cuts)
        self.assertNotIn("innerHTML", cuts)

    def test_related_video_picker_sends_active_profile(self):
        picker = function_body("openRelatedVideoPicker")
        self.assertIn("/api/youtube/related-videos?initial=", picker)
        self.assertIn("X-Profile-Id", picker)
        self.assertIn("activeProfileId", picker)
        self.assertIn("Nenhum vídeo relacionado", picker)
        self.assertIn("no_related_video", picker)

    def test_related_video_picker_supports_scheduled_videos(self):
        source = (Path(__file__).parents[1] / "core" / "web_server.py").read_text(encoding="utf-8")
        self.assertIn("status IN ('publicado', 'publicado_externo', 'programado', 'agendado')", source)

    def test_caption_preview_exposes_horizontal_centering(self):
        self.assertGreaterEqual(SOURCE.count("Centralizar horizontalmente"), 2)
        self.assertIn("caption-center-horizontal", SOURCE)
        self.assertIn("previewText.dataset.positionX = '50'", SOURCE)

    def test_caption_adjustment_can_read_cut_transcription_safely(self):
        self.assertIn("Ler transcrição do corte", SOURCE)
        reader_start = SOURCE.index("async function openCutTranscriptReader")
        reader = SOURCE[reader_start:SOURCE.index("async function generateCutCaptions", reader_start)]
        self.assertIn("/api/transcription?video_id=", reader)
        self.assertIn("segment.texto", reader)
        self.assertNotIn("innerHTML", reader)
        self.assertIn("/api/cuts/caption-transcript", reader)
        self.assertIn("Salvar e voltar ao ajuste", SOURCE)
        self.assertIn("background: var(--panel)", (Path(__file__).parents[1] / "frontend" / "styles.css").read_text(encoding="utf-8"))

    def test_cycle_metadata_replacement_is_scoped_to_job(self):
        self.assertIn("replace-cycle-metadata", SOURCE)
        self.assertIn("/api/cuts/replace-cycle-metadata", SOURCE)
        self.assertIn("data-job-id", SOURCE)

    def test_profile_menu_can_reauthorize_youtube(self):
        self.assertIn("profile-reauthorize", SOURCE)
        self.assertIn("reauthorize=1", SOURCE)

    def test_persisted_cuts_are_not_removed_by_temporal_overlap(self):
        review_cuts = function_body("allReviewCuts")
        self.assertIn("const byId = new Map()", review_cuts)
        self.assertIn("return [...byId.values()]", review_cuts)
        self.assertNotIn("const overlap", review_cuts)

    def test_cut_source_exposes_editorial_status_and_delete_action(self):
        cuts = function_body("renderCuts")
        self.assertIn("has_editorial", cuts)
        self.assertIn("Gerar editorial", cuts)
        self.assertIn("Ler editorial", cuts)
        self.assertIn("delete-editorial-dossier", cuts)
        self.assertIn("editorial-status", cuts)
        self.assertIn("role: 'status'", cuts)
        self.assertNotIn("domButton(selectedCutSource.has_editorial ? 'Editorial disponível'", cuts)
        self.assertLess(cuts.index("transcriptionActions.push(domButton('Apagar editorial'"), cuts.index("transcriptionActions.push(editorialStatus)"))
        self.assertIn("/api/editorial/delete-dossier", function_body("deleteEditorialDossier"))

    def test_editorial_reader_uses_safe_dom_and_dossier_endpoint(self):
        reader = function_body("openEditorialDossier")
        self.assertIn("/api/editorial/dossier?video_id=", reader)
        self.assertIn("melhores_momentos", reader)
        self.assertIn("createElement('article'", reader)
        self.assertNotIn("innerHTML", reader)


if __name__ == "__main__":
    unittest.main()
