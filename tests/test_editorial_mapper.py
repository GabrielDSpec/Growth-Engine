import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.editorial_mapper import build_dossier, build_semantic_heatmap, harvest_candidates, load_dossier, load_or_build_dossier


class EditorialMapperTests(unittest.TestCase):
    def test_build_dossier_persists_chapter_description(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video.mp4"
            source.write_bytes(b"video")
            with patch("core.editorial_mapper.obter_pastas_midia", return_value={"editorial_dossiers": directory}):
                dossier = build_dossier(
                    "video-1",
                    1,
                    str(source),
                    [{"inicio": 0, "fim": 10, "texto": "fala"}],
                    10,
                    "",
                    {"capitulos": [{"titulo": "Introdução", "descricao": "O vídeo apresenta o contexto.", "inicio": 0, "fim": 10}]},
                )
            self.assertEqual(dossier["capitulos"][0]["descricao"], "O vídeo apresenta o contexto.")

    def test_build_dossier_persists_ranked_moments(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video.mp4"
            source.write_bytes(b"video")
            with patch("core.editorial_mapper.obter_pastas_midia", return_value={"editorial_dossiers": directory}):
                dossier = build_dossier(
                    "video-1",
                    1,
                    str(source),
                    [{"inicio": 0, "fim": 10, "texto": "fala"}],
                    10,
                    "",
                    {"candidatos": [
                        {"inicio": 20, "fim": 30, "titulo": "B", "score_vaca_roxa": 70},
                        {"inicio": 0, "fim": 10, "titulo": "A", "score_vaca_roxa": 90},
                    ]},
                )
                loaded = load_dossier("video-1", 1)
            self.assertEqual([item["score_viralidade"] for item in dossier["melhores_momentos"]], [90, 70])
            self.assertEqual(loaded["video_id"], "video-1")

    def test_build_dossier_usa_candidatos_editoriais_da_ia(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video.mp4"
            source.write_bytes(b"video")
            with patch("core.editorial_mapper.obter_pastas_midia", return_value={"editorial_dossiers": directory}):
                dossier = build_dossier(
                    "video-1",
                    1,
                    str(source),
                    [{"inicio": 0, "fim": 10, "texto": "fala"}],
                    10,
                    "",
                    {
                        "candidatos": [],
                        "editorial_candidatos": [{"inicio": 0, "fim": 10, "titulo": "A", "score_vaca_roxa": 90}],
                    },
                )
            self.assertEqual(len(dossier["melhores_momentos"]), 1)

    def test_harvest_orders_by_score_and_ignores_overlap(self):
        dossier = {"melhores_momentos": [
            {"id": "low", "inicio": 20, "fim": 30, "score_viralidade": 70, "usado": True},
            {"id": "high", "inicio": 0, "fim": 10, "score_viralidade": 95, "usado": True},
            {"id": "blocked", "inicio": 40, "fim": 50, "score_viralidade": 100, "usado": True},
        ]}
        candidates = harvest_candidates(dossier, [{"inicio": 39, "fim": 51, "status": "concluido"}], limit=2)
        self.assertEqual([candidate["id"] for candidate in candidates], ["high", "low"])

    def test_colheita_nao_altera_dossie_nem_consulta_flag_usado(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video.mp4"
            source.write_bytes(b"video")
            segments = [{"indice": 0, "inicio": 0, "fim": 10, "texto": "fala"}]
            parameters = {"prompt_version": "test"}
            with patch("core.editorial_mapper.obter_pastas_midia", return_value={"editorial_dossiers": directory}):
                build_dossier("video-1", 1, str(source), segments, 10, "", {"candidatos": [{"inicio": 0, "fim": 10, "titulo": "A", "score_vaca_roxa": 90}]}, parameters)
                dossier_file = Path(directory) / "video-1_dossier.json"
                before = dossier_file.read_bytes()
                _, candidates, _, cache_hit = load_or_build_dossier(
                    "video-1", 1, str(source), segments, 10, "", [],
                    lambda _partial: self.fail("cache hit não deve chamar o Ollama"), parameters, limit=1,
                )
                self.assertTrue(cache_hit)
                self.assertEqual(len(candidates), 1)
                self.assertEqual(dossier_file.read_bytes(), before)

    def test_cache_invalida_media_alterada_ou_transcricao_ausente(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video.mp4"
            source.write_bytes(b"video-v1")
            segments = [{"indice": 0, "inicio": 0, "fim": 10, "texto": "fala"}]
            parameters = {"prompt_version": "test"}
            with patch("core.editorial_mapper.obter_pastas_midia", return_value={"editorial_dossiers": directory}):
                build_dossier("video-1", 1, str(source), segments, 10, "", {"candidatos": []}, parameters)
                source.write_bytes(b"video-v2")
                chamadas = []
                load_or_build_dossier(
                    "video-1", 1, str(source), segments, 10, "", [],
                    lambda _partial: chamadas.append(True) or {"candidatos": [{"inicio": 0, "fim": 10, "titulo": "A", "score_vaca_roxa": 90}]}, parameters,
                )
                self.assertEqual(chamadas, [True])
                chamadas.clear()
                load_or_build_dossier(
                    "video-1", 1, str(source), [], 10, "", [],
                    lambda _partial: chamadas.append(True) or {"candidatos": [{"inicio": 0, "fim": 10, "titulo": "A", "score_vaca_roxa": 90}]}, parameters,
                )
                self.assertEqual(chamadas, [True])

    def test_cache_rejeita_dossie_vazio_ou_com_falha(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video.mp4"
            source.write_bytes(b"video")
            segments = [{"indice": 0, "inicio": 0, "fim": 10, "texto": "fala"}]
            parameters = {"prompt_version": "test"}
            with patch("core.editorial_mapper.obter_pastas_midia", return_value={"editorial_dossiers": directory}):
                build_dossier(
                    "video-1", 1, str(source), segments, 10, "",
                    {"candidatos": [], "diagnostico": [{"status": "timeout_or_network"}]}, parameters,
                )
                chamadas = []
                _, candidates, _, cache_hit = load_or_build_dossier(
                    "video-1", 1, str(source), segments, 10, "", [],
                    lambda _partial: chamadas.append(True) or {"candidatos": [{"inicio": 0, "fim": 10, "titulo": "A", "score_vaca_roxa": 90}]},
                    parameters, limit=1,
                )
                self.assertEqual(chamadas, [True])
                self.assertFalse(cache_hit)
                self.assertEqual(len(candidates), 1)

    def test_dossie_vazio_mantem_estrutura_e_nao_lanca_excecao(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "video.mp4"
            source.write_bytes(b"video")
            segments = [{"indice": 0, "inicio": 0, "fim": 10, "texto": "fala"}]
            with patch("core.editorial_mapper.obter_pastas_midia", return_value={"editorial_dossiers": directory}):
                dossier, candidates, _, cache_hit = load_or_build_dossier(
                    "video-1", 1, str(source), segments, 10, "", [],
                    lambda _partial: {"candidatos": [], "editorial_candidatos": [], "diagnostico": [{"status": "timeout_or_network"}]},
                    {"prompt_version": "test"},
                )
                self.assertEqual(dossier["melhores_momentos"], [])
                self.assertEqual(dossier["resumo_global"], "fala")
                self.assertEqual(candidates, [])
                self.assertFalse(cache_hit)

    def test_semantic_heatmap_preserves_hooks_entities_and_signals(self):
        heatmap = build_semantic_heatmap(
            [{"inicio": 0, "fim": 10, "texto": "A descoberta"}],
            [{
                "inicio": 2,
                "fim": 8,
                "score_viralidade": 90,
                "gancho": "A descoberta inesperada",
                "entidades": ["Projeto X"],
            }],
            "[PICO DE ÁUDIO] 2-4\n[CORTE DE CÂMERA] 6-8",
        )
        interval = heatmap["intervalos"][0]
        self.assertEqual(interval["intensidade"], 74)
        self.assertEqual(interval["ganchos"], ["A descoberta inesperada"])
        self.assertEqual(interval["entidades"], ["Projeto X"])
        self.assertEqual(len(interval["sinais_multimodais"]), 2)


if __name__ == "__main__":
    unittest.main()