"""Regresión de límites, preferencias, licencias y exportación de la actualización."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as app
from preferences import Preferences
from render_options import options, post_args
from watermark import export_args
from live import twitch_channel, twitch_media, LiveController


class StudioUpdate(unittest.TestCase):
    def test_fifty_and_three_minutes_are_validated_on_server(self):
        self.assertEqual(app.live_clip_settings({'clip_seconds':180,'clips_per_block':50}),(180,50))
        for payload in ({'clip_seconds':180,'clips_per_block':51},{'clip_seconds':181,'clips_per_block':2},
                        {'clip_seconds':True,'clips_per_block':1},{'clip_seconds':30,'clips_per_block':True}):
            with self.assertRaises(ValueError):app.live_clip_settings(payload)
        self.assertEqual(app.bounds(100,280),(100,280))
        with self.assertRaises(ValueError):app.bounds(100,280.01)

    def test_preferences_and_reset_preserve_license_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=Preferences(root)
            saved=p.save({'performance':'light','resolution':1080,'clip_count':50,'clip_seconds':180})
            self.assertEqual(Preferences(root).load()['clip_count'],50)
            for values in ({'clip_count':51},{'resolution':999},{'theme':'purple'},{'accent':'url(x)'},{'follow_face':1}):
                with self.assertRaises(ValueError):p.save(values)
            (root/'instalacion.dat').write_bytes(b'licencia-original')
            (root/'archivo-ajeno.mp4').write_bytes(b'original-externo')
            (root/'imported.video').write_bytes(b'copia')
            plan=p.plan()
            self.assertNotIn('instalacion.dat',[x['path'] for x in plan['files']])
            with self.assertRaises(ValueError):p.clear(plan['confirmation'],'si')
            p.clear(plan['confirmation'],'RESTABLECER JULIO CLIP')
            self.assertEqual((root/'instalacion.dat').read_bytes(),b'licencia-original')
            self.assertEqual((root/'archivo-ajeno.mp4').read_bytes(),b'original-externo')

    def test_cleanup_only_offers_known_temporary_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=Preferences(root);folder=root/'exportando-prueba';folder.mkdir();(folder/'video.mp4').write_bytes(b'temp')
            (root/'clip-111111111111.mp4').write_bytes(b'final')
            (root/'live').mkdir();(root/'live/bloque.mkv').write_bytes(b'pendiente')
            names=[x['path'] for x in p.plan(True)['files']]
            self.assertEqual(names,['exportando-prueba/video.mp4'])

    def test_real_dashboard_does_not_invent_previous_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefs=Preferences(tmp)
            self.assertIsNone(prefs.dashboard([],False,{'running':False})['best_interest'])
            prefs.record_analysis('real-1',120,2);prefs.record_analysis('real-1',120,2)
            self.assertEqual(prefs.dashboard([],True,{'running':True})['jobs_running'],2)
            self.assertEqual(prefs.dashboard([],False,{})['videos_analyzed'],1)

    def test_twitch_scope_and_https(self):
        self.assertEqual(twitch_channel('https://www.twitch.tv/mi_canal'),'https://www.twitch.tv/mi_canal')
        for url in ('http://twitch.tv/name','https://twitch.tv.evil.com/name','https://twitch.tv/videos/123','https://twitch.tv/directory','https://u:p@twitch.tv/name'):
            with self.assertRaises(ValueError):twitch_channel(url)
        self.assertTrue(twitch_media('https://video-weaver.abc.hls.ttvnw.net/x.m3u8'))
        self.assertFalse(twitch_media('https://ttvnw.net.evil.com/x'))
        self.assertEqual(app.published_platform('https://www.twitch.tv/videos/123456'),'Twitch')

    def test_render_inputs_bounded(self):
        for payload in ({'speed':0},{'zoom':100},{'volume':float('nan')},{'resolution':True},{'fit':'distort'},{'frame_x':2}):
            with self.assertRaises(ValueError):options(payload)

    def test_batch_queue_does_not_keep_the_old_limit_of_ten(self):
        state=dict(source='imported.video',busy=True,status='Listo',suggestions=[
            dict(start=i*40,end=i*40+30,title='Conversación',score=70) for i in range(50)])
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'DATA',Path(tmp)),patch.object(app,'STATE',state),patch.object(app,'export_published') as export:
            app.LOCK.acquire()
            job=app.PublishedJob('batch-export')
            app.process('batch-export',{'indices':list(range(50))},job)
            self.assertEqual(export.call_count,50)
            self.assertEqual(job.snapshot()['status'],'complete')
            self.assertFalse(state['busy'])

    def test_project_does_not_accept_arbitrary_paths_or_invalid_times(self):
        from projects import Projects
        with tempfile.TemporaryDirectory() as tmp:
            projects=Projects(tmp)
            with self.assertRaises(ValueError):projects.save('clip',{'start':0,'end':3,'path':'C:/Windows'},10)
            with self.assertRaises(ValueError):projects.save('clip',{'start':0,'end':200},300)

    def test_session_limit_does_not_delete_the_unfinished_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bloque-00000001.mkv';path.write_bytes(b'captura-pendiente')
            controller=LiveController(tmp,lambda _:None,lambda *_:False)
            with patch.object(controller,'_entries',return_value=[(path,{})]):controller._consumer('url')
            self.assertEqual(path.read_bytes(),b'captura-pendiente')
            self.assertFalse(path.with_suffix('.hecho').exists())
            self.assertTrue(controller.capture_stop.is_set())

    def test_new_installations_use_only_random_seed_old_tokens_still_match(self):
        from license_client import LicenseGate
        with tempfile.TemporaryDirectory() as tmp:
            gate=LicenseGate({'url':'https://abcdefghijklmnopqrst.supabase.co','key':'sb_publishable_test'},Path(tmp))
            with patch('license_client.windows_protect',side_effect=OSError()),patch('license_client.device_token') as legacy:
                token=gate.installation()
                legacy.assert_not_called()
                self.assertEqual(len(token),64)
                other=LicenseGate(gate.config,Path(tmp));self.assertEqual(other.installation(),token)
            (Path(tmp)/'instalacion.dat').write_bytes(b'\x02'+b'x'*32)
            old=LicenseGate(gate.config,Path(tmp))
            with patch('license_client.device_token',return_value='old-unchanged') as legacy:
                self.assertEqual(old.installation(),'old-unchanged');legacy.assert_called_once_with(b'x'*32)

    def test_long_video_selection_can_keep_more_than_ten_candidates(self):
        from monitor import choose_moments
        candidates=[dict(start=i*35,end=i*35+30,score=70,title='Conversación '+str(i)) for i in range(55)]
        picked,_=choose_moments(candidates,[],50,True)
        self.assertEqual(len(picked),50)


@unittest.skipUnless(os.environ.get('JULIO_FFMPEG') and os.environ.get('JULIO_FFPROBE'),'Requiere FFmpeg real')
class ActualStudioVideo(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.ffmpeg=os.environ['JULIO_FFMPEG'];self.probe=os.environ['JULIO_FFPROBE']
        self.source=self.root/'source.mp4'
        subprocess.run([self.ffmpeg,'-v','error','-y','-f','lavfi','-i','testsrc2=s=320x180:r=8:d=2',
                        '-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-c:a','aac','-shortest',str(self.source)],check=True,timeout=40)
        self.media=json.loads(subprocess.check_output([self.probe,'-v','error','-show_format','-show_streams','-of','json',str(self.source)]))
    def tearDown(self):self.tmp.cleanup()

    def test_six_real_export_dimensions_and_decodable_audio(self):
        for resolution in (720,1080):
            for fmt,expected in [('vertical',(resolution,resolution*16//9)),('landscape',(resolution*16//9,resolution)),('square',(resolution,resolution))]:
                with self.subTest(resolution=resolution,format=fmt):
                    output=self.root/f'{fmt}-{resolution}.mp4'
                    args=export_args(self.ffmpeg,self.source,output,0,1,self.media,None,False,
                        format_name=fmt,render_options={'resolution':resolution,'quality':'light','fit':'crop'})
                    subprocess.run(args,check=True,timeout=120,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                    media=json.loads(subprocess.check_output([self.probe,'-v','error','-show_streams','-of','json',str(output)]))
                    v=next(s for s in media['streams'] if s['codec_type']=='video')
                    self.assertEqual((v['width'],v['height']),expected)
                    self.assertTrue(any(s['codec_type']=='audio' for s in media['streams']))
                    subprocess.run([self.ffmpeg,'-v','error','-i',str(output),'-f','null','-'],check=True,timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)

    def test_actual_180_seconds_and_reject_overlong_edit(self):
        output=self.root/'three-minutes.mp4'
        args=export_args(self.ffmpeg,self.source,output,0,180,self.media,None,False)
        # Repetir el patrón corto sólo para este archivo técnico de prueba.
        args[3:3]=['-stream_loop','-1']
        subprocess.run(args,check=True,timeout=120,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        media=json.loads(subprocess.check_output([self.probe,'-v','error','-show_format','-of','json',str(output)]))
        self.assertLessEqual(float(media['format']['duration']),180.001)
        self.assertGreater(float(media['format']['duration']),179)
        with self.assertRaises(ValueError):post_args(self.ffmpeg,self.source,output,self.media,options({'speed':.5}),180)

    def test_speed_volume_zoom_and_effect_preserve_resolution(self):
        output=self.root/'edited.mp4';values=options({'speed':2,'volume':.5,'zoom':1.5,'effect':'bw','fade':True})
        subprocess.run(post_args(self.ffmpeg,self.source,output,self.media,values,2),check=True,timeout=80,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        media=json.loads(subprocess.check_output([self.probe,'-v','error','-show_format','-show_streams','-of','json',str(output)]))
        self.assertAlmostEqual(float(media['format']['duration']),1,delta=.15)
        v=next(s for s in media['streams'] if s['codec_type']=='video');self.assertEqual((v['width'],v['height']),(320,180))
