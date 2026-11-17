import array,json,os,re,struct,subprocess,sys,tempfile,threading,unittest,wave,zlib
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import branding
from captions import ass_text,token_words
from editing import subtitle_settings,kept_ranges,retime_cues
from transcription import transcribe_chunks
from monitor import WorkProgress,rank_moments

def png(alpha=True):
    def chunk(name,data):return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
    rows=b''.join(b'\0'+b''.join(bytes((255,0,0,255 if not alpha or 10<=x<50 and 10<=y<40 else 0)) for x in range(64)) for y in range(48))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',64,48,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')

class Synchronization(unittest.TestCase):
    def test_dtw_wins_over_early_generic_offsets(self):
        words=token_words([dict(text=' Julio',t_dtw=120,offsets={'from':0,'to':100}),
            dict(text=' lan',t_dtw=170),dict(text='zó',t_dtw=180),dict(text=' pelota',t_dtw=220)],0,3)
        self.assertGreater(words[0]['start'],1.1)
        self.assertEqual([w['text'] for w in words],['Julio','lanzó','pelota'])
        self.assertLessEqual(words[0]['end'],words[1]['start'])
    def test_never_reveals_future_words_in_any_style(self):
        words=[dict(text='Julio',start=1,end=1.4),dict(text='lanza',start=1.7,end=2),dict(text='pelota',start=2.3,end=2.7)]
        cue=dict(text='Julio lanza pelota',start=1,end=2.7,words=words)
        from captions import THEMES
        for theme in THEMES:
            data=ass_text([cue],subtitle_settings({'subtitle_style':{'theme':theme}}),360,640)
            events=[line for line in data.splitlines() if line.startswith('Dialogue:')]
            self.assertEqual(len(events),3)
            self.assertNotIn('lanza',events[0]);self.assertNotIn('pelota',events[1])
            self.assertIn('0:00:01.00',events[0])
    def test_manual_delay_is_bounded_and_moves_text_only(self):
        cue=dict(text='Hola',start=1,end=2)
        data=ass_text([cue],subtitle_settings({'subtitle_style':{'offset_ms':500}}),360,640)
        self.assertIn('0:00:01.50',data)
        for value in (4000,float('nan'),True):
            with self.assertRaises(ValueError):subtitle_settings({'subtitle_style':{'offset_ms':value}})
    def test_chunks_preserve_absolute_time_and_do_not_repeat_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audio=root/'a.wav';rate=1000
            with wave.open(str(audio),'wb') as out:
                out.setparams((1,2,rate,0,'NONE','not compressed'));out.writeframes(array.array('h',[1000,-1000]*2500).tobytes())
            called=[];progress=WorkProgress()
            def decode(part,result,language):
                called.append(language)
                return {'result':{'language':'es'},'transcription':[dict(text='Hola mundo',offsets={'from':0,'to':2000},tokens=[
                    dict(text=' Hola',offsets={'from':100,'to':400}),dict(text=' mundo',offsets={'from':1500,'to':1900})])]}
            value=transcribe_chunks(audio,root/'a.json',decode,progress,seconds=2)
            self.assertEqual(called,[None,'es','es'])
            starts=[t['offsets']['from'] for s in value['transcription'] for t in s['tokens']]
            self.assertEqual(starts,sorted(set(starts)))
            self.assertTrue(any(s>=2000 for s in starts))
            self.assertEqual(progress.snapshot()['fraction'],1)
    def test_silence_skips_the_model_and_cancel_is_immediate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audio=root/'a.wav'
            with wave.open(str(audio),'wb') as out:
                out.setparams((1,2,1000,0,'NONE','not compressed'));out.writeframes(b'\0'*2000)
            value=transcribe_chunks(audio,root/'a.json',lambda *a:self.fail('No invocar ASR en silencio'))
            self.assertEqual(value['transcription'],[])
            event=threading.Event();event.set()
            with self.assertRaises(ValueError):transcribe_chunks(audio,root/'a.json',None,cancel=event)
    def test_voice_matching_words_is_not_a_fixed_four_minute_progress_watchdog(self):
        import server
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);model=root/'models';model.mkdir();(model/'ggml-base.bin').write_bytes(b'model')
            calls=[]
            def fake_run(args,**kwargs):
                calls.append((args,kwargs))
                Path(args[args.index('-of')+1]+'.json').write_text('{"transcription":[]}')
            def fake_chunks(a,t,decode,*rest):return decode(Path(a),Path(t),'es')
            with patch.object(server,'ROOT',root),patch.object(server,'DATA',root),patch.object(server,'run',fake_run),patch('transcription.transcribe_chunks',fake_chunks):
                server.whisper_audio(root/'a.wav',root/'r.json',align=True)
            self.assertIn('-dtw',calls[0][0]);self.assertNotIn('stall_timeout',calls[0][1])
            self.assertEqual(calls[0][1]['timeout'],1800)
    def test_overlap_cuts_refused_and_slowdown_limited(self):
        with self.assertRaises(ValueError):kept_ranges(dict(start=0,end=8,remove=[dict(start=1,end=4),dict(start=3,end=5)]),8)
    def test_story_with_setup_and_outcome_can_be_selected_without_shouting(self):
        cues=[dict(start=0,end=10,text='Al principio no entendía cómo cambiar el equipo y me dijeron que necesitaba aprender otra técnica distinta.'),
              dict(start=11,end=23,text='Al final me di cuenta que el problema estaba en practicar cada día con paciencia y conseguí resolverlo.')]
        picks,_=rank_moments(cues,30,30,1,threshold=39)
        self.assertEqual(len(picks),1);self.assertIn('desenlace',picks[0]['reason'])

@unittest.skipUnless(os.environ.get('JULIO_FFMPEG') and os.environ.get('JULIO_FFPROBE'),'FFmpeg real requerido')
class RealMedia(unittest.TestCase):
    def run_media(self,args):
        result=subprocess.run(args,capture_output=True,check=True,timeout=60);return result.stdout
    def test_transparent_upload_overlay_video_audio_and_reject_opaque(self):
        ff=os.environ['JULIO_FFMPEG']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);saved=branding.store(root,png(),ff,self.run_media)
            with self.assertRaises(ValueError):branding.store(root,png(False),ff,self.run_media)
            with self.assertRaises(ValueError):branding.image(root,'../../secret')
            source=root/'source.mp4'
            self.run_media([ff,'-v','error','-y','-f','lavfi','-i','color=blue:s=180x320:r=10:d=1',
                '-f','lavfi','-i','sine=duration=1','-c:v','libx264','-c:a','aac','-shortest',str(source)])
            for position in branding.POSITIONS:
                output=root/(position+'.mp4');values=branding.settings(dict(custom_watermark=saved['id'],watermark_position=position))
                self.run_media(branding.overlay_args(ff,source,output,branding.image(root,saved['id']),180,320,.5,values))
                raw=self.run_media([ff,'-v','error','-i',str(output),'-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'])
                self.assertGreater(sum(r>b and r>40 for r,b in zip(raw[0::3],raw[2::3])),10)
                audio=self.run_media([ff,'-v','error','-i',str(output),'-map','0:a:0','-f','s16le','pipe:1']);self.assertGreater(len(audio),1000)
    def test_mp4_has_no_caption_before_voice_start(self):
        ff=os.environ['JULIO_FFMPEG']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cue=dict(text='Julio lanza',start=.8,end=1.9,words=[dict(text='Julio',start=.8,end=1.2),dict(text='lanza',start=1.3,end=1.9)])
            (root/'captions.ass').write_text(ass_text([cue],subtitle_settings({'subtitle_style':{'theme':'slide'}}),180,320),encoding='utf-8')
            raw=subprocess.run([ff,'-v','error','-f','lavfi','-i','color=black:s=180x320:r=10:d=2',
                '-vf','ass=captions.ass','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],cwd=root,capture_output=True,check=True,timeout=30).stdout
            stride=180*320*3;frames=[raw[i:i+stride] for i in range(0,len(raw),stride)]
            self.assertLess(max(frames[4]),5)
            self.assertGreater(sum(v>80 for v in frames[10]),20)

if __name__=='__main__':unittest.main()
