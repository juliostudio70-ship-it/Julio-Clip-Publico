/* Respuestas tardías nunca deben reactivar una autorización revocada. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const tick = () => new Promise(resolve => setImmediate(resolve));
function harness() {
  const handlers={}, sent=[], pending=[];
  const nodes=Object.fromEntries(['approve','revoke','bridge-status','origin'].map(id=>[id,{}]));
  const origin='https://julio-ejemplo.netlify.app', challenge='a'.repeat(32);
  const remote={closed:false,postMessage:(data)=>sent.push(data)};
  const context={URL,URLSearchParams,Blob,Date,JSON,RegExp,Error,Object,Promise,
    location:{search:'?origin='+encodeURIComponent(origin)+'&challenge='+challenge},
    document:{getElementById:id=>nodes[id]},
    window:{opener:remote,addEventListener:(name,fn)=>{handlers[name]=fn;}},
    setInterval(){},fetch:()=>new Promise((resolve,reject)=>pending.push({resolve,reject}))};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/bridge.js'),'utf8'),context);
  const answer=(index,data={token:'LOCAL-SECRET',requirements:{ffmpeg:true}})=>pending[index].resolve({ok:true,json:async()=>data});
  const request=()=>handlers.message({origin,source:remote,data:{type:'julio-request',challenge,id:'b'.repeat(24),method:'state'}});
  return {nodes,sent,pending,answer,request,handlers};
}

async function main() {
  let h=harness();
  h.nodes.approve.onclick();
  h.nodes.revoke.onclick();
  h.answer(0); await tick();
  assert.equal(h.sent.filter(d=>d.type==='julio-connected').length,0);
  assert.match(h.nodes['bridge-status'].textContent,/revocada/);
  h.request(); await tick();
  assert.equal(h.pending.length,1,'Revocar durante la autorización impide llamadas posteriores');

  h=harness();
  h.nodes.approve.onclick(); // autorización vieja
  h.nodes.revoke.onclick();
  h.nodes.approve.onclick(); // nueva
  h.answer(1); await tick();
  h.pending[0].reject(Error('respuesta vieja')); await tick();
  assert.match(h.nodes['bridge-status'].textContent,/autorizada/);
  assert.equal(h.nodes.approve.disabled,true,'Un error viejo no cambia el control de una sesión nueva');
  h.request();
  h.nodes.revoke.onclick();
  h.nodes.approve.onclick();
  h.answer(3); await tick();
  h.answer(2,{status:'resultado anterior'}); await tick();
  assert.equal(h.sent.filter(d=>d.type==='julio-response').length,0,'Una tarea vieja no responde en otra autorización');

  h=harness();
  h.nodes.approve.onclick();
  h.handlers.beforeunload();
  h.answer(0); await tick();
  assert.equal(h.sent.filter(d=>d.type==='julio-connected').length,0);
  console.log('Puente: revocación durante autorización, errores tardíos, cambio de sesión y cierre comprobados.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
