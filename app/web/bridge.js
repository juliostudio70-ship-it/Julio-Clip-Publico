(function () {
  'use strict';
  var params = new URLSearchParams(location.search);
  var origin = params.get('origin'), challenge = params.get('challenge');
  var approved = false, token = '', expires = 0, generation = 0;
  var remote = window.opener;
  var status = document.getElementById('bridge-status');
  var approve = document.getElementById('approve');
  var inflight = Object.create(null);
  var valid = false;
  try { var u = new URL(origin); valid = u.protocol === 'https:' && u.origin === origin && /^[a-f0-9]{32}$/.test(challenge) && !!remote; } catch (e) {}
  document.getElementById('origin').textContent = valid ? origin : 'Solicitud de vinculación inválida.';
  approve.disabled = !valid;
  function send(data) { if (valid && remote && !remote.closed) remote.postMessage(data, origin); }
  function revoke() {
    generation += 1; approved = false; token = '';
    send({type: 'julio-disconnected', challenge: challenge});
    status.textContent = 'Conexión revocada. Las tareas ya iniciadas pueden seguir ejecutándose en el equipo.';
    approve.disabled = !valid;
  }
  document.getElementById('revoke').onclick = revoke;
  approve.onclick = function () {
    var attempt = ++generation;
    approve.disabled = true;
    fetch('/api/session').then(function (r) { if (!r.ok) throw Error(); return r.json(); }).then(function (session) {
      if (attempt !== generation) return;
      token = session.token; approved = true; expires = Date.now() + 12*60*60*1000;
      status.textContent = 'Conexión autorizada. Mantén esta ventana abierta. Puedes volver a tu página.';
      // El token local nunca se envía al origen remoto.
      send({type: 'julio-connected', challenge: challenge, requirements: session.requirements});
    }).catch(function () { if (attempt !== generation) return; status.textContent = 'No se pudo iniciar la sesión. Abre de nuevo el programa.'; approve.disabled = false; });
  };
  window.addEventListener('message', function (event) {
    if (!approved || Date.now() >= expires || event.origin !== origin || event.source !== remote) return;
    var d = event.data;
    if (!d || d.type !== 'julio-request' || d.challenge !== challenge || !/^[a-f0-9]{24}$/.test(d.id) || inflight[d.id]) return;
    var methods = ['state', 'diagnostics', 'youtube', 'analyze', 'export', 'edit', 'clip-info', 'upload', 'download', 'thumbnail', 'subtitles', 'trash', 'restore', 'empty-trash', 'storage', 'clear-source', 'clear-queue', 'live-start', 'live-stop', 'live-finish', 'published-cancel', 'kick-preview'];
    if (methods.indexOf(d.method) === -1) return;
    var path = '/api/' + d.method, options = {};
    var binary = {download:'/clips/', thumbnail:'/thumbs/', subtitles:'/subtitulos/'};
    if (binary[d.method]) {
      if (!d.payload || !/^clip-[a-f0-9]{12}\.mp4$/.test(d.payload.name)) return;
      path = binary[d.method] + d.payload.name;
    } else if (d.method !== 'state' && d.method !== 'diagnostics') {
      options = {method: 'POST', headers: {'X-Julio-Token': token, 'Content-Type': d.method === 'upload' ? 'application/octet-stream' : 'application/json'}, body: d.method === 'upload' ? d.payload : JSON.stringify(d.payload || {})};
      if (d.method === 'upload' && (!(d.payload instanceof Blob) || !d.payload.size || d.payload.size > 2*1024*1024*1024)) return;
    }
    inflight[d.id] = true;
    var requestGeneration = generation;
    fetch(path, options).then(function (r) {
      if (!r.ok) return r.json().then(function (err) { throw Error(err.error || 'La tarea falló.'); });
      return binary[d.method] || d.method === 'kick-preview' ? r.blob() : r.json();
    }).then(function (data) {
      if (approved && requestGeneration === generation && Date.now() < expires) send({type: 'julio-response', challenge: challenge, id: d.id, data: data});
    }).catch(function (e) {
      if (approved && requestGeneration === generation && Date.now() < expires) send({type: 'julio-response', challenge: challenge, id: d.id, error: e.message});
    }).then(function () { delete inflight[d.id]; });
  });
  window.addEventListener('beforeunload', function () { generation += 1; approved = false; token = ''; send({type: 'julio-disconnected', challenge: challenge}); });
  setInterval(function () { if (approved && Date.now() >= expires) revoke(); }, 1000);
}());
