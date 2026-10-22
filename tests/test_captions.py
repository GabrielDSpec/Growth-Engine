import unittest

from core.caption_styles import INTERNAL_CAPTION_STYLES, validate_style_config
from core.captions import gerar_ass, gerar_cues_relativos


class CaptionGenerationTests(unittest.TestCase):
    def test_cues_are_clipped_and_relative_to_cut(self):
        cues = gerar_cues_relativos(
            [
                {"inicio": 5, "fim": 12, "texto": "antes e durante"},
                {"inicio": 20, "fim": 22, "texto": "fora"},
            ],
            10,
            15,
        )
        self.assertEqual(cues, [{"inicio": 0.0, "fim": 2.0, "texto": "antes e durante"}])

    def test_cues_remove_markup_and_acoustic_markers(self):
        cues = gerar_cues_relativos(
            [{"start": 1, "end": 3, "text": "<b>Olá</b> [música] mundo"}],
            0,
            5,
        )
        self.assertEqual(cues[0]["texto"], "Olá mundo")

    def test_ass_escapes_override_syntax_and_has_timestamps(self):
        ass = gerar_ass(
            [{"inicio": 0, "fim": 1.25, "texto": r"{\an8} linha\\teste"}],
            estilo="bold",
            titulo="Título / teste",
        )
        self.assertIn("Title: Ttulo  teste", ass)
        self.assertIn("PlayResX: 1080", ass)
        self.assertIn("PlayResY: 1920", ass)
        self.assertIn("Style: Default,Arial,60", ass)
        self.assertIn("Dialogue: 0,0:00:00.00,0:00:01.25,Default", ass)
        self.assertIn("(/an8) linha//teste", ass)

    def test_unknown_style_is_rejected(self):
        with self.assertRaises(ValueError):
            gerar_ass([], estilo="unknown")

    def test_custom_font_size_and_position_override_preset(self):
        ass = gerar_ass(
            [{"inicio": 0, "fim": 1, "texto": "configuração"}],
            estilo="clean",
            fonte="Montserrat",
            tamanho=72,
            posicao="top",
        )
        self.assertIn("Style: Default,Montserrat,72", ass)
        self.assertIn(",1,8,60,60,110,1", ass)

    def test_custom_stroke_is_applied_to_ass_style(self):
        ass = gerar_ass([], stroke_cor="coral", stroke_tamanho=6)
        self.assertIn("Style: Default,Arial,54,&H00FFFFFF,&H005CE4FF,&H005B4BFF,&H80000000", ass)
        self.assertIn(",1,6,1,2,60,60,110,1", ass)

    def test_custom_caption_colors_are_applied_to_ass_style(self):
        ass = gerar_ass(
            [],
            cor_texto="#123456",
            cor_destaque="#ABCDEF",
            stroke_cor="#654321",
            cor_fundo="#102030",
            opacidade_fundo=25,
        )
        self.assertIn("Style: Default,Arial,54,&H00563412,&H00EFCDAB,&H00214365,&HBF302010", ass)

    def test_karaoke_uses_relative_word_timestamps(self):
        cues = gerar_cues_relativos(
            [{"inicio": 10, "fim": 12, "texto": "olá mundo", "palavras": [
                {"inicio": 10, "fim": 10.5, "texto": "olá"},
                {"inicio": 10.5, "fim": 12, "texto": "mundo"},
            ]}],
            10,
            12,
            incluir_palavras=True,
        )
        ass = gerar_ass(cues, estilo="highlight", animacao="karaoke")
        self.assertIn("{\\k50}olá {\\k150}mundo", ass)

    def test_karaoke_wraps_long_lines(self):
        cues = gerar_cues_relativos(
            [{"inicio": 0, "fim": 10, "texto": "uma frase longa", "palavras": [
                {"inicio": index * 0.5, "fim": (index + 1) * 0.5, "texto": "palavra"}
                for index in range(12)
            ]}],
            0,
            10,
            incluir_palavras=True,
        )
        ass = gerar_ass(cues, estilo="highlight", tamanho=72, animacao="karaoke")
        self.assertIn("\\N", ass)

    def test_single_line_preserves_large_text(self):
        cues = [{"inicio": 0, "fim": 2, "texto": "uma legenda muito longa para permanecer em uma única linha"}]
        ass = gerar_ass(cues, tamanho=140, uma_linha=True)
        self.assertNotIn("\\N", ass)
        self.assertIn("\\q2", ass)
        self.assertRegex(ass, r"\\fs[0-9]+")

    def test_single_line_karaoke_preserves_word_flow(self):
        cues = gerar_cues_relativos(
            [{"inicio": 0, "fim": 2, "texto": "uma frase longa", "palavras": [
                {"inicio": index * 0.5, "fim": (index + 1) * 0.5, "texto": "palavra"}
                for index in range(12)
            ]}],
            0,
            2,
            incluir_palavras=True,
        )
        ass = gerar_ass(cues, estilo="highlight", tamanho=140, animacao="karaoke", uma_linha=True)
        self.assertNotIn("\\N", ass)

    def test_exact_vertical_position_uses_ass_pos(self):
        cues = [{"inicio": 0, "fim": 2, "texto": "posição exata"}]
        ass = gerar_ass(cues, posicao="bottom", posicao_x=25, posicao_y=37.5)
        self.assertIn("{\\an5\\pos(270,720)}posição exata", ass)

    def test_horizontal_position_preserves_selected_vertical_position(self):
        cues = [{"inicio": 0, "fim": 2, "texto": "posição horizontal"}]
        ass = gerar_ass(cues, posicao="bottom", posicao_x=50)
        self.assertIn("{\\an5\\pos(540,1498)}posição horizontal", ass)

    def test_karaoke_falls_back_to_even_word_distribution(self):
        cues = gerar_cues_relativos(
            [{"inicio": 0, "fim": 2, "texto": "uma frase curta"}],
            0,
            2,
            incluir_palavras=True,
        )
        ass = gerar_ass(cues, estilo="highlight", animacao="karaoke")
        self.assertIn("{\\k67}uma {\\k67}frase {\\k67}curta", ass)

    def test_external_font_requires_explicit_allowlist(self):
        with self.assertRaises(ValueError):
            gerar_ass([], fonte="Minha Fonte")
        ass = gerar_ass([], fonte="Minha Fonte", fontes_permitidas=["Minha Fonte"])
        self.assertIn("Style: Default,Minha Fonte,54", ass)

    def test_highlight_style_allows_karaoke_animation(self):
        config = validate_style_config(INTERNAL_CAPTION_STYLES["highlight"])
        self.assertEqual(config["animation"], "karaoke")


if __name__ == "__main__":
    unittest.main()
