import unittest
from datetime import datetime
from uuid import uuid4
from threading import Event
from unittest.mock import patch

from core.content_profile import VIDEO_THEME_SCHEMA, _classificar_videos, _parse_classification_response, _rotulo_valido
from core.google_oauth import SCOPES_PUBLISH, SCOPES_YOUTUBE, SCOPES_YOUTUBE_FORCE_SSL
from core.cutter import _montar_prompt, _titulo_editorial_local, _titulo_generico, calcular_score_corte, calcular_score_observavel, gerar_cortes_com_retry, refinar_titulo_corte, validar_cortes
from core.profiles import validar_url_canal
from core.radar_sources import _rss_source_urls
from core.task_runner import TaskRunner
from core.publisher import _dedupe_repeated_text, _metadata_for_cut, _normalize_hashtags, _original_video_url, _restore_entities, _truncate_youtube_title, arquivo_publicacao_corte, planejar_melhores_slots
from core.web_server import _admin_clear_finished_jobs, _clear_transcription_cache, _fallback_editorial_description, _save_publication_description, _update_runtime_job, _validar_ids_video_relacionado
from core.notification_repository import select_notifications
from core.content_analysis_repository import select_analysis_status
from core.content_profile_repository import select_profile_videos
from core.opportunities_repository import insert_opportunity, select_opportunities, select_top15_analyzed_videos
from core.opportunities import _validar_sugestoes, listar_oportunidades, gerar_briefing
from core.job_repository import create_job, recover_running_jobs, select_job, update_job
from core.cuts_repository import create_cut, list_cut_caption_transcript, list_cuts, replace_cut_cycle_metadata, save_cut_caption_transcript, update_cut


class CoreContractsTests(unittest.TestCase):
    @patch("core.web_server.get_connection")
    def test_admin_clear_finished_jobs_preserves_active_jobs(self, connection_factory):
        connection = connection_factory.return_value
        connection.execute.return_value.rowcount = 3
        self.assertEqual(_admin_clear_finished_jobs(915361), {"removidos": 3})
        query, params = connection.execute.call_args.args
        self.assertIn("DELETE FROM tarefas_jobs", query)
        self.assertIn("completed", params)
        connection.commit.assert_called_once()

    @patch("core.web_server._youtube_client")
    @patch("core.web_server.get_connection")
    @patch("core.web_server.arquivo_publicacao_corte", return_value="captioned.mp4")
    def test_published_short_idempotency_uses_captioned_path(self, _publication_path, connection_factory, youtube_client):
        connection = connection_factory.return_value
        connection.execute.return_value.fetchall.return_value = [{"video_id": "captioned-id", "status": "publicado_externo", "titulo": "Título", "descricao": "Descrição", "arquivo_origem": "captioned.mp4"}]
        youtube_client.return_value.videos.return_value.list.return_value.execute.return_value = {"items": [{"id": "captioned-id"}]}
        from core.web_server import _published_short_for_cut

        self.assertEqual(_published_short_for_cut({"caminho_saida": "original.mp4", "legenda_status": "concluido"}, 915361)["video_id"], "captioned-id")
        self.assertIn("captioned.mp4", connection.execute.call_args.args[1])

    def test_captioned_cut_publication_uses_caption_file(self):
        with patch("core.publisher.os.path.isfile", side_effect=lambda path: path in {"original.mp4", "captioned.mp4"}):
            self.assertEqual(arquivo_publicacao_corte({"caminho_saida": "original.mp4", "legenda_status": "concluido", "legenda_caminho": "captioned.mp4"}), "captioned.mp4")
            with self.assertRaisesRegex(RuntimeError, "MP4 legendado"):
                arquivo_publicacao_corte({"caminho_saida": "original.mp4", "legenda_status": "concluido", "legenda_caminho": "missing.mp4"})

    def test_clear_transcription_cache_preserves_video_and_cuts(self):
        class Result:
            def fetchone(self):
                return {"file_hash": "old-hash", "arquivo_origem": "C:/media/source.mp4"}

        class Connection:
            def __init__(self):
                self.statements = []
                self.committed = False

            def execute(self, sql, params):
                self.statements.append((sql, params))
                return Result()

            def commit(self):
                self.committed = True

            def close(self):
                pass

        connection = Connection()
        with patch("core.web_server.get_connection", return_value=connection), patch("core.web_server.os.path.isfile", return_value=False), patch("core.web_server._remove_video_artifacts", return_value=2) as remove_artifacts, patch("core.web_server.dossier_path") as dossier_path:
            dossier_path.return_value.is_file.return_value = False
            removed = _clear_transcription_cache("video-1", 7)

        update_sql = connection.statements[1][0]
        self.assertIn("transcricao=NULL", update_sql)
        self.assertIn("transcricao_segmentos=NULL", update_sql)
        self.assertIn("videos_historico", update_sql)
        self.assertTrue(connection.committed)
        remove_artifacts.assert_called_once()
        self.assertEqual(removed, 2)

    def test_related_video_rejects_self_reference(self):
        with self.assertRaisesRegex(ValueError, "não pode ser relacionado"):
            _validar_ids_video_relacionado("MscbSvK1Cb4", "MscbSvK1Cb4")

    def test_youtube_oauth_includes_full_write_scopes(self):
        self.assertEqual(SCOPES_YOUTUBE, "https://www.googleapis.com/auth/youtube")
        self.assertEqual(SCOPES_YOUTUBE_FORCE_SSL, "https://www.googleapis.com/auth/youtube.force-ssl")
        self.assertEqual(SCOPES_PUBLISH, "https://www.googleapis.com/auth/youtube.upload")

    def test_publisher_removes_repeated_description_sentences(self):
        text = "Ela foi em 2005. Ela foi em 2005. O contexto explica a cena."
        self.assertEqual(_dedupe_repeated_text(text), "Ela foi em 2005. O contexto explica a cena.")

    def test_publisher_restores_entity_only_from_original_title(self):
        self.assertEqual(_restore_entities("MISI Piranga 2026", "Miss Piranga 2026"), "Miss Piranga 2026")
        self.assertEqual(_restore_entities("MISI desconhecida", "Evento Piranga"), "MISI desconhecida")

    @patch("core.publisher.gerar_metadados_blindados")
    def test_publisher_preserva_metadados_persistidos_sem_chamar_ia(self, metadata):
        long_title = "Palavra editorial importante " * 6
        title, description, _ = _metadata_for_cut({
            "id": 42,
            "perfil_id": 1,
            "titulo": long_title,
            "descricao_publicacao": "Descrição editorial factual persistida no dossiê.",
        })
        metadata.assert_not_called()
        self.assertLessEqual(len(title), 100)
        self.assertTrue(title.endswith("..."))
        self.assertEqual(description, "Descrição editorial factual persistida no dossiê.")

    @patch("core.publisher.get_connection")
    def test_publisher_persiste_metadado_final_no_corte(self, get_connection):
        connection = get_connection.return_value
        from core.publisher import _persist_final_metadata

        _persist_final_metadata({"id": 42, "perfil_id": 7}, "Título final", "Descrição final")

        connection.execute.assert_called_once()
        self.assertEqual(connection.execute.call_args.args[1], ("Título final", "Descrição final", 42, 7))
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_truncamento_de_titulo_preserva_palavra_e_limite_da_api(self):
        original = "Uma manchete editorial muito longa com várias palavras importantes para o corte"
        title = _truncate_youtube_title(original, limit=40)
        self.assertLessEqual(len(title), 100)
        self.assertTrue(title.endswith("..."))
        self.assertEqual(original[len(title[:-3])], " ")

    def test_cut_title_removes_markdown_heading_markers(self):
        self.assertEqual(refinar_titulo_corte("### A gente"), "A gente")

    def test_local_title_fallback_uses_evidence_only(self):
        self.assertEqual(_titulo_editorial_local("A gente fala sobre doação de órgãos e transplantes"), "Fala sobre doação órgãos transplantes")
        self.assertNotIn("Momento:", _titulo_editorial_local("A gente fala sobre doação de órgãos e transplantes"))

    def test_generic_title_is_detected(self):
        self.assertTrue(_titulo_generico("A gente"))

    def test_publisher_links_youtube_source_but_not_local_uuid(self):
        self.assertEqual(_original_video_url("dQw4w9WgXcQ"), "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(_original_video_url("local-video-uuid"), "")

    @patch("core.publisher.gerar_metadados_blindados", return_value={})
    def test_publisher_keeps_description_empty_without_editorial_summary(self, _metadata):
        _, description, _ = _metadata_for_cut({
            "video_id": "dQw4w9WgXcQ",
            "video_titulo": "Evento confirmado",
            "titulo": "O evento surpreendeu",
            "gancho": "O evento surpreendeu.",
        })
        self.assertEqual(description, "")

    @patch("core.web_server.update_cut_metadata")
    @patch("core.web_server._transcript_for_cut", return_value="A primeira fala apresenta uma ideia importante sobre o canal e explica o contexto do corte.")
    @patch("core.web_server._metadata_for_cut", return_value=("Corte", "", []))
    def test_cut_uses_rich_fallback_when_ai_summary_is_missing(self, _metadata, _transcript, update_metadata):
        description = _save_publication_description(1298, {"titulo": "Uma descoberta importante"}, 915361)
        self.assertIn("Uma descoberta importante", description)
        self.assertIn("Trecho entre 00:00 e 00:00", description)
        self.assertNotIn("E tudo ia bem", description)
        update_metadata.assert_called_once_with(1298, "Uma descoberta importante", description, perfil_id=915361)

    @patch("core.web_server._transcript_for_cut", return_value="")
    def test_rich_fallback_uses_cut_evidence_without_transcript(self, _transcript):
        description = _fallback_editorial_description({"titulo": "Corte local", "gancho": "A ideia começa aqui", "inicio": 12, "fim": 34})
        self.assertIn("Trecho entre 00:12 e 00:34", description)
        self.assertNotIn("E tudo ia bem", description)

    @patch("core.publisher.gerar_metadados_blindados", return_value={"descricao": "Uma descrição editorial fiel.", "hashtags": ["#viagem", "#fyp", "#turismo"]})
    def test_publisher_appends_relevant_hashtags_to_description(self, _metadata):
        _, description, _ = _metadata_for_cut({"video_id": "local-video", "video_titulo": "Viagem de trem", "titulo": "A rota surpreendente"})
        self.assertIn("#viagem", description)
        self.assertIn("#turismo", description)
        self.assertNotIn("#fyp", description)

    def test_hashtags_are_not_generic(self):
        self.assertEqual(_normalize_hashtags(["#viral", "#fyp", "#turismo"], "Uma rota de turismo."), ["#turismo"])

    def test_scheduler_fills_available_gaming_slots_before_next_day(self):
        cuts = [{"categoria": "Gaming", "titulo": "Gameplay e história do jogo"} for _ in range(4)]
        slots = planejar_melhores_slots(4, perfil_id=999999, cuts=cuts)
        self.assertEqual(len(slots), 4)
        self.assertTrue(all(slot["time"] in {"18:00", "20:00", "21:00", "22:00"} for slot in slots))
        now = datetime.now()
        available_today = sum(datetime.strptime(time, "%H:%M").time() > now.time() for time in ("18:00", "20:00", "21:00", "22:00"))
        expected_today = min(4, available_today)
        first_date_count = sum(slot["date"] == slots[0]["date"] for slot in slots)
        self.assertEqual(first_date_count, expected_today or 4)

    def test_scheduler_starts_from_requested_datetime(self):
        start_at = "2099-06-18T23:30"
        slots = planejar_melhores_slots(3, perfil_id=999999, start_at=start_at)
        self.assertEqual(len(slots), 3)
        self.assertTrue(all(f"{slot['date']}T{slot['time']}" > start_at for slot in slots))

    def test_youtube_url_validation_accepts_only_supported_hosts(self):
        self.assertTrue(validar_url_canal("https://www.youtube.com/@canal"))
        self.assertTrue(validar_url_canal("https://youtu.be/video"))
        self.assertFalse(validar_url_canal("https://youtube.com.evil.example/canal"))
        self.assertFalse(validar_url_canal("javascript:alert(1)"))

    def test_video_theme_schema_matches_consumed_keys(self):
        properties = set(VIDEO_THEME_SCHEMA["properties"])
        required = set(VIDEO_THEME_SCHEMA["required"])
        self.assertEqual(properties, {"tema_abstrato", "pilar", "formato"})
        self.assertEqual(required, properties)

    def test_semantic_labels_reject_titles_and_numbers(self):
        self.assertTrue(_rotulo_valido("Viagem e turismo"))
        self.assertFalse(_rotulo_valido("Video 2025"))
        self.assertFalse(_rotulo_valido("uma"))
        self.assertFalse(_rotulo_valido("frase longa demais com muitas palavras que nao deve ser categoria"))

    def test_classification_parser_requires_exact_json_contract(self):
        valid = _parse_classification_response('{"tema_abstrato":"Viagem e turismo","pilar":"Experiência de viagem","formato":"vlog"}')
        self.assertEqual(valid["formato"], "vlog")
        with self.assertRaises(ValueError):
            _parse_classification_response("```json {\\\"tema_abstrato\\\":\\\"Viagem e turismo\\\"}```")
        with self.assertRaises(ValueError):
            _parse_classification_response('{"tema_abstrato":"Viagem e turismo","pilar":"Experiência de viagem","formato":"vlog","extra":"nao"}')

    def test_invalid_classification_retries_and_accepts_later_valid_response(self):
        data = [{"video_id": "video-retry", "titulo": "Teste", "views": 10, "likes": 1, "analise": {}}]
        responses = ["texto inválido", '{"tema_abstrato":"Viagem e turismo","pilar":"Experiência de viagem","formato":"vlog"}']
        with patch("core.content_profile._consultar_qwen", side_effect=responses) as consult:
            classified, failures = _classificar_videos(data)
        self.assertEqual(consult.call_count, 2)
        self.assertEqual(len(classified), 1)
        self.assertEqual(failures, [])

    def test_exhausted_classification_retry_never_returns_invalid_item(self):
        data = [{"video_id": "video-fail", "titulo": "Teste", "views": 10, "likes": 1, "analise": {}}]
        with patch("core.content_profile._consultar_qwen", return_value="nao json") as consult:
            with self.assertRaises(ValueError):
                _classificar_videos(data)
        self.assertEqual(consult.call_count, 3)

    def test_cut_score_uses_the_declared_weighted_dimensions(self):
        score = calcular_score_corte({
            "distintividade": 100,
            "gancho": 100,
            "clareza_promessa": 100,
            "autossuficiencia": 100,
            "compartilhabilidade": 100,
            "evidencia": 100,
        })
        self.assertEqual(score, 100)

    def test_observable_cut_score_is_nonzero_without_ai_subscores(self):
        score = calcular_score_observavel(
            "Como descobri o erro e o resultado surpreendeu a equipe",
            [{"texto": "Como descobri o erro e o resultado surpreendeu"}],
        )
        self.assertGreater(score["score"], 0)
        self.assertEqual(set(score["pontuacoes"]), {"distintividade", "gancho", "clareza_promessa", "autossuficiencia", "compartilhabilidade", "evidencia"})

    def test_generic_cut_title_is_replaced_by_content_title(self):
        title = refinar_titulo_corte("Trecho para revisar 01", "As juradas avaliaram a competição")
        self.assertEqual(title, "As juradas avaliaram a competição")

    def test_cut_prompt_checks_original_video_title_against_transcription(self):
        prompt = _montar_prompt("[0] 0-20: A frase confirmada.", 20, [], 1, [], [], titulo_original="Evento em Piranga")
        self.assertIn("Título original do vídeo: Evento em Piranga", prompt)
        self.assertIn("confira o título original contra o MATERIAL BASE", prompt)

    def test_cutter_rejects_empty_editorial_response_without_local_fallback(self):
        class EmptyResponse:
            status_code = 200

            def json(self):
                return {"response": '{"cortes": []}'}

        with patch("core.cutter.requests.post", return_value=EmptyResponse()) as request, patch("core.cutter.OLLAMA_CUTS_ENABLED", True):
            result = gerar_cortes_com_retry("[0] 0.000-20.000: fala", 20, [{"indice": 0, "inicio": 0, "fim": 20, "texto": "fala"}])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["cortes"], [])
        self.assertEqual(len(result["diagnostico"]), 1)
        self.assertEqual(
            result["diagnostico"][0]["erro"],
            'empty_editorial_response; sem candidatos válidos. RAW: {"cortes": []}',
        )
        self.assertEqual(request.call_count, 2)

    def test_cutter_accepts_nine_distinct_valid_segments(self):
        segmentos = [{"indice": indice, "inicio": indice * 10, "fim": (indice + 1) * 10, "texto": f"Fala {indice} com conclusão."} for indice in range(9)]
        candidatos = [{
            "indice": indice,
            "titulo": f"Descoberta numero {indice}",
            "segmento_inicio": indice,
            "segmento_fim": indice,
            "gancho": f"fala {indice}",
            "promessa": "a ideia principal",
            "virada": "o contraste aparece",
            "conclusao": "a ideia se fecha",
            "autossuficiente": True,
            "promocional": False,
            "pontuacoes": {chave: 100 for chave in ("distintividade", "gancho", "clareza_promessa", "autossuficiencia", "compartilhabilidade", "evidencia")},
        } for indice in range(9)]

        class ValidResponse:
            status_code = 200

            def json(self):
                import json
                return {"response": json.dumps({"cortes": candidatos})}

        with patch("core.cutter._gerar_resposta_ollama", return_value={"status_code": 200, "response": ValidResponse().json()["response"]}):
            result = gerar_cortes_com_retry("transcricao", 90, segmentos)
        self.assertEqual(result["status"], "completed")
        self.assertGreater(len(result["cortes"]), 0)
        self.assertEqual(len({(item["inicio"], item["fim"]) for item in result["cortes"]}), len(result["cortes"]))

    def test_new_cut_cycle_requires_editorial_provider(self):
        with patch("core.cutter.OLLAMA_CUTS_ENABLED", False):
            result = gerar_cortes_com_retry(
                "transcricao",
                60,
                [],
                cortes_existentes=[{"inicio_segundos": 0, "fim_segundos": 20}],
            )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["candidatos"], [])
        self.assertEqual(result["diagnostico"][0]["status"], "provider_disabled")

    def test_cutter_preserves_structural_candidate_below_recommended_score(self):
        candidate = {
            "titulo": "Descoberta editorial válida",
            "segmento_inicio": 0,
            "segmento_fim": 0,
            "gancho": "fala importante",
            "promessa": "a ideia principal",
            "virada": "o contraste aparece",
            "conclusao": "a ideia se fecha",
            "autossuficiente": True,
            "promocional": False,
            "pontuacoes": {"distintividade": 60, "gancho": 60, "clareza_promessa": 60, "autossuficiencia": 60, "compartilhabilidade": 60, "evidencia": 60},
        }
        segments = [{"indice": 0, "inicio": 0, "fim": 20, "texto": "Fala importante com a ideia principal."}]
        self.assertEqual(len(validar_cortes([candidate], 20, segments)), 0)
        preserved = validar_cortes([candidate], 20, segments, score_minimo=0)
        self.assertEqual(len(preserved), 1)
        self.assertEqual(preserved[0]["score_vaca_roxa"], 60)

    def test_cutter_uses_ai_suggested_title_and_description(self):
        candidate = {
            "titulo_sugerido": "A descoberta que mudou tudo",
            "descricao_sugerida": "O trecho explica a descoberta e o contraste observado.",
            "segmento_inicio": 0,
            "segmento_fim": 0,
            "gancho": "A descoberta importante",
            "promessa": "entender a ideia principal",
            "virada": "o contraste aparece",
            "conclusao": "a ideia se fecha",
            "autossuficiente": True,
            "promocional": False,
            "pontuacoes": {chave: 90 for chave in ("distintividade", "gancho", "clareza_promessa", "autossuficiencia", "compartilhabilidade", "evidencia")},
        }
        resultado = validar_cortes([candidate], 20, [{"indice": 0, "inicio": 0, "fim": 20, "texto": "A descoberta importante explica a ideia principal e o contraste aparece no final."}], score_minimo=0)
        self.assertEqual(resultado[0]["titulo"], "A descoberta que mudou tudo")
        self.assertEqual(resultado[0]["descricao_publicacao"], candidate["descricao_sugerida"])

    def test_cutter_accepts_evidence_with_small_wording_variation(self):
        candidate = {
            "titulo": "Descoberta editorial válida",
            "segmento_inicio": 0,
            "segmento_fim": 0,
            "gancho": "descoberta importante muda tudo",
            "promessa": "a ideia principal",
            "virada": "o contraste aparece",
            "conclusao": "a ideia se fecha",
            "autossuficiente": True,
            "promocional": False,
            "pontuacoes": {chave: 100 for chave in ("distintividade", "gancho", "clareza_promessa", "autossuficiencia", "compartilhabilidade", "evidencia")},
        }
        segments = [{"indice": 0, "inicio": 0, "fim": 20, "texto": "Essa descoberta realmente importante mudou tudo para nós."}]
        self.assertEqual(len(validar_cortes([candidate], 20, segments)), 1)

    def test_cutter_rejects_a_segment_that_ends_inside_a_sentence(self):
        candidate = {
            "titulo": "Descoberta editorial válida",
            "segmento_inicio": 0,
            "segmento_fim": 0,
            "gancho": "A descoberta",
            "promessa": "a ideia principal",
            "virada": "o contraste aparece",
            "conclusao": "a ideia se fecha",
            "autossuficiente": True,
            "promocional": False,
            "pontuacoes": {chave: 100 for chave in ("distintividade", "gancho", "clareza_promessa", "autossuficiencia", "compartilhabilidade", "evidencia")},
        }
        segments = [{"indice": 0, "inicio": 0, "fim": 20, "texto": "A descoberta mudou tudo para"}]
        self.assertEqual(validar_cortes([candidate], 20, segments, score_minimo=0), [])

    def test_cutter_expands_a_split_sentence_to_the_next_segment(self):
        candidate = {
            "titulo": "Descoberta editorial válida",
            "segmento_inicio": 0,
            "segmento_fim": 0,
            "gancho": "A descoberta",
            "promessa": "a ideia principal",
            "virada": "o contraste aparece",
            "conclusao": "a ideia se fecha",
            "autossuficiente": True,
            "promocional": False,
            "pontuacoes": {chave: 100 for chave in ("distintividade", "gancho", "clareza_promessa", "autossuficiencia", "compartilhabilidade", "evidencia")},
        }
        segments = [
            {"indice": 0, "inicio": 0, "fim": 10, "texto": "A descoberta mudou"},
            {"indice": 1, "inicio": 10, "fim": 20, "texto": "tudo para nós."},
        ]
        result = validar_cortes([candidate], 20, segments, score_minimo=0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["segmento_fim"], 1)
        self.assertEqual(result[0]["fim"], 20)

    def test_cutter_builds_hook_context_highlight_montage(self):
        candidate = {
            "titulo": "A descoberta muda o resultado",
            "segmento_inicio": 0,
            "segmento_fim": 2,
            "gancho": "A descoberta aconteceu.",
            "gancho_inicio": "A descoberta aconteceu.",
            "destaque": "A descoberta aconteceu.",
            "montagem": "gancho_contexto_retorno",
            "promessa": "o contexto explica a descoberta",
            "virada": "A descoberta aconteceu.",
            "conclusao": "O contexto fecha a ideia.",
            "autossuficiente": True,
            "promocional": False,
            "pontuacoes": {chave: 100 for chave in ("distintividade", "gancho", "clareza_promessa", "autossuficiencia", "compartilhabilidade", "evidencia")},
        }
        segments = [
            {"indice": 0, "inicio": 0, "fim": 10, "texto": "O contexto explica tudo."},
            {"indice": 1, "inicio": 10, "fim": 20, "texto": "A descoberta aconteceu."},
            {"indice": 2, "inicio": 20, "fim": 30, "texto": "O contexto fecha a ideia."},
        ]
        result = validar_cortes([candidate], 30, segments, score_minimo=0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["montagem_intervalos"], [
            {"inicio": 10, "fim": 20},
            {"inicio": 0, "fim": 10},
            {"inicio": 10, "fim": 20},
        ])

    def test_radar_has_search_and_primary_rss_sources(self):
        sources = _rss_source_urls("eventos São Paulo", include_primary=True, topic="Viagem ao litoral")
        providers = {provider for provider, _ in sources}
        self.assertTrue({"Google News", "Bing News", "Yahoo News", "Reddit"}.issubset(providers))
        self.assertTrue({"G1", "UOL"}.issubset(providers))
        self.assertTrue({"Flipboard", "TecMundo"}.issubset(providers))
        local_sources = {provider for provider, _ in _rss_source_urls("eventos São Paulo", include_primary=True)}
        self.assertNotIn("TecMundo", local_sources)

    def test_task_runner_rejects_duplicate_named_tasks(self):
        runner = TaskRunner(max_workers=1)
        started = Event()
        release = Event()

        def task():
            started.set()
            release.wait(timeout=2)

        self.assertTrue(runner.submit("sample", task))
        self.assertTrue(started.wait(timeout=2))
        self.assertFalse(runner.submit("sample", task))
        release.set()
        runner.shutdown()

    def test_task_runner_lock_key_is_shared_across_operations(self):
        runner = TaskRunner(max_workers=1)
        started = Event()
        release = Event()

        def task():
            started.set()
            release.wait(timeout=2)

        self.assertTrue(runner.submit("transcription", task, key="video:abc"))
        self.assertTrue(started.wait(timeout=2))
        self.assertFalse(runner.submit("cut", task, key="video:abc"))
        release.set()
        runner.shutdown()

    def test_notification_repository_returns_domain_shape(self):
        result = select_notifications(limit=1)
        self.assertIn("notificacoes", result)
        self.assertIn("nao_lidas", result)

    def test_content_analysis_repository_returns_progress_shape(self):
        result = select_analysis_status()
        self.assertEqual(set(result), {"total", "concluidas", "pendentes", "processando", "processing_video_ids"})

    def test_content_profile_repository_returns_video_list(self):
        result = select_profile_videos(limite=1)
        self.assertIsInstance(result, list)

    def test_opportunities_repository_returns_lists(self):
        self.assertIsInstance(select_opportunities(limit=1), list)
        self.assertIsInstance(select_top15_analyzed_videos(), list)

    def test_opportunity_evidence_must_reference_top15_video_ids(self):
        source_rows = [{"video_id": "top-1"}, {"video_id": "top-2"}]
        suggestion = {
            "titulo": "Pauta ancorada", "tema": "Viagem e turismo", "contexto": "Contexto real",
            "relevancia": 8,
            "evidencia": {"video_ids": ["top-1"], "trechos": ["Trecho literal"], "observacoes": ["Observação"], "hipoteses": [], "views": 1000, "likes": 20},
        }
        self.assertEqual(_validar_sugestoes({"sugestoes": [suggestion] * 3}, source_rows)[0]["evidencia"]["video_ids"], ["top-1"])
        suggestion["evidencia"]["video_ids"] = ["radar-item"]
        with self.assertRaises(ValueError):
            _validar_sugestoes({"sugestoes": [suggestion] * 3}, source_rows)

    def test_opportunity_listing_and_briefing_expose_saved_evidence(self):
        items = [item for item in listar_oportunidades() if item.get("origem_tipo") == "autopsia_top15"]
        self.assertTrue(items)
        self.assertIn("evidence", items[0])
        briefing = gerar_briefing(items[0]["id"])
        self.assertIn("evidencia", briefing)
        self.assertTrue(briefing["evidencia"].get("video_ids"))

    def test_job_repository_persists_lifecycle(self):
        job_id = f"test-job-contract-{uuid4().hex}"
        create_job(job_id, "transcription", "video-contract")
        update_job(job_id, status="running", progress=25, message="teste")
        job = select_job(job_id)
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["progresso"], 25)
        update_job(job_id, status="completed", progress=100, message="finalizado")
        self.assertGreaterEqual(select_job(job_id)["duracao_segundos"], 0)
        recover_running_jobs()
        self.assertEqual(select_job(job_id)["status"], "completed")

    @patch("core.web_server.update_job")
    def test_runtime_job_maps_step_progress_to_persistent_counters(self, update_job_mock):
        store = {}
        _update_runtime_job(
            store,
            "step-job",
            1,
            progress=42,
            message="Transcrevendo áudio",
            stage="transcribing",
            step_name="transcription",
            segments_processed=7,
            segments_total=20,
            processed_audio_seconds=31.5,
        )

        kwargs = update_job_mock.call_args.kwargs
        self.assertEqual(kwargs["current_item"], 7)
        self.assertEqual(kwargs["total_items"], 20)
        self.assertEqual(kwargs["checkpoint"]["step_name"], "transcription")
        self.assertEqual(kwargs["checkpoint"]["processed_audio_seconds"], 31.5)

    def test_job_updates_are_isolated_by_profile(self):
        profile_a = 11000 + uuid4().int % 1000000
        profile_b = profile_a + 1
        job_id = f"test-job-isolation-{uuid4().hex}"
        from core.database import get_connection, init_db
        init_db()
        conn = get_connection()
        conn.execute("INSERT OR IGNORE INTO perfis (id, nome, tipo) VALUES (?, ?, 'test')", (profile_a, "Job A"))
        conn.execute("INSERT OR IGNORE INTO perfis (id, nome, tipo) VALUES (?, ?, 'test')", (profile_b, "Job B"))
        conn.commit()
        conn.close()
        try:
            create_job(job_id, "transcription", "video-a", perfil_id=profile_a)
            update_job(job_id, status="running", progress=99, perfil_id=profile_b)
            self.assertEqual(select_job(job_id, profile_a)["status"], "queued")
            update_job(job_id, status="running", progress=25, perfil_id=profile_a)
            self.assertEqual(select_job(job_id, profile_a)["progresso"], 25)
            self.assertIsNone(select_job(job_id, profile_b))
        finally:
            conn = get_connection()
            conn.execute("DELETE FROM tarefas_jobs WHERE job_id=? AND perfil_id IN (?, ?)", (job_id, profile_a, profile_b))
            conn.execute("DELETE FROM perfis WHERE id IN (?, ?)", (profile_a, profile_b))
            conn.commit()
            conn.close()

    def test_cuts_repository_persists_individual_state(self):
        cut_id = create_cut("job-cut-test", "video-cut-test", "source.mp4", {"inicio": 1, "fim": 3, "titulo": "Teste", "descricao_publicacao": "Descrição editorial", "score_vaca_roxa": 80})
        update_cut(cut_id, status="falhou", error="timeout")
        row = list_cuts(job_id="job-cut-test")[0]
        self.assertEqual(row["status"], "falhou")
        self.assertEqual(row["erro"], "timeout")
        self.assertEqual(row["descricao_publicacao"], "Descrição editorial")

    def test_cycle_metadata_replacement_is_word_bounded_and_job_scoped(self):
        job_id = f"job-replace-{uuid4().hex}"
        other_job_id = f"job-other-{uuid4().hex}"
        first = create_cut(job_id, "video-replace", "source.mp4", {"inicio": 1, "fim": 3, "titulo": "Varenga no título", "descricao_publicacao": "A família Varenga chegou."})
        second = create_cut(job_id, "video-replace", "source.mp4", {"inicio": 4, "fim": 6, "titulo": "Varengas não deve mudar", "descricao_publicacao": "Varenga e varenga."})
        untouched = create_cut(other_job_id, "video-replace", "source.mp4", {"inicio": 7, "fim": 9, "titulo": "Varenga fora do ciclo", "descricao_publicacao": "Varenga."})
        try:
            result = replace_cut_cycle_metadata(job_id, "Varenga", "Alvarenga")
            rows = {row["id"]: row for row in list_cuts(perfil_id=1) if row["id"] in {first, second, untouched}}
            self.assertEqual(result["cuts"], 2)
            self.assertEqual(rows[first]["titulo"], "Alvarenga no título")
            self.assertEqual(rows[first]["descricao_publicacao"], "A família Alvarenga chegou.")
            self.assertEqual(rows[second]["titulo"], "Varengas não deve mudar")
            self.assertEqual(rows[second]["descricao_publicacao"], "Alvarenga e Alvarenga.")
            self.assertEqual(rows[untouched]["titulo"], "Varenga fora do ciclo")
        finally:
            conn = __import__("core.database", fromlist=["get_connection"]).get_connection()
            conn.execute("DELETE FROM cortes_gerados WHERE id IN (?, ?, ?)", (first, second, untouched))
            conn.commit()
            conn.close()

    def test_cut_caption_transcript_is_persisted_by_cut(self):
        job_id = f"job-caption-transcript-{uuid4().hex}"
        cut_id = create_cut(job_id, "video-caption", "source.mp4", {"inicio": 1, "fim": 3, "titulo": "Corte"})
        try:
            saved = save_cut_caption_transcript(cut_id, [{"indice": 2, "inicio": 1.2, "fim": 2.4, "texto": "Texto corrigido"}])
            self.assertEqual(saved, 1)
            self.assertEqual(list_cut_caption_transcript(cut_id)[0]["texto"], "Texto corrigido")
            self.assertEqual(list_cut_caption_transcript(cut_id)[0]["inicio"], 1.2)
        finally:
            conn = __import__("core.database", fromlist=["get_connection"]).get_connection()
            conn.execute("DELETE FROM cortes_transcricao_editada WHERE cut_id=?", (cut_id,))
            conn.execute("DELETE FROM cortes_gerados WHERE id=?", (cut_id,))
            conn.commit()
            conn.close()

    def test_repositories_isolate_opportunities_and_cuts_by_profile(self):
        profile_a = 10000 + uuid4().int % 1000000
        profile_b = profile_a + 1
        from core.database import get_connection, init_db
        init_db()
        conn = get_connection()
        conn.execute("INSERT OR IGNORE INTO perfis (id, nome, tipo) VALUES (?, ?, 'test')", (profile_a, "Teste A"))
        conn.execute("INSERT OR IGNORE INTO perfis (id, nome, tipo) VALUES (?, ?, 'test')", (profile_b, "Teste B"))
        conn.commit()
        conn.close()
        try:
            opportunity_a = insert_opportunity({"perfil_id": profile_a, "titulo": "Pauta A", "atualidade": 1, "relevancia_canal": 1, "potencial_local": 1, "facilidade_gravacao": 1, "potencial_short": 1, "evidencia": 1})
            opportunity_b = insert_opportunity({"perfil_id": profile_b, "titulo": "Pauta B", "atualidade": 1, "relevancia_canal": 1, "potencial_local": 1, "facilidade_gravacao": 1, "potencial_short": 1, "evidencia": 1})
            self.assertIn(opportunity_a, [item["id"] for item in select_opportunities(perfil_id=profile_a)])
            self.assertNotIn(opportunity_b, [item["id"] for item in select_opportunities(perfil_id=profile_a)])
            cut_a = create_cut(f"job-a-{profile_a}", f"video-a-{profile_a}", "a.mp4", {"inicio": 1, "fim": 2, "titulo": "Corte A"}, perfil_id=profile_a)
            create_cut(f"job-b-{profile_b}", f"video-b-{profile_b}", "b.mp4", {"inicio": 1, "fim": 2, "titulo": "Corte B"}, perfil_id=profile_b)
            self.assertEqual([item["id"] for item in list_cuts(perfil_id=profile_a)], [cut_a])
        finally:
            conn = get_connection()
            for table in ("cortes_gerados", "oportunidades_conteudo", "tarefas_jobs"):
                conn.execute(f"DELETE FROM {table} WHERE perfil_id IN (?, ?)", (profile_a, profile_b))
            conn.execute("DELETE FROM perfis WHERE id IN (?, ?)", (profile_a, profile_b))
            conn.commit()
            conn.close()

    def test_task_runner_profile_keys_can_run_independently(self):
        runner = TaskRunner(max_workers=2)
        started = Event()
        release = Event()

        def task():
            started.set()
            release.wait(timeout=2)

        self.assertTrue(runner.submit("analysis", task, key="perfil:1:analysis"))
        self.assertTrue(runner.submit("analysis", task, key="perfil:2:analysis"))
        self.assertTrue(started.wait(timeout=2))
        release.set()
        runner.shutdown()


if __name__ == "__main__":
    unittest.main()
