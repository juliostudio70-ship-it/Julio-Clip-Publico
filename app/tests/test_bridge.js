/* Pruebas de aislamiento del puente sin depender de un servicio cloud. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

async function main() {
  const handlers = {}, sent = [], fetched = [];
  const nodes = Object.fromEntries(['approve','revoke','bridge-status','origin'].map(x => [x,{}]));
  const remote = {closed:false,postMessage:(d,origin)=>sent.push({d,origin})};
  const origin='https://julio-ejemplo.netlify.app',challenge='a'.repeat(32);
  const context = {
    URL,URLSearchParams,Blob,Date,JSON,RegExp,Error,Object,Promise,
    location:{search:'?origin='+encodeURIComponent(origin)+'&challenge='+challenge},
    document:{getElementById:id=>nodes[id]},
    window:{opener:remote,addEventListener:(name,fn)=>{handlers[name]=fn;}},
    setInterval:()=>0,
    fetch:async (url,options)=>{fetched.push({url,options});return {ok:true,json:async()=>url==='/api/session'?{token:'LOCAL-SECRET',requirements:{ffmpeg:true}}:{ok:true},blob:async()=>new Blob(['video'])};}
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/bridge.js'),'utf8'),context);
  const tick=()=>new Promise(resolve=>setImmediate(resolve));
  const message=(overrides={})=>handlers.message(Object.assign({origin,source:remote,data:{type:'julio-request',challenge,id:'b'.repeat(24),method:'state'}},overrides));
  message();await tick();assert.equal(fetched.length,0,'Sin autorización no hay llamadas');
  nodes.approve.onclick();await tick();
  assert.equal(sent[0].d.type,'julio-connected');
  assert.ok(!JSON.stringify(sent).includes('LOCAL-SECRET'),'No se comparte el token local');
  message({origin:'https://evil.example'});await tick();assert.equal(fetched.length,1);
  message({source:{}});await tick();assert.equal(fetched.length,1);
  message({data:{type:'julio-request',challenge:'wrong',id:'b'.repeat(24),method:'state'}});await tick();assert.equal(fetched.length,1);
  message({data:{type:'julio-request',challenge,id:'b'.repeat(24),method:'../server.py'}});await tick();assert.equal(fetched.length,1);
  message();await tick();assert.equal(fetched[1].url,'/api/state');
  message({data:{type:'julio-request',challenge,id:'c'.repeat(24),method:'export',payload:{start:0,end:5}}});await tick();
  assert.equal(fetched[2].options.headers['X-Julio-Token'],'LOCAL-SECRET');
  const name='clip-abcdef123456.mp4';
  message({data:{type:'julio-request',challenge,id:'d'.repeat(24),method:'clip-info',payload:{name}}});await tick();
  assert.equal(fetched[3].url,'/api/clip-info');
  assert.equal(fetched[3].options.headers['X-Julio-Token'],'LOCAL-SECRET');
  message({data:{type:'julio-request',challenge,id:'e'.repeat(24),method:'edit',payload:{name,start:0,end:5,subtitles:true}}});await tick();
  assert.equal(fetched[4].url,'/api/edit');
  assert.equal(JSON.parse(fetched[4].options.body).subtitles,true);
  assert.ok(sent.every(x=>x.origin===origin));
  nodes.revoke.onclick();message();await tick();assert.equal(fetched.length,5);
  assert.equal(sent.at(-1).d.type,'julio-disconnected');
  console.log('Puente: consentimiento, origen, ventana, reto, rutas, token, edición, subtítulos y revocación comprobados.');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
