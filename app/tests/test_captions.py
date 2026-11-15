import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from captions import THEMES, ass_text, corrected
from editing import retime_cues, subtitle_settings, visible_cues, whisper_cues

WORDS = [dict(start=0, end=.5, text='Hola'), dict(start=.5, end=1, text='mundo'),
         dict(start=1, end=1.5, text='increíble')]
CUES = [dict(start=0, end=1.5, text='Hola mundo increíble', words=WORDS)]


class CaptionTiming(unittest.TestCase):
    def test_uses_word_offsets_and_preserves_a_pause(self):
        transcription = {'transcription': [dict(offsets={'from': 0, 'to': 1900}, text='Hola mundo.', tokens=[
            dict(text=' Hola', offsets={'from': 0, 'to': 300}),
            dict(text=' mundo', offsets={'from': 900, 'to': 1800}),
            dict(text='.', offsets={'from': 1800, 'to': 1900})])]}
        result = list(whisper_cues(transcription))
        self.assertEqual([cue['text'] for cue in result], ['Hola', 'mundo.'])
        self.assertEqual(result[1]['start'], .9)
        self.assertFalse(result[0]['timing_estimated'])

    def test_legacy_json_gets_readable_phrases_and_estimated_words(self):
        text = 'Esto es una frase bastante larga que necesita dividirse sin perder ninguna palabra al terminar.'
        cues = list(whisper_cues({'transcription': [dict(offsets={'from': 0, 'to': 7000}, text=text)]}))
        self.assertEqual(' '.join(cue['text'] for cue in cues), text)
        self.assertTrue(all(len(cue['words']) <= 7 and cue['timing_estimated'] for cue in cues))

    def test_correcting_words_keeps_times_and_retiming_cuts_drops_removed_words(self):
        corrected_cues = corrected(CUES, ['Hola amigo increíble'])
        self.assertEqual(corrected_cues[0]['words'][1], dict(start=.5, end=1, text='amigo'))
        kept = visible_cues(retime_cues(corrected_cues, [(.5, 1.5)]), 1)
        self.assertEqual(kept[0]['text'], 'amigo increíble')
        self.assertEqual(kept[0]['words'][0]['start'], 0)
        self.assertEqual(kept[0]['words'][-1]['end'], 1)
        changed_count = corrected(CUES, ['Texto corregido'])
        self.assertEqual((changed_count[0]['start'], changed_count[0]['end']), (0, 1.5))
        self.assertTrue(changed_count[0]['timing_estimated'])

    def test_rejects_invalid_styles_and_escapes_ass_commands(self):
        for payload in ({'theme': 'unknown'}, {'font': 'Arial,Injected'}, {'animations': 1}, {'outline': float('nan')}):
            with self.assertRaises(ValueError):
                subtitle_settings({'subtitle_style': payload})
        text = ass_text([dict(start=0, end=1, text=r'{\pos(0,0)}')], subtitle_settings({}), 360, 640)
        self.assertNotIn(r'{\pos(0,0)}', text)
        with self.assertRaises(ValueError):
            corrected(CUES, [])

    def test_all_eight_styles_and_animation_off_are_real_ass(self):
        for theme in THEMES:
            style = subtitle_settings({'subtitle_style': {'theme': theme}})
            text = ass_text(CUES, style, 360, 640)
            self.assertIn('Dialogue:', text)
            self.assertNotIn('nan', text)
            off = ass_text(CUES, dict(style, animations=False), 360, 640)
            self.assertNotIn(r'\t(', off)
            self.assertNotIn(r'\fad(', off)
            self.assertNotIn(r'\kf', off)


@unittest.skipUnless(os.environ.get('JULIO_FFMPEG'), 'Requiere FFmpeg real')
class AnimatedExport(unittest.TestCase):
    def test_all_styles_render_in_mp4_with_audio_and_visible_pixels(self):
        ffmpeg = os.environ['JULIO_FFMPEG']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, theme in enumerate(THEMES):
                style = subtitle_settings({'subtitle_style': {'theme': theme, 'font': ('sans', 'serif', 'barlow')[index % 3]}})
                (root/'captions.ass').write_text(ass_text(CUES, style, 360, 640), encoding='utf-8')
                output = root/(theme+'.mp4')
                subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=black:s=360x640:r=20:d=1.6',
                                '-f', 'lavfi', '-i', 'sine=duration=1.6', '-vf', 'ass=captions.ass',
                                '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-shortest', str(output)],
                               check=True, timeout=40, cwd=root)
                raw = subprocess.run([ffmpeg, '-v', 'error', '-ss', '0.25', '-i', str(output), '-frames:v', '1',
                                      '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'],
                                     check=True, capture_output=True, timeout=20).stdout
                self.assertGreater(sum(value > 80 for value in raw), 100, theme)
                # Se decodifica también el audio del MP4 terminado.
                audio = subprocess.run([ffmpeg, '-v', 'error', '-i', str(output), '-map', '0:a:0',
                                        '-f', 's16le', 'pipe:1'], check=True, capture_output=True, timeout=20).stdout
                self.assertGreater(len(audio), 1000)

    def test_word_highlight_changes_pixels_and_animation_off_holds_the_phrase(self):
        ffmpeg = os.environ['JULIO_FFMPEG']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def frames(animated):
                style = subtitle_settings({'subtitle_style': {'theme': 'dynamic', 'animations': animated, 'font': 'sans'}})
                (root/'captions.ass').write_text(ass_text(CUES, style, 360, 640), encoding='utf-8')
                raw = subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=black:s=360x640:r=4:d=1.5',
                                      '-vf', 'ass=captions.ass', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'],
                                     cwd=root, check=True, capture_output=True, timeout=30).stdout
                length = 360*640*3
                return [raw[i:i+length] for i in range(0, len(raw), length)]
            animated = frames(True)
            self.assertNotEqual(animated[1], animated[3])
            static = frames(False)
            self.assertEqual(static[1], static[3])
            # Un resaltado verde real, no sólo texto blanco ni una simulación CSS.
            rgb = zip(animated[1][0::3], animated[1][1::3], animated[1][2::3])
            self.assertGreater(sum(g > r+20 and g > b+20 for r, g, b in rgb), 30)

    def test_clean_copy_follows_trash_restore_and_delete(self):
        from library import MediaStore
        with tempfile.TemporaryDirectory() as directory:
            store = MediaStore(directory)
            name = 'clip-111111111111.mp4'
            store.path(name).write_bytes(b'final')
            store.caption_base(name).write_bytes(b'clean')
            store.add(dict(name=name, editable_captions=True))
            store.move(name, True)
            self.assertTrue(store.caption_base(name, True).is_file())
            store.move(name, False)
            self.assertEqual(store.caption_base(name).read_bytes(), b'clean')
            store.move(name, True)
            store.empty_trash(True)
            self.assertFalse(store.caption_base(name, True).exists())

    def test_old_clip_gets_a_real_thumbnail_without_changing_the_video(self):
        import server as app
        from library import MediaStore
        ffmpeg = os.environ['JULIO_FFMPEG']
        with tempfile.TemporaryDirectory() as directory:
            store = MediaStore(directory)
            name = 'clip-111111111111.mp4'
            subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=180x320:r=10:d=2',
                            '-c:v', 'libx264', str(store.path(name))], check=True, timeout=30)
            store.add(dict(name=name, start=0, end=2, thumbnail=False))
            before = store.path(name).read_bytes()
            self.assertFalse(store.view()['clips'][0]['thumbnail'])
            with patch.object(app, 'tool', {'ffmpeg': ffmpeg}.get):
                thumbnail = app.ensure_thumbnail(store, name)
            self.assertEqual(thumbnail.read_bytes()[:2], b'\xff\xd8')
            self.assertEqual(store.path(name).read_bytes(), before)
            self.assertTrue(store.view()['clips'][0]['thumbnail'])
            store.move(name, True)
            self.assertTrue(store.thumbnail(name, True).is_file())

    def test_export_correct_and_disable_captions_through_the_real_pipeline(self):
        import server as app
        from library import MediaStore
        ffmpeg, ffprobe = os.environ['JULIO_FFMPEG'], os.environ['JULIO_FFPROBE']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source.mp4'
            subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=black:s=360x640:r=20:d=1.5',
                            '-f', 'lavfi', '-i', 'sine=duration=1.5', '-c:v', 'libx264', '-c:a', 'aac', str(source)],
                           check=True, timeout=30)
            with patch.object(app, 'tool', {'ffmpeg': ffmpeg, 'ffprobe': ffprobe}.get), \
                    patch.object(app, 'DATA', root), patch.object(app, 'STATE', {'edits': {}}), \
                    patch.object(app, 'LICENSE', None):
                store = MediaStore(root)
                name = 'clip-111111111111.mp4'
                app.publish_clip(store, name, dict(start=0, end=1.5),
                                 lambda output: [ffmpeg, '-v', 'error', '-y', '-i', str(source), '-c', 'copy', str(output)],
                                 lambda *_: CUES, burn_subtitles=True,
                                 subtitle_style=subtitle_settings({'subtitle_style': {'theme': 'bounce'}}))
                self.assertTrue(store.caption_base(name).is_file())
                self.assertTrue(store.active_clip(name)['editable_captions'])
                self.assertTrue(app.LOCK.acquire(False))
                app.process('edit', dict(name=name, id='correct', start=0, end=1.5,
                                        subtitles=True, burn_subtitles=True, caption_edits=['Hola amigo increíble']))
                self.assertNotIn('error', app.STATE['edits']['correct'])
                updated = store.active_clip(app.STATE['edits']['correct']['name'])
                self.assertEqual(updated['captions'][0]['text'], 'Hola amigo increíble')
                self.assertTrue(updated['burned_subtitles'])
                self.assertTrue(app.LOCK.acquire(False))
                app.process('edit', dict(name=name, id='without', start=0, end=1.5, subtitles=False))
                self.assertNotIn('error', app.STATE['edits']['without'])
                clean = store.active_clip(app.STATE['edits']['without']['name'])
                self.assertFalse(clean['subtitles'])
                self.assertFalse(clean['burned_subtitles'])
                raw = subprocess.run([ffmpeg, '-v', 'error', '-ss', '0.25', '-i', str(store.path(clean['name'])),
                                      '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'],
                                     check=True, capture_output=True, timeout=30).stdout
                self.assertLess(max(raw), 40)


if __name__ == '__main__':
    unittest.main()
