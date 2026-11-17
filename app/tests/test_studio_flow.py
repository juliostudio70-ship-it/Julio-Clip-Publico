"""Flujo HTTP real: importar → proyecto → previsualizar → exportar → descargar."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as app

@unittest.skipUnless(os.environ.get('JULIO_FFMPEG') and os.environ.get('JULIO_FFPROBE'),'FFmpeg real requerido')
class StudioFlow(unittest.TestCase):
    def test_import_preview_matches_export_and_reset_keeps_activation(self):
        ffmpeg=os.environ['JULIO_FFMPEG'];ffprobe=os.environ['JULIO_FFPROBE']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'original-externo.mp4'
            subprocess.run([ffmpeg,'-v','error','-y','-f','lavfi','-i','testsrc2=s=192x108:r=8:d=2',
                '-f','lavfi','-i','sine=duration=2','-c:v','libx264','-c:a','aac',str(source)],check=True,timeout=40)
            saved=hashlib.sha256(source.read_bytes()).hexdigest()
            state=dict(status='Listo',busy=False,source=None,source_platform=None,source_duration=None,clips=[],suggestions=[],edits={})
            with patch.object(app,'DATA',root),patch.object(app,'STATE',state),patch.object(app,'LIVE',None),patch.object(app,'PUBLISHED_JOB',None), \
                 patch.object(app,'LICENSE',None),patch.object(app,'tool',side_effect={'ffmpeg':ffmpeg,'ffprobe':ffprobe}.get):
                server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);port=server.server_port
                threading.Thread(target=server.serve_forever,daemon=True).start()
                def request(path,body=None,raw=False,headers=None):
                    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=40)
                    h={'Origin':f'http://127.0.0.1:{port}','X-Julio-Token':app.TOKEN}
                    if headers:h.update(headers)
                    conn.request('POST' if body is not None else 'GET',path,body if raw else json.dumps(body) if body is not None else None,h)
                    r=conn.getresponse();data=r.read();result=(r.status,data,dict(r.getheaders()));conn.close();return result
                def wait_job():
                    until=time.monotonic()+100
                    while state['busy'] and time.monotonic()<until:time.sleep(.1)
                    self.assertFalse(state['busy']);self.assertNotIn('Error:',state['status'])
                try:
                    self.assertEqual(request('/api/upload',source.read_bytes(),True)[0],200)
                    from test_sync_branding import png
                    brand_status,brand_body,_=request('/api/watermark',png(),True)
                    self.assertEqual(brand_status,200)
                    brand_key=json.loads(brand_body)['id']
                    self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),saved)
                    self.assertEqual(state['source_duration'],2)
                    code,body,h=request('/source-video',headers={'Range':'bytes=0-31'})
                    self.assertEqual(code,206);self.assertEqual(len(body),32);self.assertTrue(h['Content-Range'].startswith('bytes 0-31/'))
                    draft=dict(name='imported.video',start=0,end=1,subtitles=False,format='vertical',
                               resolution=720,quality='light',fit='crop',speed=1.25,volume=.5,zoom=1.2,frame_x=.7,frame_y=.3,effect='warm',fade=True)
                    draft.update(custom_watermark=brand_key,watermark=True,watermark_position='top-right',watermark_scale=.2)
                    self.assertEqual(request('/api/project-save',draft)[0],200)
                    info=json.loads(request('/api/clip-info',{'name':'imported.video'})[1])
                    self.assertEqual(info['project']['frame_x'],.7)
                    preview_id='a'*24
                    self.assertEqual(request('/api/editor-preview',dict(draft,id=preview_id))[0],202);wait_job()
                    self.assertTrue(state['edits'][preview_id]['preview'])
                    preview=(root/'editor-preview.mp4').read_bytes()
                    export_id='b'*24
                    self.assertEqual(request('/api/edit',dict(draft,id=export_id))[0],202);wait_job()
                    name=state['edits'][export_id]['name']
                    code,data,h=request('/clips/'+name);self.assertEqual(code,200)
                    self.assertEqual(hashlib.sha256(preview).hexdigest(),hashlib.sha256(data).hexdigest())
                    clip=app.MediaStore(root).active_clip(name);self.assertEqual((clip['width'],clip['height']),(720,1280))
                    self.assertLessEqual(clip['end']-clip['start'],180)
                    self.assertEqual(request('/api/trash',{'name':name})[0],200)
                    self.assertFalse(app.MediaStore(root).view()['clips'])
                    self.assertEqual(request('/api/restore',{'name':name})[0],200)
                    self.assertTrue(app.MediaStore(root).view()['clips'])
                    (root/'instalacion.dat').write_bytes(b'conservar-activacion')
                    code,raw,h=request('/api/maintenance-plan',{'temporary_only':False});self.assertEqual(code,200)
                    plan=json.loads(raw)
                    self.assertEqual(request('/api/maintenance-clear',{'temporary_only':False,'confirmation':plan['confirmation'],'phrase':'RESTABLECER JULIO CLIP'})[0],200)
                    self.assertEqual((root/'instalacion.dat').read_bytes(),b'conservar-activacion')
                    self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),saved)
                finally:server.shutdown();server.server_close()
