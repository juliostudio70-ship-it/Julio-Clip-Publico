(function () {
  'use strict';
  var local=location.protocol==='http:' && location.hostname==='127.0.0.1';
  var token='',pending=0,linked=false,bridge=null,challenge='',calls=Object.create(null),localOrigin='http://127.0.0.1:8765';
  var dependencies={},diagnosed=false,lastState=null;
  var desktop=false,publicEdition=false,macDesktop=false;
  var editor=null,editorTrack=null,clipListKey=null,refreshing=false,monitorRejectionKey=null,monitorClipKey=null;
  var thumbnails=Object.create(null);
  var kickRegions={camera:[72,68,28,32],game:[0,0,72,100]},gameEdited=false;
  var kickPreviewUrl='',kickPreviewPending=false,kickDrag=null;
  var coordinateIds=['kick-x','kick-y','kick-w','kick-h'];
  var $=function(id){return document.getElementById(id);};
  var views=['inicio','estudio','monitoreo','publicados','resultados','diagnostico','configuracion','tutorial'];
  var currentView='inicio';
  var titleKeys=['color','position','size','style','duration'];
  var playerVideoId='';
  function showView(){
    var hash=(location.hash||'').slice(1);
    var view=views.indexOf(hash)===-1?'inicio':hash;
    currentView=view;
    var live=view==='estudio',published=view==='publicados',library=view==='resultados';
    $('live-intro').hidden=!live;
    $('publicados').hidden=!published;
    $('monitoreo').hidden=view!=='monitoreo';
    $('creation-view').hidden=!(live||published);
    $('live-workspace').hidden=!live;
    ['published-workspace','published-times','published-export','published-suggestions'].forEach(function(id){$(id).hidden=!published;});
    $('options-title').textContent=published?'Define tu fragmento':'Marca de agua del directo';
    $('resultados').hidden=!library;
    $('library-storage').hidden=!library||publicEdition;
    $('diagnostico').hidden=view!=='diagnostico';
    ['inicio','configuracion','tutorial'].forEach(function(id){$(id).hidden=view!==id;});
    views.forEach(function(id){
      var link=$('nav-'+id);
      link.classList.toggle('active',id===view);
      link.setAttribute('aria-current',id===view?'page':'false');
    });
    refreshDesign();
    if(lastState)renderLivePreview(lastState.live);
  }
  window.addEventListener('hashchange',function(){showView();window.scrollTo(0,0);});
  showView();
  function note(t){$('notice').textContent=t;}
  function renderLicense(license){
    var active=Boolean(license&&license.state==='active');
    var blocked=Boolean(license&&!active);
    $('estudio').classList.toggle('license-blocked',blocked);
    $('license-badge').hidden=!license;
    $('license-panel').hidden=!blocked;
    $('license-renewal').hidden=!active||license.days_remaining>5;
    if(!license)return;
    if(document.title!=='Julio Clip Público'){
      document.title='Julio Clip Público';
      $('edition-label').textContent='JULIO CLIP · EDICIÓN PÚBLICA';
    }
    var days=license.days_remaining;
    var duration=days+(days===1?' día restante':' días restantes');
    $('license-badge').textContent=active?'Licencia activa — '+duration:
      license.state==='expired'?'Licencia vencida':license.state==='revoked'?'Licencia revocada':
      license.state==='offline'?'Verificación pendiente':'Licencia sin activar';
    $('license-renewal-text').textContent=active?'Te quedan '+duration+'.':'';
    ['license-whatsapp','license-reminder-link'].forEach(function(id){
      $(id).hidden=!license.whatsapp;
      if(license.whatsapp)$(id).href=license.whatsapp;
      else $(id).removeAttribute('href');
    });
    $('license-price').textContent=license.price||'';
    $('license-message').textContent=license.state==='expired'?
      'Tu suscripción de Julio Clip ha vencido. Para renovar otros 30 días, comunícate con el administrador por WhatsApp.':
      license.state==='revoked'?'Tu licencia fue revocada. Comunícate con el administrador.':
      license.state==='offline'?'Conecta esta PC a internet para verificar la licencia.':
      'Introduce el código que te entregó el administrador. Tus 30 días empiezan al activarlo.';
    if(blocked&&editor)closeEditor();
  }
  $('license-form').onsubmit=function(event){
    event.preventDefault();
    var code=$('license-code').value.trim();
    if(!code)return;
    $('license-activate').disabled=true;
    $('license-feedback').textContent='Verificando el código…';
    transport('license/activate',{code:code,device_alias:$('license-device').value.trim()}).then(function(result){
      $('license-code').value='';
      $('license-feedback').textContent=result.message;
      refresh();
    }).catch(function(error){
      $('license-feedback').textContent=error.message;
    }).then(function(){$('license-activate').disabled=false;});
  };
  function random(n){var a=new Uint8Array(n);crypto.getRandomValues(a);return Array.prototype.map.call(a,function(x){return ('0'+x.toString(16)).slice(-2);}).join('');}
  function available(){return local||linked;}
  function has(names){return !available() || (diagnosed&&names.every(function(name){return dependencies[name];}));}
  function ready(){return diagnosed&&Object.keys(dependencies).length>0&&Object.keys(dependencies).every(function(name){return dependencies[name];});}
  function supportsClipSettings(){return lastState&&Object.prototype.hasOwnProperty.call(lastState.live,'clip_seconds');}
  function supportsFastMode(){return lastState&&typeof lastState.live.fast_mode==='boolean';}
  function supportsEditor(){return !publicEdition&&lastState&&Object.prototype.hasOwnProperty.call(lastState,'edits');}
  function feature(name){return Boolean(lastState&&lastState.capabilities&&lastState.capabilities[name]);}
  function titleSettings(prefix){
    var title={text:$(prefix+'-title').value.trim()};
    titleKeys.forEach(function(key){var value=$(prefix+'-'+key).value;if(value)title[key]=value;});
    return title;
  }
  function titleSample(prefix){
    var title=titleSettings(prefix), preview=$(prefix+'-title-preview');
    preview.hidden=!feature('titles')||!title.text;
    preview.textContent=title.text;
    preview.style.color=title.color||'#ffffff';
    ['position','size','style'].forEach(function(key){preview.setAttribute('data-'+key,title[key]||'');});
  }
  function refreshDesign(){
    var live=currentView==='estudio',format=$(live?'live-format':'published-format').value||'original';
    var split=live&&isKick()&&$('kick-split').checked;
    var locked=Boolean(pending||(lastState&&(live?lastState.live.running:lastState.busy)));
    $('design-options').hidden=!(feature('face_tracking')||feature('titles'));
    $('design-face-wrap').hidden=!feature('face_tracking');
    $('design-face-hint').hidden=!feature('face_tracking');
    $('design-face-hint').textContent=split?'El seguimiento se usa con un solo encuadre.':
      format==='vertical'?'Si hay varias caras, el recorte intenta seguir a quien habla.':
      'Selecciona Vertical 9:16 para activar el seguimiento.';
    $('design-face').disabled=locked||format!=='vertical'||split;
    $('design-title-tools').hidden=!feature('titles');
    $('design-title-tools').disabled=locked;
    $('editor-design').hidden=!(feature('formats')||feature('titles'));
    $('editor-title-tools').hidden=!feature('titles');
    $('editor-face-wrap').hidden=!feature('face_tracking');
    $('editor-face').disabled=$('editor-format').value!=='vertical';
    ['live','export','editor'].forEach(function(prefix){
      $(prefix+'-burn-wrap').hidden=!feature('titles')||!$(prefix+'-subtitles').checked;
    });
    $('live-burn').disabled=Boolean(pending||(lastState&&lastState.live.running));
    $('export-burn').disabled=Boolean(pending||(lastState&&lastState.busy));
    var subtitlePrefix=live?'live':'export';
    $('caption-tools').hidden=!feature('titles')||!$(subtitlePrefix+'-subtitles').checked||!$(subtitlePrefix+'-burn').checked;
    $('caption-tools').disabled=locked;
    $('edit-caption-tools').hidden=!feature('titles')||!$('editor-subtitles').checked||!$('editor-burn').checked;
    titleSample('design');
    titleSample('editor');
  }
  function addStyling(d,prefix){
    if(feature('face_tracking')&&d.format==='vertical'&&!d.split&&$(prefix+'-face').checked)d.follow_face=true;
    if(feature('titles')){
      var title=titleSettings(prefix);
      if(title.text)d.overlay_title=title;
    }
    if(window.JulioStudio)window.JulioStudio.style(d,prefix);
    return d;
  }
  function applySubtitles(payload,context){
    if(!payload.subtitles||!feature('titles')||!$(context+'-burn').checked)return;
    var prefix=context==='editor'?'edit-caption':'caption';
    payload.burn_subtitles=true;
    payload.subtitle_style=captionSettings(prefix);
  }
  var captionThemes=[['classic','Clásico','CC'],['dynamic','Dinámico','Aa'],['word','Palabra por palabra','1·2'],
    ['bounce','Rebote','↟'],['zoom','Zoom','⊕'],['karaoke','Karaoke','♫'],['minimal','Minimalista','—'],['impact','Impacto','!'],['slide','Deslizar','↗'],['build','Construcción','▰']];
  function captionSettings(prefix){
    return {color:$(prefix+'-color').value||'#ffffff',size:$(prefix+'-size').value||'medium',
      position:$(prefix+'-position').value||'bottom',theme:$(prefix+'-catalog').selectedTheme||'classic',
      font:$(prefix+'-font').value||'barlow',accent:$(prefix+'-accent').value||'#a8e986',
      animations:$(prefix+'-animations').checked,outline:Number($(prefix+'-outline').value||2),
      shadow:Number($(prefix+'-shadow').value||1),reveal:$(prefix+'-reveal').value||'progressive',offset_ms:Number($(prefix+'-offset').value||0)};
  }
  function captionDemo(prefix){
    var style=captionSettings(prefix),demo=$(prefix+'-demo');
    demo.setAttribute('data-theme',style.theme);demo.setAttribute('data-animated',String(style.animations));
    demo.setAttribute('data-position',style.position);demo.setAttribute('data-size',style.size);
    demo.style.color=style.color;
    demo.style.fontFamily={barlow:'"Barlow Condensed", sans-serif',sans:'Arial, sans-serif',serif:'Georgia, serif'}[style.font];
    demo.textContent='';
    ['Este','momento','lo','cambia','todo'].forEach(function(word,index){
      var span=document.createElement('span');span.textContent=word+' ';span.style.animationDelay=(index*.32)+'s';
      span.style.textShadow='0 1px '+style.shadow+'px #000';
      span.style.webkitTextStroke=(style.theme==='minimal'?0:style.outline*.3)+'px #151a21';
      span.style.setProperty&&span.style.setProperty('--caption-accent',style.accent);
      demo.appendChild(span);
    });
  }
  ['caption','edit-caption'].forEach(function(prefix){
    var catalog=$(prefix+'-catalog');catalog.selectedTheme='classic';
    captionThemes.forEach(function(theme){
      var card=document.createElement('button');card.type='button';card.className='caption-card';
      card.setAttribute('data-theme',theme[0]);
      card.setAttribute('aria-pressed',String(theme[0]==='classic'));
      var icon=document.createElement('span');icon.className='caption-icon';icon.textContent=theme[2];icon.setAttribute('aria-hidden','true');
      var name=document.createElement('strong');name.textContent=theme[1];
      var example=document.createElement('small');
      ['Cada ','momento ','cuenta'].forEach(function(word){var piece=document.createElement('span');piece.textContent=word;example.appendChild(piece);});
      card.appendChild(icon);card.appendChild(name);card.appendChild(example);
      card.onclick=function(){
        catalog.selectedTheme=theme[0];
        Array.prototype.forEach.call(catalog.children,function(item){item.setAttribute('aria-pressed',String(item===card));});
        captionDemo(prefix);
      };
      catalog.appendChild(card);
    });
    ['color','size','position','font','accent','outline','shadow','animations','reveal','offset'].forEach(function(key){
      $(prefix+'-'+key).oninput=function(){captionDemo(prefix);};
    });
    captionDemo(prefix);
  });
  ['design','editor'].forEach(function(prefix){
    ['title'].concat(titleKeys).forEach(function(key){
      $(prefix+'-'+key).oninput=function(){titleSample(prefix);};
    });
  });
  ['live-format','published-format','editor-format'].forEach(function(id){$(id).onchange=refreshDesign;});
  $('live-subtitles').onchange=refreshDesign;
  $('export-subtitles').onchange=refreshDesign;
  ['live','export','editor'].forEach(function(context){$(context+'-burn').onchange=refreshDesign;});
  function isKick(){
    if(!feature('kick'))return false;
    try{
      var url=new URL($('youtube').value.trim());
      return url.protocol==='https:'&&['kick.com','www.kick.com'].indexOf(url.hostname)>=0;
    }catch(e){return false;}
  }
  function layoutControls(liveLocked,publishedLocked){
    var kick=isKick(),split=kick&&$('kick-split').checked;
    $('live-url-label').textContent=feature('kick')?'Enlace del directo de YouTube, Kick o Twitch':'Enlace del directo de YouTube';
    $('live-format-wrap').hidden=!feature('formats');
    $('published-format-wrap').hidden=!feature('formats');
    $('live-profile-wrap').hidden=!feature('profiles');
    $('published-profile-wrap').hidden=!feature('profiles');
    $('live-profile').disabled=liveLocked;
    $('published-profile').disabled=publishedLocked;
    $('kick-settings').hidden=!kick;
    $('kick-crop-settings').hidden=!split;
    if(split)$('live-format').value='vertical';
    $('live-format').disabled=liveLocked||split;
    $('published-format').disabled=publishedLocked;
    $('youtube').disabled=liveLocked&&Boolean(lastState&&lastState.live.running);
    ['kick-split','kick-region'].concat(coordinateIds).forEach(function(id){$(id).disabled=liveLocked;});
    $('kick-preview').disabled=liveLocked||kickPreviewPending;
    refreshDesign();
  }
  function lock(b){
    ['video','remove-watermark','watermark-opacity','clear-source'].forEach(function(id){$(id).disabled=b;});
    $('load').disabled=b||!has(['yt-dlp','ffprobe']);
    $('analyze').disabled=b||!has(['ffmpeg','whisper-cli','modelo'])||(lastState&&!lastState.source);
    $('export').disabled=b||!has(['ffmpeg','ffprobe','logo'])||(lastState&&!lastState.source);
    var liveLocked=pending||(available()&&(!supportsClipSettings()||lastState.live.running));
    $('live-start').disabled=liveLocked||(available()&&!ready());
    $('clip-duration').disabled=liveLocked;
    $('clips-per-block').disabled=liveLocked;
    $('live-fast').disabled=liveLocked||(available()&&!supportsFastMode());
    $('live-subtitles').disabled=liveLocked||(available()&&!supportsEditor());
    $('export-subtitles').disabled=b||(available()&&!supportsEditor());
    layoutControls(liveLocked,b);
    if(editor)editorControls(b);
  }
  function mark(){return {watermark:!$('remove-watermark').checked,watermark_opacity:Number($('watermark-opacity').value)/100};}
  function markPreview(){$('opacity-value').textContent=$('watermark-opacity').value+' %';document.querySelector('.moving-mark').style.opacity=mark().watermark_opacity;document.querySelector('.watermark-demo').classList.toggle('mark-hidden',!mark().watermark);}
  $('remove-watermark').onchange=markPreview;$('watermark-opacity').oninput=markPreview;markPreview();
  function showCaptureMode(){
    if(available()&&lastState&&!supportsFastMode()){
      $('live-fast').checked=false;
      $('live-mode-hint').textContent='Actualiza Julio Clip en Windows para usar el modo rápido.';
      return;
    }
    var fast=$('live-fast').checked;
    var text=fast?'Bloques de alrededor de 1 minuto. Hay menos momentos para comparar.':
      'Bloques de alrededor de 5 minutos. Hay más momentos para comparar.';
    if(fast){
      var length=Number($('clip-duration').value),count=Number($('clips-per-block').value);
      if(length*count>60)text+=' Pueden salir menos clips por bloque.';
      if(length>=60)text+=' El bloque se amplía a '+Math.max(60,length+5)+' segundos para que quepa el clip.';
    }
    $('live-mode-hint').textContent=text;
  }
  $('live-fast').onchange=showCaptureMode;
  $('clip-duration').onchange=showCaptureMode;
  $('clips-per-block').onchange=showCaptureMode;
  showCaptureMode();
  function relock(){lock(pending||(lastState&&lastState.busy));}
  function selectedKickRegion(){return $('kick-region').value==='game'?'game':'camera';}
  function validRegion(r){
    return r.every(Number.isInteger)&&r[0]>=0&&r[1]>=0&&r[2]>=5&&r[3]>=5&&r[0]+r[2]<=100&&r[1]+r[3]<=100;
  }
  function drawKickRegion(name,rect){
    var box=$('kick-'+name+'-box');
    box.hidden=!validRegion(rect);
    if(box.hidden)return;
    ['left','top','width','height'].forEach(function(key,i){box.style[key]=rect[i]+'%';});
  }
  function showKickRegions(){
    coordinateIds.forEach(function(id,i){$(id).value=kickRegions[selectedKickRegion()][i];});
    Object.keys(kickRegions).forEach(function(name){drawKickRegion(name,kickRegions[name]);});
  }
  function changeKickRegion(name,rect){
    kickRegions[name]=rect;
    if(name==='game')gameEdited=true;
    if(name==='camera'&&!gameEdited&&validRegion(rect)){
      var x=rect[0],y=rect[1],right=x+rect[2],bottom=y+rect[3];
      kickRegions.game=[[0,0,x,100],[right,0,100-right,100],[0,0,100,y],[0,bottom,100,100-bottom]]
        .filter(validRegion).sort(function(a,b){return b[2]*b[3]-a[2]*a[3];})[0]||[0,0,100,100];
    }
    Object.keys(kickRegions).forEach(function(key){drawKickRegion(key,kickRegions[key]);});
  }
  $('kick-region').onchange=showKickRegions;
  coordinateIds.forEach(function(id){
    $(id).oninput=function(){
      var name=selectedKickRegion();
      changeKickRegion(name,coordinateIds.map(function(key){return $(key).value===''?NaN:Number($(key).value);}));
    };
  });
  function clearKickPreview(){
    if(kickPreviewUrl)URL.revokeObjectURL(kickPreviewUrl);
    kickPreviewUrl='';
    $('kick-image').removeAttribute('src');
    $('kick-frame').hidden=true;
  }
  $('youtube').oninput=function(){
    clearKickPreview();
    $('kick-preview-status').textContent='Encuadra con un fotograma o ajusta los porcentajes.';
    if(!isKick())$('kick-split').checked=false;
    relock();
  };
  $('kick-split').onchange=function(){showKickRegions();relock();};
  $('kick-preview').onclick=function(){
    if(!available()||!isKick()||kickPreviewPending)return;
    var url=$('youtube').value.trim();
    kickPreviewPending=true;
    relock();
    $('kick-preview-status').textContent='Buscando un fotograma del directo…';
    transport('kick-preview',{url:url}).then(function(blob){
      if(url!==$('youtube').value.trim()||!isKick())return;
      clearKickPreview();
      kickPreviewUrl=URL.createObjectURL(blob);
      $('kick-image').src=kickPreviewUrl;
      $('kick-frame').hidden=false;
      showKickRegions();
      $('kick-preview-status').textContent='Elige Cámara o Gameplay y arrastra sobre el fotograma para ajustar la zona.';
    }).catch(function(e){$('kick-preview-status').textContent=e.message;}).then(function(){
      kickPreviewPending=false;relock();
    });
  };
  function kickPoint(e){
    var area=$('kick-frame').getBoundingClientRect();
    return [Math.max(0,Math.min(100,Math.round(100*(e.clientX-area.left)/area.width))),
            Math.max(0,Math.min(100,Math.round(100*(e.clientY-area.top)/area.height)))];
  }
  function draggedRegion(origin,point){
    return [Math.min(origin[0],point[0]),Math.min(origin[1],point[1]),
            Math.abs(origin[0]-point[0]),Math.abs(origin[1]-point[1])];
  }
  $('kick-frame').onpointerdown=function(e){
    if($('kick-region').disabled||e.button!==0)return;
    kickDrag={id:e.pointerId,origin:kickPoint(e),name:selectedKickRegion()};
    this.setPointerCapture(e.pointerId);
  };
  $('kick-frame').onpointermove=function(e){
    if(kickDrag&&kickDrag.id===e.pointerId)drawKickRegion(kickDrag.name,draggedRegion(kickDrag.origin,kickPoint(e)));
  };
  $('kick-frame').onpointerup=function(e){
    if(!kickDrag||kickDrag.id!==e.pointerId)return;
    var rect=draggedRegion(kickDrag.origin,kickPoint(e));
    if(validRegion(rect))changeKickRegion(kickDrag.name,rect);
    kickDrag=null;
    showKickRegions();
  };
  $('kick-frame').onpointercancel=function(){kickDrag=null;showKickRegions();};
  function rpc(method,payload){return new Promise(function(resolve,reject){
    if(!linked||!bridge||bridge.closed)return reject(Error('Vincula esta página con el programa en el mismo equipo.'));
    var id=random(12),timer=setTimeout(function(){delete calls[id];reject(Error('La conexión no respondió a tiempo. Revisa la ventana de vinculación.'));},method==='state'?10000:900000);
    calls[id]={resolve:resolve,reject:reject,timer:timer};bridge.postMessage({type:'julio-request',challenge:challenge,id:id,method:method,payload:payload},localOrigin);
  });}
  function transport(method,payload){
    if(!local)return rpc(method,payload);
    var options={},path='/api/'+method;
    var binary={download:'/clips/',thumbnail:'/thumbs/',subtitles:'/subtitulos/'};
    if(binary[method])path=binary[method]+payload.name;
    else if(method!=='state'&&method!=='diagnostics')options={method:'POST',headers:{'X-Julio-Token':token,'Content-Type':method==='upload'||method==='watermark'?'application/octet-stream':'application/json'},body:method==='upload'||method==='watermark'?payload:JSON.stringify(payload||{})};
    return fetch(path,options).then(function(r){if(!r.ok)return r.json().then(function(d){throw Error(d.error||'La operación falló.');});return binary[method]||method==='kick-preview'?r.blob():r.json();});
  }
  function act(method,payload){
    if(!available()){note('Sin conexión: inicia el programa y pulsa Vincular con mi equipo, o utiliza la interfaz local.');return;}
    var locks=['youtube','analyze','export','batch-export','live-start','prepare-mac','clear-source'].indexOf(method)!==-1;
    if(locks){pending+=1;lock(true);}
    transport(method,payload).then(function(result){
      note((result&&result.message)||'Solicitud aceptada. Consulta el estado real de la operación.');
      if(method==='live-start'){location.hash='#monitoreo';showView();}
    }).catch(function(e){note(e.message);}).then(function(){if(locks)pending-=1;refresh();});
  }
  function requirements(d){dependencies=d;diagnosed=true;$('requirements').textContent='';Object.keys(d).forEach(function(name){var el=document.createElement('span');el.className='req '+(d[name]?'ok':'missing');el.textContent=name+(d[name]?': comprobación básica correcta':': falta o no funciona');$('requirements').appendChild(el);});$('tools-state').textContent=ready()?'Herramientas disponibles. Prueba un clip corto antes de iniciar una captura larga.':'Faltan herramientas o recursos: '+Object.keys(d).filter(function(name){return !d[name];}).join(', ')+'. '+(macDesktop?'Pulsa Preparar herramientas para Mac.':desktop?'Vuelve a ejecutar el instalador si faltan archivos.':'Comprueba los archivos de la instalación.');lock(pending||(lastState&&lastState.busy));}
  function configureDesktop(d){
    if(!d.desktop)return;
    desktop=true;publicEdition=d.public===true;macDesktop=d.prepare_mac===true;
    document.body.classList.toggle('desktop-studio',true);
    document.body.classList.toggle('public-edition',publicEdition);
    document.title=publicEdition?'Julio Clip Público':'Julio Clip Privado';
    document.querySelector('.aside-note p').textContent='Procesa tus videos y guarda tus clips en este equipo.';
    $('prepare-mac').hidden=!macDesktop;
    $('public-limits').hidden=!publicEdition;
    if(publicEdition){
      $('nav-publicados').hidden=true;
      $('remove-watermark').checked=true;
      $('clip-duration').value='30';
      $('clips-per-block').value='2';
      if(location.hash==='#publicados')location.hash='#estudio';
      views=views.filter(function(v){return v!=='publicados';});
      markPreview();
    }
    showView();
  }
  function disconnect(){if(bridge&&!bridge.closed)bridge.close();bridge=null;challenge='';linked=false;diagnosed=false;lastState=null;dependencies={};closeEditor();Object.keys(calls).forEach(function(id){clearTimeout(calls[id].timer);calls[id].reject(Error('Conexión revocada.'));delete calls[id];});$('connection').textContent='● Sin vincular';$('link').hidden=false;$('unlink').hidden=true;$('status').textContent='Sin conexión al programa.';lock(false);}
  window.addEventListener('message',function(e){
    if(local||!bridge||bridge.closed||e.origin!==localOrigin||e.source!==bridge)return;var d=e.data;if(!d||d.challenge!==challenge)return;
    if(d.type==='julio-connected'){linked=true;$('link').hidden=true;$('unlink').hidden=false;requirements(d.requirements);note('Conexión autorizada. Mantén abierta la ventana local de vinculación.');refresh();}
    else if(d.type==='julio-disconnected')disconnect();
    else if(linked&&d.type==='julio-response'&&calls[d.id]){var c=calls[d.id];clearTimeout(c.timer);delete calls[d.id];if(d.error)c.reject(Error(d.error));else c.resolve(d.data);}
  });
  $('link').onclick=function(){
    if(location.protocol!=='https:'){note('Abre la página desplegada por HTTPS en Netlify para vincular. Esta copia sin publicar permanece en demostración.');return;}
    disconnect();
    challenge=random(16);bridge=window.open(localOrigin+'/bridge.html?origin='+encodeURIComponent(location.origin)+'&challenge='+challenge,'julio-vincular-'+challenge,'width=720,height=650');
    note(bridge?'Autoriza la dirección de esta página en la ventana local. Inicia primero Julio Clip si no carga.':'El navegador bloqueó la ventana. Permite la ventana emergente o utiliza la interfaz local.');
  };
  $('unlink').onclick=function(){if(bridge&&!bridge.closed)bridge.close();disconnect();};
  $('refresh-tools').onclick=function(){if(!available()){note('Primero inicia y vincula el programa.');return;}this.disabled=true;var b=this;transport('diagnostics').then(function(d){requirements(d.requirements);refresh();}).catch(function(e){note(e.message);}).then(function(){b.disabled=false;});};
  $('prepare-mac').onclick=function(){if(macDesktop)act('prepare-mac');};
  $('load').onclick=function(){
    var url=$('published-url').value.trim(),host;
    try{host=new URL(url).hostname;}catch(e){note('Pega el enlace HTTPS de un video publicado.');return;}
    if(lastState&&typeof lastState.source_platform==='undefined'&&(host==='tiktok.com'||host.endsWith('.tiktok.com'))){
      note('Actualiza Julio Clip en Windows para importar videos de TikTok.');
      return;
    }
    act('youtube',{url:url});
  };
  $('analyze').onclick=function(){
    var options=feature('profiles')?{profile:$('published-profile').value||'auto'}:{};
    if(window.JulioStudio){options.clip_seconds=Number($('published-duration').value);options.clip_count=Number($('published-count').value);}
    act('analyze',options);
  };
  $('export').onclick=function(){
    var d=mark();d.start=$('start').value;d.end=$('end').value;
    var start=Number(d.start),end=Number(d.end);
    if(d.start===''||d.end===''||!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end-start>180+1e-9){
      note('Introduce un inicio y un final válidos. La duración máxima del clip es de 180 segundos.');
      return;
    }
    if(supportsEditor())d.subtitles=$('export-subtitles').checked;
    applySubtitles(d,'export');
    if(feature('formats'))d.format=$('published-format').value||'original';
    act('export',addStyling(d,'design'));
  };
  $('live-start').onclick=function(){
    var d=mark();
    d.url=$('youtube').value.trim();
    d.clip_seconds=Number($('clip-duration').value);
    d.clips_per_block=Number($('clips-per-block').value);
    if(supportsFastMode())d.fast_mode=$('live-fast').checked;
    if(supportsEditor())d.subtitles=$('live-subtitles').checked;
    applySubtitles(d,'live');
    if(feature('formats'))d.format=$('live-format').value||'original';
    if(feature('profiles'))d.profile=$('live-profile').value||'auto';
    if(isKick()&&$('kick-split').checked){
      if(!Object.keys(kickRegions).every(function(name){return validRegion(kickRegions[name]);})){
        note('Comprueba que los dos encuadres estén dentro del vídeo y midan al menos 5 % por lado.');
        return;
      }
      d.format='vertical';
      d.split=kickRegions;
    }
    act('live-start',addStyling(d,'design'));
  };
  $('live-stop').onclick=function(){act('live-stop');};
  $('monitor-stop').onclick=function(){act('live-stop');};
  $('live-finish').onclick=function(){act('live-finish');};
  $('monitor-finish').onclick=function(){act('live-finish');};
  $('published-cancel').onclick=function(){
    var job=lastState&&lastState.published_job;
    if(job&&job.status==='running')act('published-cancel',{id:job.id});
  };
  $('clear-source').onclick=function(){if(confirm('¿Retirar la copia importada y sus temporales? No se borrará tu archivo original ni los clips.'))act('clear-source');};
  $('save-storage').onclick=function(){act('storage',{quota_gb:$('quota').value,max_clips:$('max-clips').value});};
  $('empty-trash').onclick=function(){if(confirm('¿Borrar definitivamente los clips de la papelera? No se puede deshacer.'))act('empty-trash',{confirmed:true});};
  $('clear-queue').onclick=function(){if(confirm('¿Descartar definitivamente los bloques pendientes? Detén antes la captura. Los clips exportados se conservan.'))act('clear-queue',{confirmed:true});};
  $('video').onchange=function(){var f=this.files[0];if(!f)return;if(!available()){note('Primero vincula esta página o usa la interfaz local. No se ha cargado el archivo.');this.value='';return;}if(f.size>2*1024*1024*1024){note('El video supera 2 GB.');return;}pending+=1;lock(true);note('Copiando video al almacenamiento local…');transport('upload',f).then(function(){$('filename').textContent=f.name;note('Video importado.');}).catch(function(e){note(e.message);}).then(function(){pending-=1;refresh();});};
  function button(text,action){var b=document.createElement('button');b.textContent=text;b.onclick=action;return b;}
  function download(name,method){
    method=method||'download';
    transport(method,{name:name}).then(function(blob){
      if(window.JulioStudio&&window.JulioStudio.hasDownloadFolder())return window.JulioStudio.saveDownload(blob,method==='subtitles'?name.replace(/\.mp4$/,'.srt'):name);
      var url=URL.createObjectURL(blob),a=document.createElement('a');
      a.href=url;a.download=method==='subtitles'?name.replace(/\.mp4$/,'.srt'):name;
      document.body.appendChild(a);a.click();a.remove();
      setTimeout(function(){URL.revokeObjectURL(url);},60000);
    }).catch(function(e){note(e.message);});
  }
  function editorMessage(message){$('editor-status').textContent=message;}
  function closeEditor(){
    if(!editor)return;
    var player=$('editor-video');
    player.pause();
    player.removeAttribute('src');
    player.load();
    if(editor.url)URL.revokeObjectURL(editor.url);
    if(editorTrack){
      editorTrack.mode='hidden';
      while(editorTrack.cues.length)editorTrack.removeCue(editorTrack.cues[0]);
      editorTrack.mode='disabled';
    }
    editor=null;
    $('clip-editor').hidden=true;
  }
  function openEditor(clip){
    if(!available()||!supportsEditor())return;
    closeEditor();
    var session={clip:clip,cuts:[],duration:0,url:null,job:null};
    editor=session;
    $('editor-name').textContent=clip.title||'Vista previa del clip';
    $('editor-start').value='0';
    $('editor-end').value='';
    $('editor-cuts').textContent='';
    $('editor-copy').hidden=true;
    $('editor-subtitles').checked=Boolean(clip.subtitles&&(!clip.burned_subtitles||clip.editable_captions));
    $('editor-subtitles').disabled=Boolean(clip.burned_subtitles&&!clip.editable_captions);
    $('editor-burn').checked=true;
    if(clip.subtitle_style){
      var savedStyle=clip.subtitle_style;
      ['color','size','position','font','accent','outline','shadow','reveal'].forEach(function(key){
        if(savedStyle[key]!==undefined)$('edit-caption-'+key).value=String(savedStyle[key]);
      });
      $('edit-caption-offset').value=String(savedStyle.offset_ms||0);$('edit-caption-animations').checked=savedStyle.animations!==false;
      captionThemes.forEach(function(theme,index){
        if(theme[0]===savedStyle.theme)$('edit-caption-catalog').children[index].onclick();
      });
      captionDemo('edit-caption');
    }
    $('editor-captions-hint').textContent=clip.burned_subtitles&&!clip.editable_captions?
      'Este clip ya tiene texto incrustado. La copia conserva esas letras.':
      'Si el clip tiene subtítulos, puedes verlos aquí. Julio Clip puede generarlos al guardar.';
    $('editor-format').value='original';
    $('editor-face').checked=false;
    $('editor-title').value='';
    refreshDesign();
    if(window.JulioStudio)window.JulioStudio.openEditor(clip);
    $('clip-editor').hidden=false;
    $('editor-heading').focus();
    editorMessage('Cargando el clip desde tu equipo…');
    editorControls(false);
    var player=$('editor-video');
    Promise.all([transport('clip-info',{name:clip.name}),clip.name==='imported.video'?fetch('/source-video').then(function(r){if(!r.ok)throw Error('No se pudo abrir el video importado');return r.blob();}):transport('download',{name:clip.name})]).then(function(result){
      if(editor!==session)return;
      session.project=result[0].project||null;
      if(clip.name==='imported.video'&&result[0].duration>0){session.duration=result[0].duration;$('editor-end').value=Math.min(session.duration,180);editorInputChanged();}
      session.captionFields=[];
      $('caption-corrections').textContent='';
      var canCorrect=!clip.burned_subtitles||clip.editable_captions;
      $('caption-corrections-wrap').hidden=!canCorrect||!result[0].captions.length;
      if(canCorrect)result[0].captions.forEach(function(cue){
        var label=document.createElement('label');label.textContent=cue.start.toFixed(2)+'–'+cue.end.toFixed(2)+' s';
        var field=document.createElement('input');field.type='text';field.maxLength=240;field.value=cue.text;
        label.appendChild(field);$('caption-corrections').appendChild(label);session.captionFields.push(field);
      });
      session.hasCaptions=!session.clip.burned_subtitles&&result[0].captions.length>0;
      if(session.hasCaptions){
        if(!editorTrack)editorTrack=player.addTextTrack('captions','Español','es');
        editorTrack.mode='hidden';
        result[0].captions.forEach(function(cue){
          var text=cue.text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
          editorTrack.addCue(new VTTCue(cue.start,cue.end,text));
        });
        $('editor-subtitles').onchange();
      }
      session.url=URL.createObjectURL(result[1]);
      player.src=session.url;
    }).catch(function(e){if(editor===session)editorMessage(e.message);});
  }
  function editorDraft(){
    if(!editor||!editor.duration)return null;
    var start=$('editor-start'),end=$('editor-end');
    var draft={start:start.valueAsNumber,end:end.valueAsNumber,remove:editor.cuts.map(function(cut){
      return {start:cut.start.valueAsNumber,end:cut.end.valueAsNumber};
    }).sort(function(a,b){return a.start-b.start;})};
    if(!(draft.start>=0&&draft.end>draft.start&&draft.end<=editor.duration))return null;
    var cursor=draft.start,duration=draft.end-draft.start;
    for(var i=0;i<draft.remove.length;i++){
      var cut=draft.remove[i];
      if(!(cut.start>=cursor&&cut.end>cut.start&&cut.end<=draft.end))return null;
      cursor=cut.end;
      duration-=cut.end-cut.start;
    }
    draft.duration=duration;
    return draft;
  }
  function editorControls(busy){
    var draft=editorDraft(), ready=Boolean(editor.duration), saving=Boolean(editor.job);
    $('editor-fields').disabled=!ready||saving;
    $('editor-add-cut').disabled=editor.cuts.length>=8;
    $('editor-save').disabled=busy||saving||!draft||draft.duration<.25||draft.duration>180+1e-9||!has(['ffmpeg','ffprobe']);
    $('editor-length').textContent=!ready?'':draft?'Duración de la copia · '+draft.duration.toFixed(2)+' s':'Revisa los tiempos y evita tramos solapados.';
  }
  function editorInputChanged(){
    if(!editor)return;
    editorControls(pending||(lastState&&lastState.busy));
  }
  function usePlayhead(input){
    input.value=Math.min(editor.duration,Math.floor($('editor-video').currentTime*1000)/1000);
    editorInputChanged();
  }
  function cutField(labelText){
    var group=document.createElement('div'),label=document.createElement('label'),input=document.createElement('input');
    input.type='number';input.min='0';input.max=String(editor.duration);input.step='0.001';
    input.oninput=editorInputChanged;
    label.textContent=labelText;label.appendChild(input);group.appendChild(label);
    group.appendChild(button('Usar posición actual',function(){usePlayhead(input);}));
    return {group:group,input:input};
  }
  $('editor-close').onclick=closeEditor;
  $('editor-start').oninput=editorInputChanged;
  $('editor-end').oninput=editorInputChanged;
  $('editor-start-now').onclick=function(){usePlayhead($('editor-start'));};
  $('editor-end-now').onclick=function(){usePlayhead($('editor-end'));};
  $('editor-subtitles').onchange=function(){
    if(editor&&editor.hasCaptions&&editorTrack)editorTrack.mode=this.checked?'showing':'hidden';
    refreshDesign();
  };
  $('editor-video').onloadedmetadata=function(){
    if(!editor||!editor.url||!Number.isFinite(this.duration))return;
    editor.duration=Math.floor(this.duration*1000)/1000;
    $('editor-end').value=Math.min(editor.duration,180);
    if(editor.project){
      var saved=editor.project;$('editor-start').value=saved.start;$('editor-end').value=saved.end;
      (saved.remove||[]).forEach(function(cut){$('editor-add-cut').onclick();var fields=editor.cuts[editor.cuts.length-1];fields.start.value=cut.start;fields.end.value=cut.end;});
      if(window.JulioStudio)window.JulioStudio.restoreProject(saved);
      editor.project=null;
    }
    editorMessage('Marca los tiempos en el video original.');
    editorInputChanged();
  };
  $('editor-video').onerror=function(){if(editor&&editor.url)editorMessage('El navegador no pudo abrir el original. Si los tiempos están disponibles, usa Renderizar vista previa para convertirlo.');};
  $('editor-add-cut').onclick=function(){
    if(!editor||editor.cuts.length>=8)return;
    var row=document.createElement('div'),start=cutField('Quitar desde (s)'),end=cutField('Quitar hasta (s)');
    var cut={start:start.input,end:end.input};
    row.className='editor-cut';
    row.appendChild(start.group);
    row.appendChild(end.group);
    row.appendChild(button('Retirar tramo',function(){
      editor.cuts.splice(editor.cuts.indexOf(cut),1);row.remove();editorInputChanged();
    }));
    editor.cuts.push(cut);
    $('editor-cuts').appendChild(row);
    usePlayhead(cut.start);
    cut.end.focus();
  };
  $('editor-save').onclick=function(){
    if(!editor||this.disabled)return;
    var session=editor,draft=editorDraft();
    session.job=random(12);
    $('editor-copy').hidden=true;
    editorMessage('Guardando la copia en tu equipo…');
    editorInputChanged();
    var payload={id:session.job,name:session.clip.name,start:draft.start,end:draft.end,
      remove:draft.remove,subtitles:$('editor-subtitles').checked};
    if(feature('formats'))payload.format=$('editor-format').value||'original';
    applySubtitles(payload,'editor');
    if(session.captionFields&&session.captionFields.length)payload.caption_edits=session.captionFields.map(function(field){return field.value;});
    var method=session.previewRequested?'editor-preview':'edit';session.previewRequested=false;
    transport(method,addStyling(payload,'editor')).then(refresh).catch(function(e){
      if(editor!==session)return;
      session.job=null;
      editorMessage(e.message);
      editorInputChanged();
    });
  };
  function editorResult(state){
    if(!editor||!editor.job||!state.edits)return;
    var result=state.edits[editor.job];
    if(!result||(!result.name&&!result.error&&!result.preview))return;
    editor.job=null;
    editorMessage(result.error||(result.preview?'Vista previa renderizada. Este es el resultado real de los ajustes.':'Copia guardada en Mis clips.'));
    if(result.preview){
      $('editor-rendered').src='/editor-preview.mp4?v='+Date.now();$('editor-rendered').hidden=false;
    }
    var copy=state.clips.find(function(clip){return clip.name===result.name;});
    $('editor-copy').hidden=!copy;
    if(copy)$('editor-copy').onclick=function(){openEditor(copy);};
    editorInputChanged();
  }
  function renderClips(clips){
    if(window.JulioStudio)clips=window.JulioStudio.filter(clips);
    var key=JSON.stringify([supportsEditor(),clips]);
    if(clipListKey===key)return;
    clipListKey=key;
    Object.keys(thumbnails).forEach(function(name){
      if(clips.some(function(c){return c.name===name;}))return;
      var entry=thumbnails[name];
      delete thumbnails[name];
      entry.then(function(url){if(url)URL.revokeObjectURL(url);});
    });
    $('clips').textContent=clips.length?'':'Los clips exportados aparecerán aquí.';
    $('clips').className=clips.length?'clip-gallery':'empty';
    clips.slice().sort(function(a,b){return window.JulioStudio&&window.JulioStudio.interestOrder()?(b.interest||0)-(a.interest||0):(b.created||0)-(a.created||0);}).forEach(function(c,index){
      var row=document.createElement('div'),details=document.createElement('div'),p=document.createElement('p');
      var title=document.createElement('h3'),picture=document.createElement('img'),actions=document.createElement('div');
      var state=document.createElement('span');
      row.className='clip clip-card';
      if(row.style.setProperty)row.style.setProperty('--clip-aspect',c.width&&c.height?c.width+'/'+c.height:c.format==='vertical'?'9/16':c.format==='square'?'1/1':'16/9');
      actions.className='connection-actions';details.className='clip-details';
      title.textContent=c.title||'Clip '+(index+1);title.className='clip-title';
      picture.className='clip-thumbnail';picture.src='poster.svg';picture.alt='Miniatura de '+(c.title||'tu clip');
      picture.setAttribute('loading','lazy');picture.setAttribute('decoding','async');
      if(supportsEditor()){
        picture.tabIndex=0;picture.setAttribute('role','button');picture.setAttribute('aria-label','Ver '+(c.title||'clip '+(index+1)));
        picture.onclick=function(){openEditor(c);};
        picture.onkeydown=function(event){if(event.key==='Enter'||event.key===' '){event.preventDefault();openEditor(c);}};
      }
      {
        if(local)picture.src='/thumbs/'+c.name;
        else{
          if(!thumbnails[c.name])thumbnails[c.name]=transport('thumbnail',{name:c.name})
            .then(function(blob){return URL.createObjectURL(blob);}).catch(function(){delete thumbnails[c.name];return '';});
          thumbnails[c.name].then(function(url){if(url)picture.src=url;});
        }
        picture.onerror=function(){picture.onerror=null;picture.src='poster.svg';picture.alt='Miniatura no disponible; puedes abrir o descargar el clip.';};
      }
      p.textContent=Number(c.end-c.start).toFixed(1)+' s · '+(c.watermark?'con marca':'sin marca')+
        (c.format==='vertical'?(c.split?' · 9:16 dividido':' · 9:16'):c.format==='square'?' · 1:1':'')+
        (c.burned_subtitles?' · subtítulos visibles':c.subtitles?' · subtítulos':c.no_caption_speech?' · voz no detectada':'')+
        (c.edited?' · copia editada':'')+
        (c.follow_face?' · encuadre facial':c.face_requested?' · plano completo':'')+
        (typeof c.interest==='number'?' · Potencial viral estimado '+c.interest+'/100':'');
      p.setAttribute('title',p.textContent);
      p.textContent=Number(c.end-c.start).toFixed(1)+' s · '+(c.format==='vertical'?'9:16':c.format==='square'?'1:1':'Original')+
        (typeof c.interest==='number'?' · Interés estimado '+c.interest+'/100':'')+
        (c.created?' · '+new Date(c.created*1000).toLocaleDateString('es'):'')+' · '+({conversation:'Conversación',sports:'Deportes',gameplay:'Gameplay',general:'General'}[c.category||'general']);
      state.className='clip-ready';state.textContent='Listo para descargar';
      if(supportsEditor())actions.appendChild(button('Editar',function(){openEditor(c);}));
      actions.appendChild(button('Descargar ↓',function(){download(c.name);}));
      if(!publicEdition)actions.appendChild(button('A la papelera',function(){if(window.confirm('¿Mover este clip a la papelera? Puedes restaurarlo después.'))act('trash',{name:c.name});}));
      if(c.subtitles)actions.appendChild(button('Subtítulos .srt',function(){download(c.name,'subtitles');}));
      details.appendChild(title);details.appendChild(p);details.appendChild(state);details.appendChild(actions);
      row.appendChild(picture);row.appendChild(details);$('clips').appendChild(row);
    });
  }
  function clock(seconds){
    var whole=Math.floor(seconds||0);
    return [Math.floor(whole/3600),Math.floor(whole/60)%60,whole%60].map(function(n){return n<10?'0'+n:String(n);}).join(':');
  }
  function remaining(progress){
    if(typeof progress.remaining_seconds!=='number')return 'Calculando tiempo restante…';
    if(progress.fraction>=1)return 'Cerrando esta etapa…';
    return 'Faltan aprox. '+clock(progress.remaining_seconds)+' en esta etapa.';
  }
  function renderPublished(s){
    var job=s.published_job;
    var active=job&&(job.status==='running'||job.status==='cancelling');
    var status=active?(job.status==='cancelling'?'Cancelando operación…':job.label):s.status;
    if($('published-status').textContent!==status)$('published-status').textContent=status;
    var bar=$('published-progress'), detail=$('published-eta'), cancel=$('published-cancel');
    bar.hidden=!active;detail.hidden=!active;cancel.hidden=!active;
    if(!active)return;
    cancel.disabled=job.status==='cancelling';
    if(typeof job.fraction==='number')bar.value=Math.floor(job.fraction*100);
    else bar.removeAttribute('value');
    detail.textContent=job.status==='cancelling'?'Deteniendo el trabajo actual.':
      'En esta etapa: '+clock(job.elapsed_seconds)+' · '+remaining(job);
  }
  function renderLivePreview(liveState){
    var videoId=currentView==='monitoreo'&&liveState.running&&liveState.video_id;
    videoId=typeof videoId==='string'&&/^[A-Za-z0-9_-]{11}$/.test(videoId)?videoId:'';
    $('monitor-preview').hidden=!videoId;
    if(videoId===playerVideoId)return;
    playerVideoId=videoId;
    $('monitor-player').textContent='';
    if(!videoId)return;
    var frame=document.createElement('iframe');
    frame.setAttribute('title','Reproductor del directo de YouTube');
    frame.setAttribute('loading','lazy');
    frame.setAttribute('allow','encrypted-media; picture-in-picture; fullscreen');
    frame.setAttribute('allowfullscreen','');
    frame.setAttribute('referrerpolicy','strict-origin-when-cross-origin');
    frame.src='https://www.youtube.com/embed/'+videoId+'?playsinline=1';
    $('monitor-youtube').href='https://www.youtube.com/watch?v='+videoId;
    $('monitor-player').appendChild(frame);
  }
  function renderMonitor(liveState,clips){
    renderLivePreview(liveState);
    var m=liveState.monitor||{};
    $('monitor-state').textContent=liveState.status+' · '+(liveState.backlog||0)+' bloques pendientes de procesar';
    $('monitor-stop').disabled=!liveState.running;
    $('monitor-finish').hidden=typeof liveState.finishing!=='boolean';
    $('live-finish').hidden=$('monitor-finish').hidden;
    $('monitor-finish').disabled=!liveState.running||liveState.finishing;
    $('live-finish').disabled=$('monitor-finish').disabled;
    $('metric-recorded').textContent=clock(m.recorded_seconds);
    ['reviewed','highlights','rejected','generated'].forEach(function(key){$('metric-'+key).textContent=String(m[key]||0);});
    $('metric-queued').textContent=String(m.pending_clips||0);
    var analysis=m.analysis||{};
    var transcribing=analysis.label||'Convirtiendo el audio en texto';
    if(typeof analysis.fraction==='number'&&analysis.total){
      transcribing+=' '+Math.floor(analysis.fraction*100)+' % · '+clock(analysis.total*analysis.fraction)+' de '+clock(analysis.total)+' de audio';
    }
    if(analysis.label)transcribing+=' · '+remaining(analysis)+' · '+clock(analysis.elapsed_seconds)+' transcurridos';
    var descriptions={
      recording:m.recording?'Desde el inicio · '+clock(m.elapsed_seconds):m.elapsed_seconds?'Sesión · '+clock(m.elapsed_seconds):'En espera',
      transcribing:transcribing,
      searching:analysis.label||'Comparando imagen, audio y narración',
      exporting:'Clip '+(m.exporting||0)+' de '+(m.export_total||0)+' del bloque'+
        (analysis.label&&(/^(Siguiendo|Codificando)/).test(analysis.label)?' · '+analysis.label:'')
    };
    Object.keys(descriptions).forEach(function(key){
      var active=key==='recording'?Boolean(m.recording):m.stage===key;
      $('stage-'+key).classList.toggle('stage-active',active);
      $('stage-'+key+'-detail').textContent=active||key==='recording'?descriptions[key]:
        key==='searching'&&m.reviewed?'Último bloque revisado':'En espera';
    });
    var recent=(m.recent_clips||[]).filter(function(clip){
      return clips.some(function(c){return c.name===clip.name;});
    });
    var clipKey=JSON.stringify(recent);
    if(clipKey!==monitorClipKey){
      monitorClipKey=clipKey;
      $('monitor-clips').textContent='';
      (recent.length?recent:[{title:'Aún no hay clips listos.'}]).forEach(function(clip){
        var item=document.createElement('li');item.textContent=clip.title;
        if(clip.name)item.appendChild(button('Descargar ↓',function(){download(clip.name);}));
        $('monitor-clips').appendChild(item);
      });
    }
    var rejections=m.recent_rejections||[],key=JSON.stringify(rejections);
    if(key===monitorRejectionKey)return;
    monitorRejectionKey=key;
    $('monitor-rejections').textContent='';
    if(!rejections.length){
      var empty=document.createElement('li');empty.textContent='Aquí aparecerán los motivos de descarte.';
      $('monitor-rejections').appendChild(empty);
    }
    rejections.forEach(function(decision){
      var item=document.createElement('li');
      item.textContent=clock(decision.start)+'–'+clock(decision.end)+' del bloque · '+decision.reason+
        (typeof decision.score==='number'?' '+decision.score+'/100.':'');
      $('monitor-rejections').appendChild(item);
    });
  }
  function render(s){
    renderLicense(s.license);
    if(window.JulioStudio)window.JulioStudio.render(s);
    if(s.source_duration>0&&(!lastState||s.source_duration!==lastState.source_duration||s.source_platform!==lastState.source_platform)){
      $('start').value=0;
      $('end').value=Math.min(30,Math.floor(s.source_duration*1000)/1000);
    }
    lastState=s;$('connection').textContent=(desktop?'● En este equipo':local?'● Conexión local':'● Equipo vinculado')+(ready()?' · herramientas disponibles':' · revisar herramientas');$('status').textContent=s.status;$('prepare-mac').disabled=s.busy;lock(pending||s.busy);
    if(s.source_platform)$('filename').textContent='Video de '+s.source_platform+' · '+Number(s.source_duration).toFixed(1)+' s';
    else if(s.source&&$('filename').textContent==='Todavía no has importado un video.')$('filename').textContent='Video disponible en el equipo.';
    if(!s.source)$('filename').textContent='Todavía no has importado un video.';
    renderPublished(s);
    renderClips(s.clips);
    renderMonitor(s.live,s.clips);
    editorResult(s);
    $('trash').textContent=s.trash.length?'':'La papelera está vacía.';
    s.trash.forEach(function(c){var row=document.createElement('div'),p=document.createElement('p');row.className='clip';p.textContent=c.name;row.appendChild(p);row.appendChild(button('Restaurar',function(){act('restore',{name:c.name});}));$('trash').appendChild(row);});
    $('storage-state').textContent=s.storage.used_gb+' GB usados de '+s.storage.quota_gb+' GB · '+s.storage.free_gb+' GB libres en disco · máximo '+s.storage.max_clips+' clips activos.';
    if(document.activeElement!==$('quota'))$('quota').value=s.storage.quota_gb;if(document.activeElement!==$('max-clips'))$('max-clips').value=s.storage.max_clips;
    var liveStatus=s.live.status+' · '+s.live.processed+' bloques procesados en esta sesión · '+s.live.backlog+' pendientes';
    if(!supportsClipSettings())liveStatus+=' · Actualiza Julio Clip en Windows para usar los nuevos controles.';
    else if(s.live.running&&s.live.clip_seconds){
      $('clip-duration').value=String(s.live.clip_seconds);
      $('clips-per-block').value=String(s.live.clips_per_block);
      if(feature('profiles'))$('live-profile').value=s.live.profile||'auto';
      if(supportsEditor())$('live-subtitles').checked=Boolean(s.live.subtitles);
      liveStatus+=' · Hasta '+s.live.clips_per_block+' por bloque, '+s.live.clip_seconds+' s por clip.';
    }
    if(supportsFastMode()&&s.live.running){
      $('live-fast').checked=s.live.fast_mode;
      liveStatus+=' · '+(s.live.fast_mode?'Rápido':'Normal')+' · bloques de ~'+s.live.block_seconds/60+' min';
    }
    showCaptureMode();
    $('live-state').textContent=liveStatus;$('live-stop').disabled=!s.live.running;
    $('live-activity').hidden=!(s.live.running&&s.live.monitor&&s.live.monitor.stage==='transcribing');
    $('live-activity').textContent=$('stage-transcribing-detail').textContent;
    var analyzed=s.published_job&&s.published_job.action==='analyze'&&s.published_job.status==='complete';
    $('suggestions').textContent=s.suggestions.length?'':analyzed?
      'No se encontraron momentos que pasaran el filtro.':'Importa un video y busca momentos destacados.';
    s.suggestions.forEach(function(c){if(c.rejected||(window.JulioStudio&&window.JulioStudio.isRejected(c)))return;var row=document.createElement('div'),p=document.createElement('p');row.className='suggestion';p.textContent=c.start.toFixed(1)+'–'+c.end.toFixed(1)+' s · '+c.text+(typeof c.score==='number'?' · Interés estimado '+c.score+'/100':'')+(c.reason?' · '+c.reason:'');row.appendChild(p);row.appendChild(button('Aceptar · Usar tiempos',function(){$('start').value=c.start;$('end').value=c.end;$('start').focus();if(window.JulioStudio)window.JulioStudio.accept(c);}));row.appendChild(button('Rechazar',function(){c.rejected=true;row.remove();if(window.JulioStudio)window.JulioStudio.reject(c);}));$('suggestions').appendChild(row);});
  }
  function refresh(){
    if(!available()||refreshing)return;
    refreshing=true;
    transport('state').then(render).catch(function(e){$('connection').textContent='● Sin conexión';$('status').textContent=e.message;lock(true);})
      .then(function(){refreshing=false;});
  }
  if(local){$('link').hidden=true;$('unlink').hidden=true;lock(true);fetch('/api/session').then(function(r){if(!r.ok)throw Error();return r.json();}).then(function(d){token=d.token;configureDesktop(d);requirements(d.requirements);note(desktop?'Tu estudio está abierto. Los clips se guardan en este equipo.':'Modo local. Revisa las herramientas antes de procesar.');refresh();}).catch(function(){note('No se pudo iniciar la sesión local.');lock(true);});}
  else{$('connection').textContent='● Demostración / sin vincular';note('Sin conexión. Abre Julio Clip y vincula esta página en el mismo equipo para procesar.');$('status').textContent='Las funciones reales requieren vinculación y dependencias.';}
  window.Julio={transport:transport,refresh:refresh,openEditor:openEditor,act:act,
    preview:function(){if(editor){editor.previewRequested=true;$('editor-save').onclick();}},
    editorPayload:function(){if(!editor)return null;var d=editorDraft();if(!d)return null;delete d.duration;d.name=editor.clip.name;d.subtitles=$('editor-subtitles').checked;d.format=$('editor-format').value||'original';applySubtitles(d,'editor');if(editor.captionFields&&editor.captionFields.length)d.caption_edits=editor.captionFields.map(function(f){return f.value;});return addStyling(d,'editor');},
    state:function(){return lastState;},caption:function(){return captionSettings('caption');},
    setCaption:function(s){['color','size','position','font','accent','outline','shadow','reveal'].forEach(function(k){if(s[k]!==undefined)$('caption-'+k).value=String(s[k]);});$('caption-offset').value=String(s.offset_ms||0);$('caption-animations').checked=s.animations!==false;captionThemes.forEach(function(t,i){if(t[0]===s.theme)$('caption-catalog').children[i].onclick();});captionDemo('caption');},
    setEditorCaption:function(s){['color','size','position','font','accent','outline','shadow','reveal'].forEach(function(k){if(s[k]!==undefined)$('edit-caption-'+k).value=String(s[k]);});$('edit-caption-offset').value=String(s.offset_ms||0);$('edit-caption-animations').checked=s.animations!==false;captionThemes.forEach(function(t,i){if(t[0]===s.theme)$('edit-caption-catalog').children[i].onclick();});captionDemo('edit-caption');},
    publishedPayload:function(){var d=mark();d.subtitles=$('export-subtitles').checked;applySubtitles(d,'export');d.format=$('published-format').value||'original';return addStyling(d,'design');}};
  setInterval(function(){if(!local&&linked&&(!bridge||bridge.closed))disconnect();refresh();},2000);
}());
