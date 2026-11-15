from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitor import LiveMonitor, rank_moments, restore_cue_times


class MonitorTest(unittest.TestCase):
    def test_sports_transcript_times_stay_in_the_original_scene(self):
        cues = [{'start': 2, 'end': 5, 'text': 'La batea.'},
                {'start': 8.1, 'end': 8.3, 'text': 'Pausa.'},
                {'start': 10, 'end': 13, 'text': 'Cuadrangular.'}]
        mapped = list(restore_cue_times(cues, [(0, 8, 29), (8.33, 12.33, 95)]))
        self.assertEqual([(cue['text'], cue['start']) for cue in mapped],
                         [('La batea.', 31), ('Cuadrangular.', 96.67)])
        self.assertEqual(mapped[1]['end'], 99)

    def test_ad_with_clear_conversation_still_gets_rejected(self):
        cues = [{'start': 0, 'end': 18, 'text':
                 '¡Increíble! Compra ahora y usa el código para esta oferta por tiempo limitado.'}]
        picks, rejects = rank_moments(cues, 20, 20, 1, energy=[1500]*20)
        self.assertEqual(picks, [])
        self.assertIn('anuncio', rejects[0]['reason'])

    def test_ad_break_excludes_middle_but_review_resumes_on_return(self):
        cues = [{'start': 5, 'end': 8, 'text': 'Volvemos después de estos mensajes.'},
                {'start': 17, 'end': 26, 'text': '¡Qué increíble! Nadie se esperaba una sorpresa así.'},
                {'start': 35, 'end': 38, 'text': 'Regresamos al partido.'},
                {'start': 40, 'end': 49, 'text': '¡Cuadrangular decisivo! La pelota cruzó el muro y ganó el equipo.'},
                {'start': 49, 'end': 53, 'text': '¡No me lo creo, qué locura! Ganaron sobre la hora.'}]
        picks, rejects = rank_moments(cues, 62, 20, 3, energy=[900]*62)
        self.assertTrue(picks)
        self.assertTrue(all(pick['start'] >= 35 for pick in picks))
        self.assertTrue(any('anuncio' in rejected['reason'] for rejected in rejects))

    def test_reconnect_totals_media_and_never_counts_an_export_twice(self):
        tracker = LiveMonitor()
        tracker.progress(45)
        tracker.progress(40)
        tracker.end_capture()
        tracker.progress(14)
        tracker.reviewed([{}], [{'reason': 'Sin voz'}])
        tracker.exporting(1)
        tracker.completed()
        tracker.finish()
        snapshot = tracker.snapshot()
        self.assertEqual(snapshot['recorded_seconds'], 59)
        self.assertEqual(snapshot['generated'], 0)
        self.assertEqual(snapshot['pending_clips'], 0)
        self.assertEqual(snapshot['rejected'], 1)
        self.assertFalse(snapshot['recording'])

    def test_rank_prefers_context_and_reactions_and_explains_signal_gaps(self):
        cues = [
            {'start': 0, 'end': 8, 'text': 'Eh, este, eh, este.'},
            {'start': 27, 'end': 33, 'text': '¿Cómo resolvimos el problema con la cámara?'},
            {'start': 34, 'end': 42, 'text': 'De repente regresó la señal porque movimos el cable.'},
            {'start': 42, 'end': 46, 'text': '¡No me lo creo! ¡Qué locura!'},
        ]
        energy = [300] * 72
        energy[42] = 1800
        picks, rejections = rank_moments(cues, 72, 20, 2, [(11, 15)], energy)
        self.assertEqual(len(picks), 1)
        self.assertGreaterEqual(picks[0]['score'], 60)
        self.assertEqual(picks[0]['end']-picks[0]['start'], 20)
        self.assertIn('señal', picks[0]['title'])
        self.assertTrue(any('salto' in item['reason'] for item in rejections))
        self.assertTrue(any('poca conversación' in item['reason'] or 'Poca variedad' in item['reason']
                            for item in rejections))
