"""Ventanas acotadas de voz y tiempos absolutos; sin servicios externos."""
import array
import json
import math
import tempfile
import wave
from pathlib import Path


def speech_bounds(samples, rate, left, right):
    """Acota silencios claros, sin confundir esta prueba energética con un ASR."""
    step=max(1,round(rate*.02));levels=[]
    lo=max(0,int(left*rate));hi=min(len(samples),int(right*rate))
    for start in range(lo,hi,step):
        values=samples[start:min(start+step,hi)]
        levels.append(math.sqrt(sum(v*v for v in values)/max(1,len(values))))
    if not levels:return None
    peak=max(levels)
    if peak<35:return None
    floor=sorted(levels)[len(levels)//10]
    threshold=max(35,min(peak*.12,floor*2.5+35))
    active=[i for i,v in enumerate(levels) if v>=threshold]
    if not active:return None
    return max(left,(lo+active[0]*step)/rate-.025),min(right,(lo+(active[-1]+1)*step)/rate+.04)


def transcribe_chunks(audio, transcript, decode, progress=None, cancel=None, seconds=20):
    """decode recibe WAV/JSON/idioma; los solapes tienen dueño para no duplicar."""
    from captions import phrases, timed_words
    audio,transcript=Path(audio),Path(transcript)
    with wave.open(str(audio),'rb') as reader:
        if reader.getnchannels()!=1 or reader.getsampwidth()!=2:
            raise ValueError('La transcripción necesita audio mono PCM de 16 bits.')
        rate=reader.getframerate();params=reader.getparams();duration=reader.getnframes()/rate
    if not math.isfinite(duration) or duration<=0:raise ValueError('El video no contiene audio legible.')
    total=max(1,math.ceil(duration/seconds));segments=[];language=None
    if progress:progress.reset('Preparando transcripción por bloques cortos…',duration)
    with tempfile.TemporaryDirectory(prefix='voz-bloques-',dir=audio.parent) as temp:
        folder=Path(temp)
        for index in range(total):
            if cancel and cancel.is_set():raise ValueError('Operación cancelada.')
            left=index*seconds;right=min(duration,left+seconds)
            begin=max(0,left-.8);finish=min(duration,right+.8)
            with wave.open(str(audio),'rb') as reader:
                reader.setpos(int(begin*rate));samples=array.array('h',reader.readframes(int((finish-begin)*rate)))
            if progress:
                with progress.guard:progress.label=f'Transcribiendo bloque {index+1} de {total} · {left:.0f}–{right:.0f} s de audio'
            if speech_bounds(samples,rate,0,finish-begin) is not None:
                clip=folder/'bloque.wav';result=folder/'bloque.json'
                with wave.open(str(clip),'wb') as writer:
                    writer.setparams(params);writer.writeframes(samples.tobytes())
                raw=decode(clip,result,language)
                language=raw.get('result',{}).get('language') or language
                for cue in phrases(raw):
                    words=cue.get('words',[])
                    kept=[]
                    bounds=speech_bounds(samples,rate,cue['start'],min(finish-begin,cue['end']))
                    if bounds and cue.get('timing_estimated'):
                        words=timed_words(cue['text'],*bounds)
                    for word in words:
                        start=word['start']+begin;end=word['end']+begin
                        if not left<=(start+end)/2<right:continue
                        if bounds:
                            start=max(start,begin+bounds[0]);end=min(end,begin+bounds[1])
                        start=max(left,start);end=min(right,end)
                        if end-start<.015:continue
                        kept.append(dict(text=' '+word['text'],offsets={'from':round(start*1000),'to':round(end*1000)}))
                    if kept:
                        segments.append(dict(text=''.join(t['text'] for t in kept).strip(),tokens=kept,
                            offsets={'from':kept[0]['offsets']['from'],'to':kept[-1]['offsets']['to']}))
            if progress:progress.report((index+1)/total)
    value=dict(transcription=segments,result={'language':language},timing_source='dtw_and_audio_bounds')
    transcript.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    return value
