import unittest
from unittest.mock import patch

import requests

from core.cutter import EditorialCandidates, GenerationCancelled, _calcular_timeout_ollama, _candidato_somente_ruido_audio, _candidatos_fallback, _candidatos_para_revisao, _cortes_repetidos, _deduplicar_cortes, _extrair_candidatos, _gerar_indice_editorial, _gerar_resposta_ollama, _gerar_resposta_ollama_http, _gerar_dossie_editorial_unico, _normalizar_candidato_bloco, _segmentar_editorial, _selecionar_candidatos_locais_com_insistencia, _titulo_editorial_local, gerar_cortes_com_retry
from core.media_tools import nome_seguro_arquivo


class OllamaWatchdogTests(unittest.TestCase):
    def test_editorial_preserva_steps_com_musica_ou_gritos(self):
        segmentos = [
            {"indice": indice, "inicio": indice * 180 + 5, "fim": indice * 180 + 15, "texto": "[MÚSICA TOCANDO]" if indice % 2 == 0 else "[GRITOS DE GOL]"}
            for indice in range(8)
        ]
        candidato = EditorialCandidates([{"titulo": "Momento do step", "inicio_segundos": 5, "fim_segundos": 15}])
        with patch("core.cutter._gerar_resposta_ollama", return_value={"status_code": 200, "response": "{}"}), patch("core.cutter._extrair_candidatos", return_value=candidato) as extrair:
            resultado = _gerar_dossie_editorial_unico("transcricao", 1474, segmentos, 30, 60)
        self.assertEqual(resultado.steps_total, 8)
        self.assertEqual(resultado.steps_completed, 8)
        self.assertEqual(extrair.call_count, 8)

    def test_editorial_resume_skips_completed_steps(self):
        segments = [
            {"indice": index, "inicio": index * 30, "fim": (index + 1) * 30, "texto": f"Fala relevante {index}."}
            for index in range(12)
        ]
        response = {"status_code": 200, "response": "{}"}
        candidate = {"titulo": "Momento relevante", "descricao_publicacao": "Contexto", "inicio_segundos": 0, "fim_segundos": 30}
        partial = []
        cancel_calls = 0

        def cancel_after_first_step():
            nonlocal cancel_calls
            cancel_calls += 1
            return cancel_calls > 1

        with patch("core.cutter._gerar_resposta_ollama", return_value=response) as ollama, patch(
            "core.cutter._extrair_candidatos", return_value=EditorialCandidates([candidate])
        ):
            with self.assertRaises(GenerationCancelled):
                _gerar_dossie_editorial_unico(
                    "transcricao",
                    360,
                    segments,
                    20,
                    60,
                    cancel_callback=cancel_after_first_step,
                    partial_callback=partial.append,
                )
            self.assertEqual(len(partial), 1)
            self.assertEqual(partial[0]["steps_completed"], 1)
            self.assertEqual(partial[0]["candidatos"][0]["step"], 1)
            ollama.reset_mock()
            resumed = _gerar_dossie_editorial_unico(
                "transcricao",
                360,
                segments,
                20,
                60,
                resume_analysis=partial[0],
            )

        self.assertEqual(ollama.call_count, 2)
        self.assertEqual(resumed.steps_total, 3)
        self.assertEqual(resumed.steps_completed, 3)

    def test_parser_repara_json_com_markdown_e_chave_sinonima(self):
        resposta = {
            "response": "Aqui estão os momentos:\n```json\n{\"momentos\":[{\"titulo\":\"Descoberta\"}]}\n```\nEspero que ajude."
        }
        self.assertEqual(_extrair_candidatos(resposta), [{"titulo": "Descoberta"}])

    def test_parser_remove_bloco_think_antes_de_extrair_json(self):
        resposta = {
            "response": "<think>Vou organizar a resposta {com cuidado}.</think>\n```json\n{\"melhores_momentos\":[{\"titulo\":\"Descoberta\"}]}\n```"
        }
        self.assertEqual(_extrair_candidatos(resposta), [{"titulo": "Descoberta"}])

    def test_parser_aceita_primeira_lista_de_dicionarios_com_chave_desconhecida(self):
        resposta = {"response": '{"resumo":"Bloco relevante","momentos_virais":[{"titulo":"Descoberta"}]}' }
        self.assertEqual(_extrair_candidatos(resposta), [{"titulo": "Descoberta"}])

    def test_parser_preserva_json_bruto_quando_nao_encontra_lista_de_candidatos(self):
        resposta = {"response": '{"resumo":"Bloco sem momentos","observacoes":"Nenhum trecho"}' }
        with self.assertRaisesRegex(ValueError, r"empty_editorial_response; sem candidatos válidos\. RAW: \{\"resumo\":\"Bloco sem momentos\",\"observacoes\":\"Nenhum trecho\"\}"):
            _extrair_candidatos(resposta)

    def test_parser_registra_texto_bruto_quando_json_e_invalido(self):
        resposta = {"response": "Aqui estão os cortes: {\"cortes\":[incompleto]"}
        with self.assertRaisesRegex(ValueError, r"parse_error_raw:.*Aqui estão os cortes"):
            _extrair_candidatos(resposta)

    def test_parser_rejeita_placeholders_de_corte_e_preserva_metadado_factual(self):
        placeholder = {"response": '{"melhores_momentos":[{"titulo":"Gancho viral","descricao_publicacao":"Por que é uma Vaca Roxa..."}]}' }
        factual = {"response": '{"melhores_momentos":[{"titulo":"A marca de 5 mil fotos","descricao_publicacao":"O fotógrafo explica o uso de dois cartões durante o show."}]}' }
        with self.assertRaisesRegex(ValueError, "placeholder_editorial_response"):
            _extrair_candidatos(placeholder)
        self.assertEqual(_extrair_candidatos(factual)[0]["titulo"], "A marca de 5 mil fotos")

    def test_indice_editorial_reintenta_schema_quando_modelo_retorna_mapa_de_transcricao(self):
        respostas = [
            {"status_code": 200, "response": '{"[%d] %d.000-%d.000: %s": ",", ": [{": "#", "172.000-176.000": "Fala do vídeo"}'},
            {"status_code": 200, "response": '{"resumo_conteudo":"Resumo do vídeo inteiro.","capitulos":[{"titulo":"Introdução","inicio_segundos":0,"fim_segundos":20},{"titulo":"Chegada","inicio_segundos":20,"fim_segundos":40},{"titulo":"Preparação","inicio_segundos":40,"fim_segundos":60},{"titulo":"Evento","inicio_segundos":60,"fim_segundos":80},{"titulo":"Público","inicio_segundos":80,"fim_segundos":100},{"titulo":"Encerramento","inicio_segundos":100,"fim_segundos":120}]}'},
        ]
        segmentos = [
            {"indice": 0, "inicio": 0, "fim": 60, "texto": "A introdução do vídeo."},
            {"indice": 1, "inicio": 60, "fim": 120, "texto": "O desenvolvimento do vídeo."},
        ]
        with patch("core.cutter._gerar_resposta_ollama", side_effect=respostas) as provider:
            resultado = _gerar_indice_editorial("A introdução do vídeo. O desenvolvimento do vídeo.", 120, segmentos)
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(len(resultado), 6)
        self.assertEqual(resultado[0]["inicio"], 0)
        self.assertEqual(resultado[1]["fim"], 40)
        self.assertEqual(resultado[-1]["fim"], 120)

    def test_timeout_ollama_aplica_formula_e_limites(self):
        self.assertEqual(_calcular_timeout_ollama(0), 120)
        self.assertEqual(_calcular_timeout_ollama(60), 210)
        self.assertEqual(_calcular_timeout_ollama(600), 1020)
        self.assertEqual(_calcular_timeout_ollama(1000), 1200)

    def test_deduplica_titulo_e_momento_sobreposto(self):
        cortes = [
            {"titulo": "A mesma descoberta", "inicio": 100, "fim": 160, "score_vaca_roxa": 80},
            {"titulo": "A mesma descoberta", "inicio": 106, "fim": 166, "score_vaca_roxa": 90},
            {"titulo": "Outro momento", "inicio": 200, "fim": 260, "score_vaca_roxa": 70},
            {"titulo": "Outro recorte", "inicio": 210, "fim": 270, "score_vaca_roxa": 60},
        ]
        resultado = _deduplicar_cortes(cortes)
        self.assertEqual([corte["titulo"] for corte in resultado], ["A mesma descoberta", "Outro momento"])

    def test_deduplica_titulos_semelhantes_mesmo_com_intervalos_distintos(self):
        cortes = [
            {"titulo": "A descoberta importante", "inicio": 0, "fim": 20},
            {"titulo": "Descoberta importante", "inicio": 30, "fim": 50},
        ]
        resultado = _deduplicar_cortes(cortes)
        self.assertEqual(len(resultado), 2)

    def test_fallback_nao_usa_ruido_de_audio_como_titulo(self):
        segmentos = [
            {"indice": 0, "inicio": 0, "fim": 10, "texto": "[Som de água]"},
            {"indice": 1, "inicio": 10, "fim": 20, "texto": "A trilha começa no mirante."},
            {"indice": 2, "inicio": 20, "fim": 30, "texto": "A vista muda completamente."},
            {"indice": 3, "inicio": 30, "fim": 40, "texto": "[Música]"},
        ]
        resultado = _candidatos_fallback(segmentos, 40, 20, 30)
        self.assertTrue(resultado)
        self.assertTrue(all(not item["titulo"].startswith("[") for item in resultado))

    def test_musica_tocando_eh_rejeitada_como_corte(self):
        segmentos = [{"inicio": 0, "fim": 20, "texto": "[MÚSICA TOCANDO]"}]
        self.assertTrue(_candidato_somente_ruido_audio({"inicio": 0, "fim": 20}, segmentos))

    def test_candidato_ia_nao_eh_descartado_sem_pontuacao_whisper(self):
        segmentos = [
            {"indice": indice, "inicio": indice * 5, "fim": (indice + 1) * 5, "texto": f"fala contínua {indice}"}
            for indice in range(5)
        ]
        resultado = _candidatos_para_revisao(
            [{"titulo": "A descoberta do trecho", "inicio_segundos": 0, "fim_segundos": 25}],
            segmentos,
            25,
            10,
            30,
        )
        self.assertEqual(len(resultado), 1)

    def test_candidato_ia_aceita_timestamps_formatados(self):
        segmentos = [
            {"indice": indice, "inicio": indice * 5, "fim": (indice + 1) * 5, "texto": f"fala contínua {indice}"}
            for indice in range(12)
        ]
        resultado = _candidatos_para_revisao(
            [{"titulo": "O trecho completo", "inicio_segundos": "00:10", "fim_segundos": "00:55"}],
            segmentos,
            60,
            10,
            60,
        )
        self.assertEqual(len(resultado), 1)

    def test_timestamps_relativos_de_blocos_sao_convertidos_para_absolutos(self):
        candidato = _normalizar_candidato_bloco(
            {"titulo": "Momento", "inicio_segundos": 10, "fim_segundos": 55},
            660,
            840,
        )
        self.assertEqual(candidato["inicio_segundos"], 670)
        self.assertEqual(candidato["fim_segundos"], 715)

    def test_steps_absolutos_e_relativos_preservam_cortes_2_3_e_4(self):
        segmentos = [
            {"indice": indice, "inicio": indice * 10, "fim": (indice + 1) * 10, "texto": f"Fala factual do trecho {indice}."}
            for indice in range(60)
        ]
        respostas = [
            {"titulo": "Momento do primeiro bloco", "descricao_publicacao": "Contexto do primeiro bloco.", "inicio_segundos": 20, "fim_segundos": 80},
            {"titulo": "Momento relativo do segundo bloco", "descricao_publicacao": "Contexto do segundo bloco.", "inicio_segundos": 20, "fim_segundos": 80},
            {"titulo": "Momento absoluto do terceiro bloco", "descricao_publicacao": "Contexto do terceiro bloco.", "inicio_segundos": 350, "fim_segundos": 410},
            {"titulo": "Momento relativo do quarto bloco", "descricao_publicacao": "Contexto do quarto bloco.", "inicio_segundos": 20, "fim_segundos": 80},
        ]

        def resposta_por_step(*_args, **_kwargs):
            import json
            candidato = respostas.pop(0)
            return {"status_code": 200, "response": json.dumps({"resumo_conteudo": "Resumo", "melhores_momentos": [candidato]})}

        with patch("core.cutter._gerar_resposta_ollama", side_effect=resposta_por_step), patch("core.cutter.OLLAMA_CUTS_ENABLED", True):
            resultado = gerar_cortes_com_retry(
                "transcricao",
                600,
                segmentos,
                minimo=1,
                duracao_minima=30,
                duracao_maxima=90,
            )

        cortes_finais = resultado["cortes"]
        self.assertEqual(resultado["status"], "completed")
        self.assertGreaterEqual(len(cortes_finais), 4)
        self.assertTrue(all(0 <= corte["inicio"] < corte["fim"] <= 600 for corte in cortes_finais))
        self.assertTrue(any(corte["inicio"] >= 180 for corte in cortes_finais))
        self.assertTrue(any(corte["inicio"] >= 330 for corte in cortes_finais))
        self.assertTrue(any(corte["inicio"] >= 495 for corte in cortes_finais))

    def test_video_longo_com_um_candidato_nao_eh_concluido(self):
        segmentos = [
            {"indice": indice, "inicio": indice * 30, "fim": (indice + 1) * 30, "texto": "[MÚSICA TOCANDO]" if indice == 16 else f"Fala relevante sobre o assunto {indice}."}
            for indice in range(17)
        ]
        resposta = [{"titulo": "A música toca intensamente", "inicio_segundos": 500, "fim_segundos": 510}]
        with patch("core.cutter._gerar_dossie_editorial_unico", return_value=resposta), patch("core.cutter.OLLAMA_CUTS_ENABLED", True):
            resultado = gerar_cortes_com_retry("transcricao", 510, segmentos, duracao_minima=20, duracao_maxima=60)
        self.assertEqual(resultado["status"], "completed")
        self.assertEqual(resultado["minimo"], 3)
        self.assertEqual(len(resultado["candidatos"]), 1)

    def test_job_real_expande_cinco_candidatos_e_libera_renderizacao(self):
        segmentos = []
        for inicio in list(range(0, 330, 2)) + list(range(1350, 1474, 2)):
            segmentos.append({
                "indice": len(segmentos),
                "inicio": inicio,
                "fim": inicio + 2,
                "texto": "[GRITOS DE GOL]" if inicio >= 1400 else f"Fala factual do trecho {inicio}.",
            })
        candidatos = [
            {"titulo": "Fusca 1974: 50 Anos de Família", "inicio_segundos": 128.4, "fim_segundos": 166.4},
            {"titulo": "Colaboração com Mohamed", "inicio_segundos": 168.4, "fim_segundos": 176.4},
            {"titulo": "Colaboração com Mohamed para o Fusca", "inicio_segundos": 168.4, "fim_segundos": 174.4},
            {"titulo": "Agradecimento e Instagram", "inicio_segundos": 178.4, "fim_segundos": 188.4},
            {"titulo": "Gritos de gol enlouquecem a galera", "inicio_segundos": 1400.4, "fim_segundos": 1472.4},
        ]
        validos = _candidatos_para_revisao(candidatos, segmentos, 1474.4, 30, 60)
        self.assertEqual(len(validos), 4)
        intervalos = sorted((corte["inicio"], corte["fim"]) for corte in validos)
        self.assertTrue(all(intervalos[indice + 1][0] - intervalos[indice][1] >= 30 for indice in range(len(intervalos) - 1)))
        self.assertTrue(all(corte["fim"] - corte["inicio"] >= 30 for corte in validos))
        self.assertTrue(any("Gritos de gol" in corte["titulo"] for corte in validos))

        with patch("core.cutter._gerar_dossie_editorial_unico", return_value=candidatos), patch("core.cutter.OLLAMA_CUTS_ENABLED", True):
            resultado = gerar_cortes_com_retry("transcricao", 1474.4, segmentos, minimo=9, duracao_minima=30, duracao_maxima=60)

        self.assertEqual(resultado["status"], "completed")
        self.assertEqual(resultado["minimo"], 3)
        self.assertGreater(len(resultado["cortes"]), 0)
        self.assertTrue(all(corte["fim"] - corte["inicio"] >= 30 for corte in resultado["cortes"]))

    def test_force_generate_never_reintroduces_overlapping_clones(self):
        segmentos = [
            {"indice": indice, "inicio": indice * 10, "fim": (indice + 1) * 10, "texto": f"A fala relevante do trecho {indice}."}
            for indice in range(6)
        ]
        resultado = _selecionar_candidatos_locais_com_insistencia(segmentos, 60, 20, 30, [])
        for indice, candidato in enumerate(resultado):
            self.assertFalse(any(_cortes_repetidos(candidato, anterior) for anterior in resultado[:indice]))

    def test_force_generate_allows_empty_result_when_existing_interval_blocks_material(self):
        segmentos = [
            {"indice": indice, "inicio": indice * 10, "fim": (indice + 1) * 10, "texto": f"A fala relevante do trecho {indice}."}
            for indice in range(6)
        ]
        resultado = _selecionar_candidatos_locais_com_insistencia(
            segmentos, 60, 20, 30, [{"inicio": 0, "fim": 60}]
        )
        self.assertEqual(resultado, [])

    def test_excluded_cuts_do_not_block_a_new_cycle(self):
        segmentos = [
            {"indice": indice, "inicio": indice * 10, "fim": (indice + 1) * 10, "texto": f"A fala relevante do trecho {indice}."}
            for indice in range(6)
        ]
        resultado = _selecionar_candidatos_locais_com_insistencia(
            segmentos, 60, 20, 30, [{"inicio": 0, "fim": 60, "status": "excluido"}]
        )
        self.assertTrue(resultado)

    def test_fallback_gera_manchete_editorial_local(self):
        segmentos = [
            {"indice": 0, "inicio": 0, "fim": 10, "texto": "[Música]"},
            {"indice": 1, "inicio": 10, "fim": 20, "texto": "Bom pessoal, a gente chegou na trilha."},
            {"indice": 2, "inicio": 20, "fim": 30, "texto": "A caminhada até o mirante começa agora."},
        ]
        resultado = _candidatos_fallback(segmentos, 30, 20, 30)
        self.assertTrue(resultado)
        self.assertEqual(resultado[0]["titulo"], "Chegou na trilha")

    def test_titulo_local_nao_aplica_catalogo_tematico(self):
        from core.cutter import _titulo_editorial_local

        titulo = _titulo_editorial_local("Falamos sobre fotos e verdade no primeiro show")

        self.assertEqual(titulo, "Falamos sobre fotos verdade primeiro show")
        self.assertNotIn("doação", titulo.casefold())
        self.assertNotIn("motel", titulo.casefold())
        self.assertNotIn("caminhada", titulo.casefold())

    def test_titulo_local_curto_usa_intervalo_temporal(self):
        from core.cutter import _titulo_editorial_local

        self.assertEqual(
            _titulo_editorial_local("[Música] ah", inicio=65, fim=125),
            "Corte do vídeo: [01:05 - 02:05]",
        )

    def test_nome_de_arquivo_remove_caracteres_invalidos(self):
        nome = nome_seguro_arquivo('Título com ? e dois pontos: final.mp4')
        self.assertNotRegex(nome, r'[<>:"/\\|?*]')

    def test_cancelamento_antes_do_processo_nao_inicia_provider(self):
        with patch("core.cutter.subprocess.Popen") as popen:
            with self.assertRaises(GenerationCancelled):
                _gerar_resposta_ollama("teste", cancel_callback=lambda: True)
        popen.assert_not_called()

    def test_requisicao_ollama_eh_stateless_e_tem_temperatura_baixa(self):
        class StreamResponse:
            status_code = 200

            def iter_lines(self, decode_unicode=True):
                yield '{"response":"{}","done":true}'

            def close(self):
                pass

        with patch("core.cutter.requests.post", return_value=StreamResponse()) as post:
            _gerar_resposta_ollama_http("lote um", timeout=2)
            _gerar_resposta_ollama_http("lote dois", timeout=2)

        self.assertEqual(post.call_count, 2)
        primeiro_payload = post.call_args_list[0].kwargs["json"]
        segundo_payload = post.call_args_list[1].kwargs["json"]
        self.assertEqual(primeiro_payload["context"], [])
        self.assertEqual(segundo_payload["context"], [])
        self.assertEqual(primeiro_payload["options"]["temperature"], 0.2)
        self.assertEqual(primeiro_payload["keep_alive"], "15m")
        self.assertIsNot(primeiro_payload, segundo_payload)
        self.assertEqual(primeiro_payload["prompt"], "lote um")
        self.assertEqual(segundo_payload["prompt"], "lote dois")

    def test_timeout_do_provider_entra_em_revisao_com_fallback(self):
        segmentos = [
            {"indice": index, "inicio": index * 5, "fim": (index + 1) * 5, "texto": f"Frase relevante numero {index}."}
            for index in range(8)
        ]
        with patch("core.cutter._gerar_dossie_editorial_unico", side_effect=requests.Timeout("provider sem resposta")) as editorial, patch("core.cutter.OLLAMA_CUTS_ENABLED", True):
            resultado = gerar_cortes_com_retry(
                " ".join(segmento["texto"] for segmento in segmentos),
                40,
                segmentos,
                minimo=3,
                max_tentativas=3,
                duracao_minima=10,
                duracao_maxima=20,
                cancel_callback=lambda: False,
            )
        self.assertEqual(resultado["status"], "failed")
        self.assertEqual(editorial.call_count, 1)
        self.assertEqual(resultado["candidatos"], [])
        self.assertEqual(len(resultado["diagnostico"]), 1)
        self.assertEqual(resultado["diagnostico"][0]["status"], "editorial_unavailable")

    def test_cache_miss_usa_diretor_de_tv_em_uma_unica_chamada(self):
        segmentos = [
            {"indice": index, "inicio": index * 10, "fim": (index + 1) * 10, "texto": f"Frase completa numero {index}."}
            for index in range(4)
        ]
        resposta = {"status_code": 200, "response": '{"melhores_momentos":[{"segmento_inicio":0,"segmento_fim":1,"score_viralidade":88,"titulo":"O detalhe que muda toda a história","gancho":"Frase completa numero 0.","promessa":"A explicação do detalhe","virada":"Frase completa numero 1.","conclusao":"Frase completa numero 1.","autossuficiente":true,"promocional":false,"pontuacoes":{"distintividade":90,"gancho":90,"clareza_promessa":80,"autossuficiencia":85,"compartilhabilidade":80,"evidencia":90}}]}' }
        with patch("core.cutter._gerar_resposta_ollama", return_value=resposta) as provider, patch("core.cutter.OLLAMA_CUTS_ENABLED", True):
            resultado = gerar_cortes_com_retry(
                "Frase completa numero 0. Frase completa numero 1.",
                40,
                segmentos,
                duracao_minima=10,
                duracao_maxima=30,
                titulo_original="Vídeo principal",
                contexto_multimodal="[PICO DE ÁUDIO] 0-10",
            )
        self.assertEqual(provider.call_count, 1)
        prompt = provider.call_args.args[0]
        self.assertIn("Frase completa numero 3.", prompt)
        self.assertIn("Diretor de TV e Especialista em Conteúdo Viral", prompt)
        self.assertIn("garimpar a \"Vaca Roxa\"", prompt)
        self.assertIn("Entrevistas com presidentes, vice-presidentes, representantes", prompt)
        self.assertIn("resumo_conteudo", prompt)
        self.assertIn("inicio_segundos", prompt)
        self.assertIn("descricao_publicacao", prompt)
        self.assertIn("INÍCIO DO MATERIAL PARA ANÁLISE", prompt)
        self.assertIn("É ESTRITAMENTE PROIBIDO retornar os DIÁLOGOS BRUTOS", prompt)
        self.assertIn('"tempo" ou "texto"', prompt)
        self.assertNotIn("transcrição", prompt.lower())
        self.assertIn("RESPONDA ESTRITAMENTE NESTE FORMATO JSON, SEM ADICIONAR NENHUMA OUTRA CHAVE:", prompt)
        self.assertIn('Cada item de `melhores_momentos` deve conter `titulo`, `descricao_publicacao`', prompt)
        self.assertIn("[1] 10.000-20.000", prompt)
        self.assertIn("INÍCIO DO MATERIAL PARA ANÁLISE", prompt)
        self.assertIn("FIM DO MATERIAL", prompt)
        self.assertIn("[PICO DE ÁUDIO] 0-10", prompt)
        self.assertIn("Contextualização Dupla", prompt)
        self.assertEqual(resultado["cortes"][0]["score_vaca_roxa"], 86)

    def test_dossie_aceita_momentos_com_timestamps_em_segundos(self):
        segmentos = [
            {"indice": index, "inicio": index * 10, "fim": (index + 1) * 10, "texto": f"Frase completa numero {index}."}
            for index in range(4)
        ]
        resposta = {"status_code": 200, "response": '{"resumo_conteudo":"O bloco explica uma descoberta relevante.","melhores_momentos":[{"titulo":"A descoberta que muda o resultado","descricao_publicacao":"O trecho apresenta um contraste inesperado.","inicio_segundos":0.0,"fim_segundos":30.0}]}' }
        with patch("core.cutter._gerar_resposta_ollama", return_value=resposta), patch("core.cutter.OLLAMA_CUTS_ENABLED", True):
            resultado = gerar_cortes_com_retry("transcricao", 40, segmentos, duracao_minima=20, duracao_maxima=30)
        self.assertEqual(resultado["status"], "completed")
        self.assertEqual(resultado["cortes"][0]["inicio"], 0)
        self.assertEqual(resultado["cortes"][0]["fim"], 30)
        self.assertEqual(resultado["cortes"][0]["descricao_publicacao"], "O trecho apresenta um contraste inesperado.")
        self.assertEqual(resultado["resumo_conteudo"], "O bloco explica uma descoberta relevante.")

    def test_titulo_sem_evidencia_do_intervalo_e_substituido(self):
        segmentos = [
            {"indice": 0, "inicio": 0, "fim": 10, "texto": "Ricardo explica a organização da escola."},
            {"indice": 1, "inicio": 10, "fim": 20, "texto": "A tradição do Ipiranga prepara o desfile."},
        ]
        candidato = {
            "titulo": "O último frame revela outro assunto",
            "descricao_publicacao": "O último frame mostra um assunto diferente.",
            "inicio_segundos": 0,
            "fim_segundos": 20,
        }
        resultado = _candidatos_para_revisao(
            [candidato], segmentos, 20, duracao_minima=10, duracao_maxima=30
        )
        self.assertEqual(len(resultado), 1)
        self.assertNotEqual(resultado[0]["titulo"], candidato["titulo"])
        self.assertIn("Ricardo", resultado[0]["titulo"])
        self.assertIn("Ricardo", resultado[0]["descricao_publicacao"])

    def test_contexto_multimodal_fica_restrito_ao_step(self):
        from core.cutter import _contexto_multimodal_do_bloco

        contexto = "\n".join([
            "[00:10 - 00:20] [🔊 PICO DE ÁUDIO]",
            "[10:05 - 10:15] [🎬 CORTE DE CÂMERA]",
            "start_time=1210.0 [🔊 PICO DE ÁUDIO]",
        ])
        filtrado = _contexto_multimodal_do_bloco(contexto, 600, 1200)
        self.assertIn("[10:05 - 10:15]", filtrado)
        self.assertNotIn("[00:10 - 00:20]", filtrado)
        self.assertNotIn("start_time=1210.0", filtrado)

    def test_dossie_editorial_processa_steps_e_salva_parciais(self):
        segmentos = [
            {"indice": index, "inicio": index * 10, "fim": (index + 1) * 10, "texto": f"Frase completa numero {index}."}
            for index in range(70)
        ]
        resposta = {"status_code": 200, "response": '{"melhores_momentos":[{"segmento_inicio":0,"segmento_fim":1,"score_viralidade":88,"titulo_sugerido":"Descoberta sobre o resultado","descricao_sugerida":"Descrição factual.","motivo_da_escolha":"Contraste observável.","gancho":"Frase completa numero 0.","promessa":"Entender o resultado","virada":"O contraste aparece.","conclusao":"A ideia termina.","pontuacoes":{"distintividade":90,"gancho":90,"clareza_promessa":80,"autossuficiencia":85,"compartilhabilidade":80,"evidencia":90},"autossuficiente":true,"promocional":false}]}' }
        parciais = []
        with patch("core.cutter._gerar_resposta_ollama", return_value=resposta) as provider, patch("core.cutter.OLLAMA_CUTS_ENABLED", True):
            resultado = _gerar_dossie_editorial_unico(
                " ".join(segmento["texto"] for segmento in segmentos),
                700,
                segmentos,
                10,
                30,
                partial_callback=parciais.append,
            )
        self.assertEqual(provider.call_count, 5)
        self.assertEqual(len(parciais), 5)
        self.assertEqual(len(resultado), 5)
        self.assertIn("Resumo global de apoio", provider.call_args_list[0].args[0])
        self.assertIn("INÍCIO DO MATERIAL PARA ANÁLISE", provider.call_args_list[1].args[0])
        self.assertIn("FIM DO MATERIAL", provider.call_args_list[1].args[0])

    def test_timeout_descarta_fallback_coberto_por_corte_existente(self):
        candidato = {
            "inicio": 0,
            "fim": 20,
            "segmento_inicio": 0,
            "segmento_fim": 1,
            "titulo": "Candidato local",
        }
        with patch("core.cutter._selecionar_candidatos_locais_com_insistencia", return_value=[candidato]), patch(
            "core.cutter._gerar_dossie_editorial_unico", side_effect=requests.Timeout("provider sem resposta")
        ), patch("core.cutter.OLLAMA_CUTS_ENABLED", True):
            resultado = gerar_cortes_com_retry(
                "transcricao",
                30,
                [],
                cortes_existentes=[{"inicio": 0, "fim": 20}],
            )
        self.assertEqual(resultado["candidatos"], [])
        self.assertIn("nenhum corte foi renderizado", resultado["rejeicoes"][0])

    def test_insistencia_entrega_candidato_quando_ciclos_anteriores_cobrem_tudo(self):
        segmentos = [
            {"indice": index, "inicio": index * 10, "fim": (index + 1) * 10, "texto": f"Frase factual numero {index}."}
            for index in range(6)
        ]
        cortes_existentes = [
            {"inicio": 0, "fim": 30},
            {"inicio": 30, "fim": 60},
        ]
        with patch("core.cutter.OLLAMA_CUTS_ENABLED", False):
            resultado = gerar_cortes_com_retry(
                " ".join(segmento["texto"] for segmento in segmentos),
                60,
                segmentos,
                duracao_minima=20,
                duracao_maxima=30,
                cortes_existentes=cortes_existentes,
            )
        self.assertEqual(resultado["status"], "failed")
        self.assertEqual(resultado["candidatos"], [])

    def test_uma_chamada_editorial_enriquece_candidatos_locais(self):
        segmentos = [
            {"indice": index, "inicio": index * 10, "fim": (index + 1) * 10, "texto": f"Frase factual {index} com conclusão."}
            for index in range(6)
        ]
        resposta = {
            "status_code": 200,
            "response": '{"melhores_momentos":[{"segmento_inicio":0,"segmento_fim":2,"titulo":"Descoberta sobre o resultado","descricao_publicacao":"Uma descoberta real do trecho.","hashtags":["#descoberta"],"score_viralidade":88,"angulo_diferente":"O contraste aparece no resultado.","gancho":"Frase factual 0 com conclusão.","promessa":"Entender o resultado","virada":"O contraste aparece","conclusao":"A ideia termina.","autossuficiente":true,"promocional":false,"pontuacoes":{"distintividade":90,"gancho":90,"clareza_promessa":80,"autossuficiencia":85,"compartilhabilidade":80,"evidencia":90}}]}'
        }
        with patch("core.cutter._gerar_resposta_ollama", return_value=resposta) as provider, patch("core.cutter.OLLAMA_CUTS_ENABLED", True):
            resultado = gerar_cortes_com_retry("transcricao", 60, segmentos, duracao_minima=20, duracao_maxima=30)
        self.assertEqual(provider.call_count, 1)
        self.assertGreater(len(resultado["candidatos"]), 0)
        for indice, candidato in enumerate(resultado["candidatos"]):
            self.assertFalse(any(_cortes_repetidos(candidato, anterior) for anterior in resultado["candidatos"][:indice]))
        self.assertEqual(resultado["status"], "completed")
        self.assertEqual(resultado["cortes"][0]["descricao_publicacao"], "Uma descoberta real do trecho.")
        self.assertEqual(resultado["cortes"][0]["score_viralidade"], 88)
        self.assertEqual(resultado["cortes"][0]["score_vaca_roxa"], 86)


if __name__ == "__main__":
    unittest.main()