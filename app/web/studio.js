(function(){
  'use strict';
  var $=function(id){return document.getElementById(id);},prefs=null,snapshot=null,initialized=false;
  var rejected=Object.create(null),accepted=Object.create(null),candidateKey='',maintenance=null,frame={x:.5,y:.5},drag=null;
  var prefKeys=['theme','accent','ui_scale','reduced_motion','performance','sensitivity','format','resolution','quality','fit','language','follow_face'];
  function text(id,value){$(id).textContent=value;}
  function api(method,payload){return window.Julio.transport(method,payload);}
  function report(error){text('notice',error.message||String(error));}
  function appearance(p){
    document.documentElement.classList.toggle('light-theme',p.theme==='light');
    document.documentElement.classList.toggle('dark-theme',p.theme==='dark');
    document.documentElement.classList.toggle('reduced-motion',p.reduced_motion);
    document.documentElement.style.setProperty('--lime',p.theme==='light'&&p.accent.toLowerCase()==='#d7a4a6'?'#87565f':p.accent);
    document.body.style.fontSize=(15*p.ui_scale/100)+'px';
  }
  function loadPrefs(p){
    prefs=p;appearance(p);
    prefKeys.forEach(function(key){var node=$('pref-'+key);if(typeof p[key]==='boolean')node.checked=p[key];else node.value=String(p[key]);});
    ['live-format','published-format'].forEach(function(id){$(id).value=p.format;});
    $('design-face').checked=p.follow_face&&p.format==='vertical';
    if(p.clip_seconds)$('clip-duration').value=String(p.clip_seconds);
    if(p.clip_count)$('clips-per-block').value=String(p.clip_count);
    $('published-duration').value=String(p.clip_seconds||30);$('design-fit').value=p.fit||'auto';
    if(window.Julio.setCaption&&p.subtitle_style)window.Julio.setCaption(p.subtitle_style);
  }
  $('preferences-form').onsubmit=function(event){
    event.preventDefault();var data={};
    prefKeys.forEach(function(key){var node=$('pref-'+key);data[key]=node.type==='checkbox'?node.checked:['ui_scale','resolution'].indexOf(key)!==-1?Number(node.value):node.value;});
    data.clip_seconds=Number($('clip-duration').value);data.clip_count=Number($('clips-per-block').value);
    if(window.Julio.caption)data.subtitle_style=window.Julio.caption();
    api('preferences',data).then(function(p){loadPrefs(p);text('preferences-message','Configuración guardada para los próximos trabajos.');}).catch(function(e){text('preferences-message',e.message);});
  };
  function openImported(){
    if(!snapshot||!snapshot.source){location.hash='#publicados';report(Error('Primero importa un video o elige un clip en la biblioteca.'));return;}
    location.hash='#resultados';window.Julio.openEditor({name:'imported.video',title:'Video importado',subtitles:false});
  }
  $('home-editor').onclick=openImported;$('edit-imported').onclick=openImported;
  document.querySelectorAll('[data-source]').forEach(function(button){button.onclick=function(){
    location.hash='#estudio';var source=button.dataset.source;
    $('youtube').placeholder=source==='kick'?'https://kick.com/tu-canal':source==='twitch'?'https://www.twitch.tv/tu-canal':'https://www.youtube.com/live/...';$('youtube').focus();
  };});
  ['library-search','library-order','library-category'].forEach(function(id){$(id).oninput=function(){window.Julio.refresh();};});
  function matchKey(c){return c.start.toFixed(3)+':'+c.end.toFixed(3);}
  function render(s){
    snapshot=s;if(!brandId&&s.branding&&s.branding.length){brandId=s.branding[0];text('brand-status','PNG transparente disponible. Activa Usar mi marca para aplicarlo.');}
    if(s.preferences&&!initialized){loadPrefs(s.preferences);initialized=true;}
    var m=s.dashboard||{};
    [['month','clips_month'],['jobs','jobs_running'],['analyzed','videos_analyzed'],['finished','clips_finished'],['score','best_interest']].forEach(function(pair){text('home-'+pair[0],m[pair[1]]===null||m[pair[1]]===undefined?'—':String(m[pair[1]])+(pair[0]==='score'?'/100':''));});
    $('home-chart').textContent='';var max=Math.max.apply(null,(m.days||[]).map(function(d){return d.count;}).concat([1]));
    (m.days||[]).forEach(function(day){var col=document.createElement('div'),n=document.createElement('span'),bar=document.createElement('div'),label=document.createElement('span');
      col.className='chart-column';n.textContent=day.count;bar.className='chart-bar';bar.style.height=(day.count/max*105)+'px';label.textContent=day.label;
      col.appendChild(n);col.appendChild(bar);col.appendChild(label);$('home-chart').appendChild(col);
    });
    var recent=s.clips.slice().sort(function(a,b){return (b.created||0)-(a.created||0);}).slice(0,3),recentKey=JSON.stringify(recent);
    if($('home-recent').dataset.key!==recentKey){$('home-recent').dataset.key=recentKey;$('home-recent').textContent='';
      recent.forEach(function(c){var button=document.createElement('button'),img=document.createElement('img'),p=document.createElement('p');
        img.src='/thumbs/'+c.name;img.alt=c.title||'Miniatura del clip';img.loading='lazy';p.textContent=c.title||'Abrir clip';
        button.appendChild(img);button.appendChild(p);button.onclick=function(){location.hash='#resultados';window.Julio.openEditor(c);};$('home-recent').appendChild(button);
      });
      if(!recent.length)text('home-recent','Aún no hay clips guardados.');
    }
    text('settings-storage',s.storage.used_gb+' GB usados · '+s.storage.free_gb+' GB libres · límite '+s.storage.quota_gb+' GB');
    if(s.storage.breakdown){$('storage-breakdown').textContent='';Object.keys(s.storage.breakdown).forEach(function(key){var span=document.createElement('span');span.textContent=key+': '+(s.storage.breakdown[key]/1024/1024).toFixed(1)+' MB';$('storage-breakdown').appendChild(span);});}
    $('edit-imported').disabled=!s.source||s.busy;
    var newKey=JSON.stringify([s.source_revision,s.suggestions.map(matchKey)]);
    if(newKey!==candidateKey){candidateKey=newKey;rejected=Object.create(null);accepted=Object.create(null);}
    text('batch-feedback',Object.keys(accepted).length+' candidatos aceptados. Usa «Aceptar» en cada propuesta.');
    $('batch-export').disabled=s.busy||!Object.keys(accepted).length;
    $('accept-all').disabled=s.busy||!s.suggestions.length;
    $('published-rejections-list').textContent='';(s.rejections||[]).forEach(function(r){var li=document.createElement('li');li.textContent=r.start.toFixed(1)+'–'+r.end.toFixed(1)+' s · '+r.reason;$('published-rejections-list').appendChild(li);});
    if(s.license){text('settings-license','Estado: '+s.license.state+' · '+s.license.days_remaining+' días restantes'+(s.license.expires_at?' · vence '+new Date(s.license.expires_at).toLocaleString('es'):''));$('settings-license-panel').hidden=false;}
  }
  var brandId=null;
  function brandOptions(d,editor){
    if(brandId&&(editor?$('editor-brand').checked:$('brand-enable').checked)){
      d.custom_watermark=brandId;d.watermark=editor?true:d.watermark!==false;
      d.watermark_position=$('brand-position').value;d.watermark_scale=Number($('brand-scale').value)/100;
      d.watermark_opacity=Number($('watermark-opacity').value)/100;
    }
  }
  $('brand-file').onchange=async function(){
    var file=this.files&&this.files[0];if(!file)return;
    if(file.size>8*1024*1024){text('brand-status','Usa un PNG de hasta 8 MB.');return;}
    text('brand-status','Comprobando transparencia…');
    try{var result=await api('watermark',file);brandId=result.id;$('brand-enable').checked=true;text('brand-status',result.message);}
    catch(e){text('brand-status',e.message);}
  };
  function style(d,prefix){
    if(!snapshot||!snapshot.capabilities||!snapshot.capabilities.studio)return;
    brandOptions(d,prefix==='editor');
    d.resolution=prefs?prefs.resolution:720;d.quality=prefs?prefs.quality:'balanced';d.fit=$('design-fit').value||'auto';
    if(prefix==='editor'){
      ['resolution','speed','volume','zoom'].forEach(function(k){d[k]=Number($('editor-'+k).value);});
      d.quality=$('editor-quality').value;d.fit=$('editor-fit').value;d.effect=$('editor-effect').value;
      d.fade=$('editor-fade').checked;d.frame_x=frame.x;d.frame_y=frame.y;d.music=$('editor-music').checked;
      if($('editor-cover').value!=='')d.cover_time=Number($('editor-cover').value);
    }
  }
  function filter(clips){
    var search=$('library-search').value.trim().toLocaleLowerCase('es'),category=$('library-category').value;
    var list=clips.filter(function(c){return (!search||(c.title||'').toLocaleLowerCase('es').indexOf(search)!==-1)&&(category==='all'||(c.category||'general')===category);});
    if($('library-order').value==='interest')list.sort(function(a,b){return (b.interest||0)-(a.interest||0);});
    return list;
  }
  function editorOpen(clip){
    var values=clip.render_options||{};frame={x:.5,y:.5};
    ['resolution','quality','fit'].forEach(function(k){$('editor-'+k).value=String(prefs&&prefs[k]!==undefined?prefs[k]:k==='resolution'?720:k==='quality'?'balanced':'auto');});
    $('editor-brand').checked=false;$('editor-speed').value='1';$('editor-volume').value='1';$('editor-zoom').value='1';$('editor-effect').value='none';$('editor-fade').checked=false;
    $('editor-music').checked=false;$('editor-cover').value='';$('editor-rendered').pause();$('editor-rendered').removeAttribute('src');$('editor-rendered').hidden=true;
  }
  var video=$('editor-video');
  video.addEventListener('timeupdate',function(){var d=Number.isFinite(video.duration)?video.duration:1;$('editor-timeline').max=String(d);$('editor-timeline').value=String(video.currentTime);text('timeline-position',Math.floor(video.currentTime/60)+':'+('0'+Math.floor(video.currentTime%60)).slice(-2));});
  $('editor-timeline').oninput=function(){video.currentTime=Number(this.value);};
  $('editor-split').onclick=function(){$('editor-add-cut').onclick();};
  $('editor-preview-button').onclick=function(){window.Julio.preview();};
  video.addEventListener('pointerdown',function(e){if($('editor-fit').value!=='crop')return;drag={x:e.clientX,y:e.clientY,fx:frame.x,fy:frame.y,id:e.pointerId};video.setPointerCapture(e.pointerId);});
  video.addEventListener('pointermove',function(e){if(!drag||drag.id!==e.pointerId)return;var box=video.getBoundingClientRect();frame.x=Math.max(0,Math.min(1,drag.fx-(e.clientX-drag.x)/box.width));frame.y=Math.max(0,Math.min(1,drag.fy-(e.clientY-drag.y)/box.height));text('editor-status','Encuadre manual '+Math.round(frame.x*100)+' % / '+Math.round(frame.y*100)+' %. Renderiza la vista previa para comprobarlo.');});
  video.addEventListener('pointerup',function(){drag=null;});
  function drawCrop(){
    var box=$('editor-crop-box');box.hidden=$('editor-fit').value!=='crop';
    if(box.hidden||!video.videoWidth)return;
    var rect=video.getBoundingClientRect(),parent=video.parentElement.getBoundingClientRect();
    var ratio={vertical:9/16,landscape:16/9,square:1}[$('editor-format').value]||video.videoWidth/video.videoHeight;
    var sw=video.videoWidth,sh=video.videoHeight,cw=Math.min(sw,sh*ratio),ch=cw/ratio,z=Number($('editor-zoom').value)||1;
    cw/=z;ch/=z;
    box.style.left=(rect.left-parent.left+(sw-cw)/sw*rect.width*frame.x)+'px';
    box.style.top=(rect.top-parent.top+(sh-ch)/sh*rect.height*frame.y)+'px';
    box.style.width=(cw/sw*rect.width)+'px';box.style.height=(ch/sh*rect.height)+'px';
  }
  var cropDrag=null;
  $('editor-crop-box').onpointerdown=function(e){cropDrag={id:e.pointerId,x:e.clientX,y:e.clientY,fx:frame.x,fy:frame.y,zoom:Number($('editor-zoom').value),resize:e.target===$('editor-crop-handle')};this.setPointerCapture(e.pointerId);e.preventDefault();};
  $('editor-crop-box').onpointermove=function(e){if(!cropDrag||cropDrag.id!==e.pointerId)return;var rect=video.getBoundingClientRect();
    if(cropDrag.resize)$('editor-zoom').value=String(Math.min(3,Math.max(1,cropDrag.zoom-(e.clientX-cropDrag.x)/rect.width*3)));
    else{frame.x=Math.max(0,Math.min(1,cropDrag.fx+(e.clientX-cropDrag.x)/rect.width));frame.y=Math.max(0,Math.min(1,cropDrag.fy+(e.clientY-cropDrag.y)/rect.height));}
    drawCrop();
  };
  $('editor-crop-box').onpointerup=function(){cropDrag=null;};
  ['editor-fit','editor-format','editor-zoom'].forEach(function(id){$(id).addEventListener('input',drawCrop);});
  video.addEventListener('loadedmetadata',drawCrop);window.addEventListener('resize',drawCrop);
  $('editor-music-file').onchange=function(){var file=this.files[0];if(!file)return;
    if(file.size>100*1024*1024){report(Error('Música de hasta 100 MB.'));return;}
    fetch('/api/session').then(function(r){return r.json();}).then(function(session){return fetch('/api/music',{method:'POST',headers:{'X-Julio-Token':session.token,'Content-Type':'application/octet-stream'},body:file});}).then(function(r){return r.json().then(function(data){if(!r.ok)throw Error(data.error);return data;});}).then(function(data){$('editor-music').checked=true;text('editor-status',data.message);}).catch(report);
  };
  function reviewMaintenance(temporary){
    api('maintenance-plan',{temporary_only:temporary}).then(function(plan){maintenance={plan:plan,temporary:temporary};$('maintenance-review').hidden=false;$('maintenance-files').textContent='';
      plan.files.forEach(function(file){var li=document.createElement('li');li.textContent=file.path+' ('+(file.bytes/1024/1024).toFixed(2)+' MB)';$('maintenance-files').appendChild(li);});
      if(!plan.files.length){var li=document.createElement('li');li.textContent='No hay archivos que borrar.';$('maintenance-files').appendChild(li);}
      text('maintenance-label','Para confirmar escribe: '+(temporary?'LIMPIAR TEMPORALES':'RESTABLECER JULIO CLIP'));
      $('maintenance-confirm').value='';text('maintenance-message','Revisa la lista completa. La eliminación no se puede deshacer.');
    }).catch(function(e){text('maintenance-message',e.message);});
  }
  $('clean-temporary').onclick=function(){reviewMaintenance(true);};$('reset-platform').onclick=function(){reviewMaintenance(false);};
  $('maintenance-cancel').onclick=function(){maintenance=null;$('maintenance-review').hidden=true;};
  $('maintenance-execute').onclick=function(){if(!maintenance)return;api('maintenance-clear',{temporary_only:maintenance.temporary,confirmation:maintenance.plan.confirmation,phrase:$('maintenance-confirm').value}).then(function(result){text('maintenance-message',result.message);$('maintenance-review').hidden=true;maintenance=null;initialized=false;window.Julio.refresh();}).catch(function(e){text('maintenance-message',e.message);});};
  $('accept-all').onclick=function(){if(!snapshot)return;snapshot.suggestions.forEach(function(c){if(!rejected[matchKey(c)])accepted[matchKey(c)]=true;});window.Julio.refresh();};
  $('batch-export').onclick=function(){if(!snapshot)return;var indices=[];snapshot.suggestions.forEach(function(c,i){if(accepted[matchKey(c)]&&!rejected[matchKey(c)])indices.push(i);});
    var payload=window.Julio.publishedPayload();payload.indices=indices;window.Julio.act('batch-export',payload);
  };
  $('editor-project-save').onclick=function(){var draft=window.Julio.editorPayload();if(!draft)return;api('project-save',draft).then(function(result){text('editor-status',result.message);}).catch(report);};
  function restoreProject(draft){
    ['resolution','quality','fit','speed','volume','zoom','effect'].forEach(function(k){if(draft[k]!==undefined)$('editor-'+k).value=String(draft[k]);});
    $('editor-format').value=draft.format||'original';$('editor-subtitles').checked=draft.subtitles===true;$('editor-burn').checked=draft.burn_subtitles===true;
    $('editor-face').checked=draft.follow_face===true;$('editor-fade').checked=draft.fade===true;$('editor-music').checked=draft.music===true;
    if(draft.overlay_title){$('editor-title').value=draft.overlay_title.text;['color','position','size','style','duration'].forEach(function(k){$('editor-'+k).value=draft.overlay_title[k];});}
    if(draft.cover_time!==undefined)$('editor-cover').value=draft.cover_time;frame={x:draft.frame_x===undefined?.5:draft.frame_x,y:draft.frame_y===undefined?.5:draft.frame_y};
    if(draft.subtitle_style)window.Julio.setEditorCaption(draft.subtitle_style);
    $('editor-subtitles').onchange();
  }
  var downloadFolder=null;
  function folderDB(){return new Promise(function(resolve,reject){var request=indexedDB.open('JulioClipLocalSettings',1);request.onupgradeneeded=function(){request.result.createObjectStore('settings');};request.onsuccess=function(){resolve(request.result);};request.onerror=function(){reject(request.error);};});}
  async function rememberFolder(handle){var db=await folderDB();await new Promise(function(resolve,reject){var transaction=db.transaction('settings','readwrite');if(handle)transaction.objectStore('settings').put(handle,'downloadFolder');else transaction.objectStore('settings').delete('downloadFolder');transaction.oncomplete=resolve;transaction.onerror=function(){reject(transaction.error);};});db.close();}
  folderDB().then(function(db){var request=db.transaction('settings').objectStore('settings').get('downloadFolder');request.onsuccess=function(){downloadFolder=request.result||null;if(downloadFolder)text('download-folder-state','Carpeta elegida: '+downloadFolder.name+'.');db.close();};}).catch(function(){});
  $('select-download-folder').onclick=async function(){if(!window.showDirectoryPicker){text('download-folder-state','Este navegador no permite elegir una carpeta desde la página. Cambia Descargas en sus ajustes; los botones de descarga siguen disponibles.');return;}try{downloadFolder=await window.showDirectoryPicker({mode:'readwrite'});await rememberFolder(downloadFolder);text('download-folder-state','Carpeta elegida: '+downloadFolder.name+'.');}catch(e){if(e.name!=='AbortError')text('download-folder-state','No se pudo guardar la carpeta; usa los ajustes del navegador.');}};
  $('clear-download-folder').onclick=function(){downloadFolder=null;rememberFolder(null).catch(function(){});text('download-folder-state','Se usa la carpeta configurada en tu navegador.');};
  async function saveDownload(blob,name){
    if(!downloadFolder)throw Error('Elige una carpeta de descargas.');
    if(await downloadFolder.queryPermission({mode:'readwrite'})!=='granted'&&await downloadFolder.requestPermission({mode:'readwrite'})!=='granted')throw Error('No se autorizó la carpeta. Puedes volver a usar la carpeta del navegador.');
    var extension=name.slice(name.lastIndexOf('.')),stem=name.slice(0,name.lastIndexOf('.')),candidate=name,index=1;
    while(true){try{await downloadFolder.getFileHandle(candidate);candidate=stem+'-'+index++ +extension;}catch(e){if(e.name==='NotFoundError')break;throw e;}}
    var file=await downloadFolder.getFileHandle(candidate,{create:true}),stream=await file.createWritable();try{await stream.write(blob);await stream.close();}catch(e){await stream.abort();throw e;}
    text('notice','Descarga guardada en '+downloadFolder.name+': '+candidate+'.');
  }
  window.JulioStudio={hasDownloadFolder:function(){return Boolean(downloadFolder);},saveDownload:saveDownload,restoreProject:restoreProject,render:render,style:style,filter:filter,openEditor:editorOpen,interestOrder:function(){return $('library-order').value==='interest';},
    reject:function(c){rejected[matchKey(c)]=true;delete accepted[matchKey(c)];},
    isRejected:function(c){return Boolean(rejected[matchKey(c)]);},accept:function(c){accepted[matchKey(c)]=true;window.Julio.refresh();}};
  window.Julio.refresh();
}());
