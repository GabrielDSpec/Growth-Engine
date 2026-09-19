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
        self.assertIn("segment.texto", cuts)
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
        self.assertIn("task-review-details", cuts)
        self.assertIn("candidate-toggle", cuts)
        self.assertIn("render-selected-cuts", cuts)
        self.assertNotIn("innerHTML", cuts)


if __name__ == "__main__":
    unittest.main()
