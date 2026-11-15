/* Dos intentos de vinculación y respuestas de ventanas cerradas. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const tick=()=>new Promise(resolve=>setImmediate(resolve));

async function main(){
  const nodes=new Map(),handlers={},popups=[];
  const node=id=>{if(!nodes.has(id))nodes.set(id,{value:id==='watermark-opacity'?'30':'',checked:false,textContent:'',style:{},classList:{toggle(){}},appendChild(){},setAttribute(){}});return nodes.get(id);};
  const tools={ffmpeg:true,ffprobe:true,'whisper-cli':true,'yt-dlp':true,modelo:true,logo:true,'runtime-youtube':true};
  const state={status:'Listo',source:false,busy:false,clips:[],trash:[],suggestions:[],storage:{used_gb:0,quota_gb:10,free_gb:100,max_clips:50},live:{running:false,status:'Detenida',processed:0,backlog:0}};
  const origin='http://127.0.0.1:8765';
  const context={location:{protocol:'https:',hostname:'julio-ejemplo.netlify.app',origin:'https://julio-ejemplo.netlify.app'},
    URL,Uint8Array,Promise,Object,Number,JSON,Error,crypto:require('node:crypto').webcrypto,
    setTimeout,clearTimeout,setInterval(){},
    document:{getElementById:node,querySelector:node,createElement:node,activeElement:null},
    fetch(){throw Error('La web remota no debe llamar directamente al servidor HTTP');},
    window:{addEventListener:(name,fn)=>{handlers[name]=fn;},open:(url,name)=>{
      const popup={url,name,closed:false,requests:[],close(){this.closed=true;},postMessage(data,target){
        assert.equal(target,origin);this.requests.push(data);
        queueMicrotask(()=>handlers.message({origin,source:popup,data:{type:'julio-response',challenge:data.challenge,id:data.id,data:state}}));
      }};popups.push(popup);return popup;
    }}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8'),context);
  node('link').onclick();node('link').onclick();
  assert.equal(popups[0].closed,true);
  assert.notEqual(popups[0].name,popups[1].name);
  const connect=popup=>handlers.message({origin,source:popup,data:{type:'julio-connected',challenge:new URL(popup.url).searchParams.get('challenge'),requirements:tools}});
  connect(popups[0]);await tick();
  assert.equal(popups[0].requests.length,0,'La ventana sustituida no recupera acceso');
  connect(popups[1]);await tick();
  assert.match(node('connection').textContent,/Equipo vinculado/);
  assert.equal(popups[1].requests.length,1);
  assert.equal(node('live-start').disabled,true);
  assert.match(node('live-state').textContent,/Actualiza Julio Clip/);
  state.live.clip_seconds=null;
  state.live.clips_per_block=null;
  connect(popups[1]);await tick();
  assert.equal(node('live-start').disabled,false);
  assert.equal(node('live-fast').disabled,true);
  assert.match(node('live-mode-hint').textContent,/Actualiza Julio Clip/);
  state.live.fast_mode=false;
  state.live.block_seconds=300;
  connect(popups[1]);await tick();
  assert.equal(node('live-fast').disabled,false);
  node('live-fast').checked=true;
  node('youtube').value='https://youtu.be/example';
  node('clip-duration').value='50';
  node('clips-per-block').value='4';
  node('live-start').onclick();await tick();await tick();
  const request=popups[1].requests.find(item=>item.method==='live-start');
  assert.equal(request.payload.clip_seconds,50);
  assert.equal(request.payload.clips_per_block,4);
  assert.equal(request.payload.fast_mode,true);
  const previousRequests=popups[1].requests.length;
  node('unlink').onclick();
  connect(popups[1]);await tick();
  assert.equal(node('connection').textContent,'● Sin vincular');
  assert.equal(popups[1].closed,true);
  assert.equal(popups[1].requests.length,previousRequests,'Un mensaje en cola de una ventana cerrada no reconecta');
  console.log('Web remota: ventana única, sustitución, recorrido de mensajes y desconexión comprobados en pruebas controladas.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
