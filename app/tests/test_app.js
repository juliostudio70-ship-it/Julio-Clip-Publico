/* Regresión del aviso real: conexión local no equivale a herramientas listas. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function main() {
  const nodes = new Map(), requests = [], handlers = {};
  const track = {cues:[],mode:'disabled',addCue(cue){this.cues.push(cue);},removeCue(cue){this.cues.splice(this.cues.indexOf(cue),1);}};
  const element = id => ({
    id,value:id==='watermark-opacity'?'30':'',checked:false,children:[],text:'',style:{},classList:{toggle(){}},
    get valueAsNumber(){return this.value===''?NaN:Number(this.value);},
    get textContent(){return this.text;},
    set textContent(value){this.text=value;this.children=[];},
    appendChild(child){this.children.push(child);child.parent=this;},disabled:false,focus(){},
    remove(){this.parent.children.splice(this.parent.children.indexOf(this),1);},
    pause(){},load(){},setAttribute(name,value){this[name]=value;},removeAttribute(name){delete this[name];},addTextTrack(){return track;}
  });
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, element(id));
    return nodes.get(id);
  };
  let tools = {ffmpeg:false,ffprobe:true,'whisper-cli':true,'yt-dlp':true,modelo:true,logo:true,'runtime-youtube':true};
  const source={name:'clip-111111111111.mp4',start:0,end:12,subtitles:true};
  const state = {status:'Listo',source:true,source_platform:null,source_duration:null,busy:false,clips:[source],edits:{},trash:[],suggestions:[],storage:{used_gb:0,quota_gb:10,free_gb:100,max_clips:50},live:{running:false,status:'Detenida',processed:0,backlog:0,clip_seconds:null,clips_per_block:null,fast_mode:false,block_seconds:300}};
  const context = {
    location:{protocol:'http:',hostname:'127.0.0.1'},URL,Uint8Array,Promise,Object,Number,JSON,Error,
    crypto:require('node:crypto').webcrypto,setTimeout,clearTimeout,setInterval(){},
    document:{getElementById:node,querySelector:node,createElement:element,activeElement:null},
    VTTCue:function(start,end,text){Object.assign(this,{start,end,text});},
    window:{addEventListener(name,fn){handlers[name]=fn;},scrollTo(){}},
    fetch:async (url,options)=>{
      requests.push({url,options});
      if(url==='/api/edit'){
        const payload=JSON.parse(options.body);
        const copy={name:'clip-222222222222.mp4',start:0,end:10,edited:true};
        state.clips.push(copy);state.edits[payload.id]={name:copy.name};
      }
      if(url==='/api/youtube'){state.source_platform='TikTok';state.source_duration=5.5;}
      const info={captions:[{start:1,end:3,text:'Ejemplo < & >'}]};
      return {ok:true,blob:async()=>new Blob(['video'],{type:'video/mp4'}),
        json:async()=>url==='/api/session'?{token:'secret',requirements:tools}:url==='/api/diagnostics'?{requirements:tools}:url==='/api/state'?structuredClone(state):url==='/api/clip-info'?info:{ok:true}};
    }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8'),context);
  const tick = () => new Promise(resolve => setImmediate(resolve));
  await tick();await tick();
  assert.match(node('connection').textContent,/Conexión local.*revisar herramientas/);
  assert.equal(node('live-start').disabled,true);
  assert.equal(node('export').disabled,true);
  assert.match(node('tools-state').textContent,/ffmpeg/);
  tools={...tools,ffmpeg:true};
  node('refresh-tools').onclick();await tick();await tick();
  assert.equal(node('live-start').disabled,false);
  assert.equal(node('export').disabled,false);
  assert.match(node('connection').textContent,/herramientas disponibles/);
  node('youtube').value='https://youtu.be/example';
  node('clip-duration').value='40';
  node('clips-per-block').value='10';
  node('live-subtitles').checked=true;
  assert.match(node('live-mode-hint').textContent,/5 minutos/);
  node('live-fast').checked=true;
  node('live-fast').onchange();
  assert.match(node('live-mode-hint').textContent,/1 minuto.*menos clips/);
  node('live-start').onclick();await tick();await tick();
  const start=requests.find(r=>r.url==='/api/live-start');
  assert.deepEqual(JSON.parse(start.options.body),{
    url:'https://youtu.be/example',clip_seconds:40,clips_per_block:10,watermark:true,watermark_opacity:0.3,subtitles:true,fast_mode:true
  });
  assert.equal(start.options.headers['X-Julio-Token'],'secret');
  assert.equal(context.location.hash,'#monitoreo');
  assert.equal(node('monitoreo').hidden,false);
  state.capabilities={kick:true,formats:true,profiles:true};
  node('refresh-tools').onclick();await tick();await tick();
  assert.equal(node('live-format-wrap').hidden,false);
  assert.equal(node('live-profile-wrap').hidden,false);
  node('live-profile').value='sports';
  assert.equal(node('kick-settings').hidden,true);
  node('youtube').value='https://kick.com/canal';
  node('youtube').oninput();
  assert.equal(node('kick-settings').hidden,false);
  node('kick-split').checked=true;node('kick-split').onchange();
  assert.equal(node('live-format').value,'vertical');
  assert.equal(node('live-format').disabled,true);
  node('live-start').onclick();await tick();await tick();
  const kick=requests.filter(r=>r.url==='/api/live-start').at(-1);
  assert.deepEqual(JSON.parse(kick.options.body).split,{camera:[72,68,28,32],game:[0,0,72,100]});
  assert.equal(JSON.parse(kick.options.body).profile,'sports');
  node('youtube').value='https://youtu.be/example';node('youtube').oninput();
  assert.equal(node('kick-settings').hidden,true);
  assert.equal(node('kick-split').checked,false);
  state.live.running=true;
  state.live.video_id='M7lc1UVf-VE';
  state.live.monitor={recorded_seconds:3671,elapsed_seconds:3690,recording:true,stage:'exporting',
    reviewed:3,highlights:2,rejected:1,generated:1,pending_clips:1,exporting:2,export_total:2,
    recent_rejections:[{start:0,end:30,reason:'Hay un salto en la señal.'}]};
  node('refresh-tools').onclick();await tick();await tick();
  assert.equal(node('metric-recorded').textContent,'01:01:11');
  assert.equal(node('stage-exporting-detail').textContent,'Clip 2 de 2 del bloque');
  assert.match(node('monitor-rejections').children[0].textContent,/salto/);
  const preview=node('monitor-player').children[0];
  assert.equal(preview.src,'https://www.youtube.com/embed/M7lc1UVf-VE?playsinline=1');
  assert.equal(preview.referrerpolicy,'strict-origin-when-cross-origin');
  node('refresh-tools').onclick();await tick();await tick();
  assert.equal(node('monitor-player').children[0],preview);
  assert.equal(node('published-workspace').hidden,true);
  context.location.hash='#publicados';handlers.hashchange();
  assert.equal(node('monitor-preview').hidden,true);
  assert.equal(node('monitor-player').children.length,0);
  state.live.running=false;
  assert.equal(node('published-workspace').hidden,false);
  assert.equal(node('live-workspace').hidden,true);
  assert.equal(node('published-export').hidden,false);
  assert.equal(node('nav-publicados')['aria-current'],'page');
  node('published-profile').value='sports';
  node('analyze').onclick();await tick();await tick();
  assert.equal(JSON.parse(requests.find(r=>r.url==='/api/analyze').options.body).profile,'sports');
  state.published_job={id:'job-1',status:'running',label:'Exportando el clip…',fraction:.25,
    elapsed_seconds:11,remaining_seconds:33};
  node('refresh-tools').onclick();await tick();await tick();
  assert.equal(node('published-progress').value,25);
  assert.match(node('published-eta').textContent,/00:00:33/);
  node('published-cancel').onclick();await tick();await tick();
  assert.deepEqual(JSON.parse(requests.find(r=>r.url==='/api/published-cancel').options.body),{id:'job-1'});
  state.published_job=null;
  node('published-url').value='https://www.tiktok.com/@cuenta/video/12345';
  node('load').onclick();await tick();await tick();
  const published=requests.find(r=>r.url==='/api/youtube');
  assert.equal(JSON.parse(published.options.body).url,node('published-url').value);
  assert.equal(node('end').value,5.5);
  assert.match(node('filename').textContent,/TikTok/);
  assert.equal(node('youtube').value,'https://youtu.be/example');
  node('start').value='0';node('end').value='181';node('export').onclick();
  assert.match(node('notice').textContent,/180 segundos/);
  assert.equal(requests.some(r=>r.url==='/api/export'),false);
  context.location.hash='#resultados';handlers.hashchange();
  const visual=node('clips').children[0];
  assert.equal(node('clips').className,'clip-gallery');
  assert.equal(visual.children[0].src,'/thumbs/'+source.name);
  assert.equal(visual.children[0].loading,'lazy');
  assert.equal(visual.children[1].children[0].className,'clip-title');
  assert.equal(visual.children[1].children[0].textContent.includes(source.name),false);
  assert.equal(node('resultados').hidden,false);
  assert.equal(node('creation-view').hidden,true);
  node('clips').children[0].children[1].children[3].children[0].onclick();
  await tick();await tick();
  const player=node('editor-video');
  player.duration=12;player.onloadedmetadata();
  assert.equal(track.mode,'showing');
  assert.equal(track.cues[0].text,'Ejemplo &lt; &amp; &gt;');
  player.currentTime=4;
  node('editor-add-cut').onclick();
  const cut=node('editor-cuts').children[0];
  player.currentTime=6;
  cut.children[1].children[1].onclick();
  assert.match(node('editor-length').textContent,/10.00 s/);
  node('editor-subtitles').checked=false;node('editor-subtitles').onchange();
  node('caption-corrections').children[0].children[0].value='Texto corregido';
  assert.equal(track.mode,'hidden');
  node('editor-save').onclick();await tick();await tick();
  const edit=JSON.parse(requests.find(r=>r.url==='/api/edit').options.body);
  assert.deepEqual(edit.remove,[{start:4,end:6}]);
  assert.equal(edit.name,source.name);
  assert.equal(edit.subtitles,false);
  assert.deepEqual(edit.caption_edits,['Texto corregido']);
  assert.match(node('editor-status').textContent,/Copia guardada/);
  assert.equal(node('editor-copy').hidden,false);
  node('editor-close').onclick();
  assert.equal(track.cues.length,0);
  assert.equal(node('clip-editor').hidden,true);
  state.capabilities={titles:true,face_tracking:true,formats:true};
  node('refresh-tools').onclick();await tick();await tick();
  node('live-subtitles').checked=true;node('live-burn').checked=true;
  node('caption-color').value='#ffffff';node('caption-accent').value='#a8e986';
  node('caption-size').value='medium';node('caption-position').value='center';
  node('caption-font').value='sans';node('caption-outline').value='0';node('caption-shadow').value='1';
  node('caption-animations').checked=true;
  assert.equal(node('caption-catalog').children.length,10);
  node('caption-catalog').children[5].onclick();
  node('live-start').onclick();await tick();await tick();
  const animated=JSON.parse(requests.filter(r=>r.url==='/api/live-start').at(-1).options.body);
  assert.deepEqual(animated.subtitle_style,{color:'#ffffff',size:'medium',position:'center',
    theme:'karaoke',font:'sans',accent:'#a8e986',animations:true,outline:0,shadow:1,reveal:'progressive',offset_ms:0});
  assert.equal(animated.burn_subtitles,true);
  assert.equal(node('license-badge').hidden,true);
  state.license={state:'active',days_remaining:3,price:'RD$800 por 30 días',whatsapp:'https://wa.me/18094063310'};
  node('refresh-tools').onclick();await tick();await tick();
  assert.match(node('license-badge').textContent,/Licencia activa.*3 días restantes/);
  assert.equal(node('license-renewal').hidden,false);
  assert.equal(node('license-panel').hidden,true);
  assert.equal(node('edition-label').textContent,'JULIO CLIP · EDICIÓN PÚBLICA');
  state.license.state='expired';
  node('refresh-tools').onclick();await tick();await tick();
  assert.equal(node('license-panel').hidden,false);
  assert.match(node('license-message').textContent,/tu suscripción.*ha vencido/i);
  assert.equal(node('license-whatsapp').href,state.license.whatsapp);
  console.log('Interfaz: diagnóstico, galería 9:16, subtítulos animados, corrección y guardado de una copia comprobados.');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
