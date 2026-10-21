import os
import tempfile
import unittest
from unittest.mock import patch

from core.cutter import calcular_corte_com_rosto
from core.media_tools import MediaToolError, _executar_render_com_fallback, _run, montar_comando_render, obter_opcoes_encoder, renderizar_corte


class MediaToolsTests(unittest.TestCase):
    def test_smart_crop_faz_fallback_no_terco_superior(self):
        class Capture:
            def get(self, propriedade):
                return {3: 1080, 4: 2200, 5: 30}.get(propriedade, 0)

            def set(self, *_):
                return True

            def read(self):
                return True, object()

            def release(self):
                pass

        class Detector:
            def detectMultiScale(self, *_args, **_kwargs):
                return []

        with patch('core.cutter.cv2.VideoCapture', return_value=Capture(), create=True), patch(
            'core.cutter.cv2.CascadeClassifier', return_value=Detector(), create=True
        ), patch('core.cutter.os.path.exists', return_value=True), patch(
            'core.cutter.cv2.cvtColor', return_value=object()
        ):
            filtro = calcular_corte_com_rosto('source.mp4', 0, 4)
        self.assertTrue(filtro.startswith('filter_complex:'))
        self.assertIn('split=2[bgsrc][fgsrc]', filtro)
        self.assertIn('boxblur=10:2,scale=1080:1920[bg]', filtro)
        self.assertIn('[bg][fg]overlay=(W-w)/2:(H-h)/2[outv]', filtro)

    def test_smart_crop_prioriza_maior_face_entre_amostras(self):
        class Capture:
            def get(self, propriedade):
                return {3: 1920, 4: 1080, 5: 30}.get(propriedade, 0)

            def set(self, *_):
                return True

            def read(self):
                return True, object()

            def release(self):
                pass

        class Detector:
            def __init__(self):
                self.chamada = 0

            def detectMultiScale(self, *_args, **_kwargs):
                self.chamada += 1
                return [(100, 100, 20, 20)] if self.chamada == 1 else [(700, 200, 100, 100)]

        with patch('core.cutter.cv2.VideoCapture', return_value=Capture(), create=True), patch(
            'core.cutter.cv2.CascadeClassifier', return_value=Detector(), create=True
        ), patch('core.cutter.os.path.exists', return_value=True), patch(
            'core.cutter.cv2.cvtColor', return_value=object()
        ):
            filtro = calcular_corte_com_rosto('source.mp4', 0, 4)
        self.assertEqual(filtro, 'crop=608:1080:446:0')

    def test_montar_comando_render_usa_parametros_cpu_unificados(self):
        command = montar_comando_render(
            'ffmpeg', 'source.mp4', 'output.mp4', 1.25, 4.75,
            'crop=100:200:10:20,scale=1080:1920:flags=lanczos',
            encoder='libx264',
        )
        self.assertLess(command.index('-i'), command.index('-ss'))
        self.assertLess(command.index('-ss'), command.index('-t'))
        self.assertLess(command.index('-t'), command.index('-avoid_negative_ts'))
        self.assertEqual(command[command.index('-avoid_negative_ts') + 1], 'make_zero')
        self.assertEqual(command[command.index('-t') + 1], '3.500')
        self.assertNotIn('-to', command)
        self.assertIn('crop=100:200:10:20,scale=1080:1920:flags=bicubic,format=yuv420p', command)
        self.assertEqual(command[command.index('-preset') + 1], 'faster')
        self.assertEqual(command[command.index('-crf') + 1], '20')
        self.assertEqual(command[command.index('-b:a') + 1], '160k')

    def test_montar_comando_render_mapeia_saida_do_filtro_complexo(self):
        filtro = (
            'filter_complex:[0:v]split=2[bgsrc][fgsrc];'
            '[bgsrc]scale=540:960:force_original_aspect_ratio=increase,'
            'crop=540:960,boxblur=10:2,scale=1080:1920[bg];'
            '[fgsrc]scale=1080:1920:force_original_aspect_ratio=decrease[fg];'
            '[bg][fg]overlay=(W-w)/2:(H-h)/2[outv]'
        )
        command = montar_comando_render('ffmpeg', 'source.mp4', 'output.mp4', 1, 4, filtro, encoder='libx264')
        self.assertIn('-filter_complex', command)
        self.assertNotIn('-vf', command)
        self.assertEqual(command[command.index('-map') + 1], '[outv]')
        self.assertIn('0:a?', command)

    def test_obter_opcoes_encoder_prioriza_amf_disponivel(self):
        with patch('core.media_tools._encoders_disponiveis', return_value=' h264_amf '):
            options = obter_opcoes_encoder('ffmpeg')
        self.assertEqual(options['name'], 'h264_amf')
        self.assertIn('h264_amf', options['args'])
        self.assertIn('vbr_peak', options['args'])

    def test_render_faz_fallback_para_cpu_em_falha_de_device_amf(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, 'source.mp4')
            output = os.path.join(folder, 'out.mp4')
            open(source, 'wb').close()
            with patch('core.media_tools._encoders_disponiveis', return_value='h264_amf'), patch(
                'core.media_tools._run', side_effect=[MediaToolError('h264_amf: device initialization failed'), None]
            ) as run, patch('core.media_tools.registrar_log'):
                _executar_render_com_fallback('ffmpeg', source, output, 0, 2, 'crop=10:20:0:0', 5)
            self.assertEqual(run.call_count, 2)
            self.assertIn('h264_amf', run.call_args_list[0].args[0])
            self.assertIn('libx264', run.call_args_list[1].args[0])

    def test_run_rejects_nonzero_returncode(self):
        with patch('core.media_tools.subprocess.run', return_value=type('Result', (), {'returncode': 1, 'stderr': 'ffmpeg failed', 'stdout': ''})()):
            with self.assertRaises(MediaToolError):
                _run(['ffmpeg'], 5)

    def test_run_converts_timeout_to_media_error(self):
        import subprocess
        with patch('core.media_tools.subprocess.run', side_effect=subprocess.TimeoutExpired(['ffmpeg'], 5)):
            with self.assertRaises(MediaToolError):
                _run(['ffmpeg'], 5)

    def test_render_rejects_missing_source_before_process(self):
        with self.assertRaises(MediaToolError):
            renderizar_corte('missing.mp4', 'out.mp4', 0, 2)

    def test_render_removes_invalid_partial_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, 'source.mp4')
            output = os.path.join(folder, 'out.mp4')
            open(source, 'wb').close()
            with patch('core.media_tools.obter_duracao', return_value=10), patch('core.media_tools.localizar_ferramentas', return_value=('ffmpeg', 'ffprobe')), patch('core.media_tools._run', side_effect=MediaToolError('timeout')):
                with self.assertRaises(MediaToolError):
                    renderizar_corte(source, output, 0, 2)
            self.assertFalse(os.path.exists(output))

    def test_render_rejects_successful_ffmpeg_without_output_file(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, 'source.mp4')
            output = os.path.join(folder, 'out.mp4')
            open(source, 'wb').close()
            with patch('core.media_tools.obter_duracao', return_value=10), patch('core.media_tools.localizar_ferramentas', return_value=('ffmpeg', 'ffprobe')), patch('core.media_tools._run'):
                with self.assertRaises(MediaToolError):
                    renderizar_corte(source, output, 0, 2)


if __name__ == '__main__':
    unittest.main()
