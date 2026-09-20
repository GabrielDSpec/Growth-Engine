import unittest
from uuid import uuid4
from threading import Event
from unittest.mock import patch

from core.content_profile import VIDEO_THEME_SCHEMA, _classificar_videos, _parse_classification_response, _rotulo_valido
from core.cutter import _montar_prompt, calcular_score_corte, calcular_score_observavel, gerar_cortes_com_retry, refinar_titulo_corte, validar_cortes
from core.profiles import validar_url_canal
from core.radar_sources import _rss_source_urls
from core.task_runner import TaskRunner
from core.publisher import _dedupe_repeated_text, _metadata_for_cut, _original_video_url, _restore_entities, planejar_melhores_slots
from core.notification_repository import select_notifications
from core.content_analysis_repository import select_analysis_status
from core.content_profile_repository import select_profile_videos
from core.opportunities_repository import insert_opportunity, select_opportunities, select_top15_analyzed_videos
from core.opportunities import _validar_sugestoes, listar_oportunidades, gerar_briefing
from core.job_repository import create_job, recover_running_jobs, select_job, update_job
from core.cuts_repository import create_cut, list_cuts, update_cut


class CoreContractsTests(unittest.TestCase):
    def test_publisher_removes_repeated_description_sentences(self):
        text = "Ela foi em 2005. Ela foi em 2005. O contexto explica a cena."
        self.assertEqual(_dedupe_repeated_text(text), "Ela foi em 2005. O contexto explica a cena.")

    def test_publisher_restores_entity_only_from_original_title(self):
        self.assertEqual(_restore_entities("MISI Piranga 2026", "Miss Piranga 2026"), "Miss Piranga 2026")
        self.assertEqual(_restore_entities("MISI desconhecida", "Evento Piranga"), "MISI desconhecida")

    def test_publisher_links_youtube_source_but_not_local_uuid(self):
        self.assertEqual(_original_video_url("dQw4w9WgXcQ"), "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(_original_video_url("local-video-uuid"), "")

    @patch("core.publisher.gerar_metadados_blindados", return_value={})
    def test_publisher_adds_original_link_to_description(self, _metadata):
        _, description, _ = _metadata_for_cut({
            "video_id": "dQw4w9WgXcQ",
            "video_titulo": "Evento confirmado",
            "titulo": "O evento surpreendeu",
            "gancho": "O evento surpreendeu.",
        })
        self.assertIn("Vídeo original: https://www.youtube.com/watch?v=dQw4w9WgXcQ", description)

    def test_scheduler_uses_three_slots_before_next_day(self):
        slots = planejar_melhores_slots(4, perfil_id=999999, cuts=[{}, {}, {}, {}])
        self.assertEqual(len(slots), 4)
        self.assertEqual(len({slot["date"] for slot in slots[:3]}), 1)
        self.assertNotEqual(slots[0]["date"], slots[3]["date"])
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
        self.assertIn("confira o título original contra a transcrição", prompt)

    def test_cutter_retries_three_times_then_requests_review(self):
        class EmptyResponse:
            status_code = 200

            def json(self):
                return {"response": '{"cortes": []}'}

        with patch("core.cutter.requests.post", return_value=EmptyResponse()) as request:
            result = gerar_cortes_com_retry("[0] 0.000-20.000: fala", 20, [{"indice": 0, "inicio": 0, "fim": 20, "texto": "fala"}])
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(len(result["diagnostico"]), 3)
        self.assertEqual(request.call_count, 3)

    def test_cutter_accepts_nine_distinct_valid_segments(self):
        segmentos = [{"indice": indice, "inicio": indice * 10, "fim": (indice + 1) * 10, "texto": f"Fala {indice} com conclusão."} for indice in range(9)]
        candidatos = [{
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

        with patch("core.cutter.requests.post", return_value=ValidResponse()):
            result = gerar_cortes_com_retry("transcricao", 90, segmentos)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["cortes"]), 9)

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
        self.assertEqual(set(result), {"total", "concluidas", "pendentes", "processando"})

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
        recover_running_jobs()
        self.assertEqual(select_job(job_id)["status"], "interrupted")

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
        cut_id = create_cut("job-cut-test", "video-cut-test", "source.mp4", {"inicio": 1, "fim": 3, "titulo": "Teste", "score_vaca_roxa": 80})
        update_cut(cut_id, status="falhou", error="timeout")
        row = list_cuts(job_id="job-cut-test")[0]
        self.assertEqual(row["status"], "falhou")
        self.assertEqual(row["erro"], "timeout")

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
