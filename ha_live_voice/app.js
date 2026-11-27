/* WebRTC and client handoff protocol based on Synero/hermes-live-voice (MIT). */
'use strict';
// V3 streams transcript fragments; speech events and actual audio extend the idle window.
class Activity {
  constructor(now=Date.now()){this.last=now;this.waitUntil=0;this.user=false;this.bot=false;this.userAt=0;this.botAt=0;}
  touch(now=Date.now()){this.last=now;}
  input(now=Date.now()){this.touch(now);this.waitUntil=now+120000;}
  output(now=Date.now()){this.touch(now);this.waitUntil=0;}
  speech(role,on,now=Date.now()){
    if(role==='user'){this.user=on;this.userAt=now;this.input(now);}
    else{this.bot=on;this.botAt=now;this.output(now);}
  }
  expireFlags(now){if(this.user&&now-this.userAt>120000)this.user=false;if(this.bot&&now-this.botAt>120000)this.bot=false;}
  canEnd(now,idle,busy){this.expireFlags(now);return !busy&&!this.user&&!this.bot&&now>=this.waitUntil&&now-this.last>=idle*1000;}
  remaining(now,idle,busy){return busy||this.user||this.bot||now<this.waitUntil?null:Math.max(0,Math.ceil((idle*1000-(now-this.last))/1000));}
}
function mergeText(current,delta,final=false){
  if(typeof delta!=='string'||!delta.trim()&&!current)return current;
  if(final){const t=delta.trim();if(!current||t.length>=current.trim().length)return t;return current;}
  return current+delta;
}
// A dedicated dashboard URL requests a single automatic start. The normal app URL stays manual.
function wantsAutoStart(path){return typeof path==='string'&&/^\/app\/01c80471_ha_live_voice\/live\/?$/.test(path);}
function transportReady(peer,channel){return peer?.connectionState==='connected'&&channel?.readyState==='open';}
if(typeof module!=='undefined'&&module.exports){module.exports={Activity,mergeText,wantsAutoStart,transportReady};}
else {
const $=id=>document.getElementById(id);
let csrf,pc,dc,stream,session,timer,pingTimer,loginTimer,idle=10;
let busy=false,starting=false,generation=0,turn='',lastUser='',signedIn=false,ended=false;
let seen=new Set(),activity=new Activity(),messages=[],ctx,localAnalyser,remoteAnalyser,localSource,remoteSource;
let dashboardOutput=null,outputTimer=null,remoteAudioStream=null,outputAttempt=0;
let captureNode=null,captureSource=null,captureDestination=null,buffering=false,captureTimer=null;
let closing=false,localHot=0,autoLaunch=false,autoConsumed=false,haveStatus=false,ready=false,readyMs=0,readyTimer=null,setupAt=0,stopPending=null,playBlocked=false;
const APP_PATH='/app/01c80471_ha_live_voice', HOME_PATH='/family-dashboard/home';
function parentPath(){try{return window.parent.location.pathname;}catch(_){return '';}}
autoLaunch=wantsAutoStart(parentPath());
function navigate(path,replace=false){
  if(window.parent!==window){
    try{window.parent.postMessage({type:'home-assistant/navigate',path,options:{replace}},location.origin);}
    catch(_){location.assign(path);}
  }else if(replace)location.replace(path);else location.assign(path);
}
function maybeAutoStart(){
  if(!autoLaunch||autoConsumed||!haveStatus||!signedIn||starting||session||closing||document.hidden)return;
  autoConsumed=true;
  // Consume the launch URL so refreshing the app does not reopen the microphone.
  navigate(APP_PATH,true);
  startSession();
}
function launchFromRoute(e){
  if(e.source!==window.parent||e.origin!==location.origin||e.data?.type!=='home-assistant/properties')return;
  const path=e.data.route?.path;
  if(path==='/live'||path==='/live/'||wantsAutoStart(path))autoLaunch=true;
  maybeAutoStart();
}
window.addEventListener('message',launchFromRoute);
window.addEventListener('visibilitychange',maybeAutoStart);
if(window.parent!==window)window.parent.postMessage({type:'home-assistant/subscribe-properties'},location.origin);
function claimDashboardOutput(){
  try{return window.parent!==window?window.parent.__haLiveVoicePlaybackV1?.claim()||null:null;}catch(_){return null;}
}
function releaseDashboardOutput(){
  clearTimeout(outputTimer);outputTimer=null;outputAttempt++;
  dashboardOutput?.close();dashboardOutput=null;remoteAudioStream=null;
}
function playNative(gen,manual=false){
  if(gen!==generation||!remoteAudioStream)return;
  const el=$('audio'),attempt=++outputAttempt;
  el.srcObject=remoteAudioStream;
  el.play().then(()=>{
    if(gen!==generation||attempt!==outputAttempt)return;
    clearTimeout(outputTimer);playBlocked=false;controls();
  }).catch(()=>{
    if(gen!==generation||attempt!==outputAttempt)return;
    if(manual){playBlocked=true;controls();return;}
    // Track may not yet be flowing. Retry once before showing the fallback.
    clearTimeout(outputTimer);outputTimer=setTimeout(()=>{
      if(gen!==generation||attempt!==outputAttempt)return;
      el.play().then(()=>{if(gen===generation&&attempt===outputAttempt){playBlocked=false;controls();}}).catch(()=>{if(gen===generation&&attempt===outputAttempt){playBlocked=true;controls();}});
    },400);
  });
}
async function playRemote(remote,gen){
  remoteAudioStream=remote;
  const lease=dashboardOutput;
  if(lease){
    let ok=false;
    try{ok=await lease.play(remote);}catch(_){}
    if(gen!==generation||remoteAudioStream!==remote){lease.close();return;}
    if(ok){playBlocked=false;controls();return;}
    lease.close();if(dashboardOutput===lease)dashboardOutput=null;
  }
  playNative(gen);
}
function unlockAudio(){
  if(ctx?.state==='suspended')ctx.resume().catch(()=>{});
  if(dashboardOutput){dashboardOutput.close();dashboardOutput=null;}
  playNative(generation,true);
}
function readyTone(){
  if(!ctx||ctx.state!=='running')return;
  try{
    const o=ctx.createOscillator(),g=ctx.createGain(),t=ctx.currentTime;
    o.frequency.value=740;g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(.035,t+.015);g.gain.exponentialRampToValueAtTime(.0001,t+.16);
    o.connect(g);g.connect(ctx.destination);o.start(t);o.stop(t+.18);
  }catch(_){}
}
function status(text,mode='ready'){ $('status').textContent=text; $('wave').dataset.mode=mode; }
function controls(){
  const active=!!session||starting||!!stopPending;
  $('start').hidden=active;$('start').disabled=!signedIn||active;
  $('stop').hidden=!active;$('stop').disabled=!active;
  $('interrupt').hidden=!session||!turn;$('interrupt').disabled=!session||!turn;
  $('voice').disabled=active;$('login').hidden=signedIn;$('unlock-audio').hidden=!playBlocked;
}
function voiceLabel(){const v=$('voice').value;$('voice-label').textContent='Live Voice · '+v.charAt(0).toUpperCase()+v.slice(1);}
function clearMessages(){messages=[];$('log').replaceChildren();const e=document.createElement('div');e.id='empty';e.className='empty';const title=document.createElement('strong');title.textContent='Wie kann ich dir helfen?';e.append(title,'Dein Gespräch erscheint hier.');$('log').append(e);}
function append(role,text,final=false,fallback=false){
  if(typeof text!=='string'||!text.trim()&&(!messages.length||final))return;
  let m=messages[messages.length-1];
  if(!m||m.role!==role||m.closed){
    $('empty')?.remove();const el=document.createElement('article');el.className='message '+role;
    const who=document.createElement('span');who.className='who';who.textContent=role==='user'?'Du':'Hausassistent';
    const bubble=document.createElement('div');bubble.className='bubble';el.append(who,bubble);$('log').append(el);
    m={role,text:'',bubble,el,closed:false,fallback:false};messages.push(m);
    if(messages.length>100)messages.shift().el.remove();
  }
  if(fallback&&m.text.trim())return;
  if(m.fallback&&!fallback){m.text='';m.fallback=false;}
  m.text=mergeText(m.text,text,final||fallback);m.fallback=fallback;
  m.bubble.textContent=m.text; $('log').scrollTop=$('log').scrollHeight;
}
function closeRole(role){const m=messages[messages.length-1];if(m?.role===role)m.closed=true;}
function lastMessage(role){return [...messages].reverse().find(m=>m.role===role);}
function note(text){const el=document.createElement('p');el.className='note';el.textContent=text;$('log').append(el);$('log').scrollTop=$('log').scrollHeight;}
async function api(path,body,keepalive=false){
  const opts=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Voice-CSRF':csrf},body:JSON.stringify(body),keepalive};
  const res=await fetch('api/'+path,opts);const data=await res.json();if(!res.ok)throw new Error(data.error||'Anfrage fehlgeschlagen');return data;
}
async function refresh(){
  const s=await api('status');csrf=s.csrf;idle=s.idle_seconds;signedIn=s.signed_in;haveStatus=true;
  if(!starting&&!session){$('voice').value=s.voice;voiceLabel();}
  $('device').hidden=!s.login_code;$('code').textContent=s.login_code||'';
  if(!signedIn){$('settings').hidden=false;$('settings-toggle').setAttribute('aria-expanded','true');}
  controls();
  if(!session&&!starting&&!ended)status(signedIn?'Bereit zum Gespräch':'Bitte mit ChatGPT anmelden');
  if(s.signed_in){clearInterval(loginTimer);loginTimer=null;}
  maybeAutoStart();
}
$('settings-toggle').onclick=()=>{$('settings').hidden=!$('settings').hidden;$('settings-toggle').setAttribute('aria-expanded',String(!$('settings').hidden));};
$('voice').onchange=voiceLabel;
$('login').onclick=async()=>{try{await api('login',{});clearInterval(loginTimer);loginTimer=setInterval(()=>refresh().catch(e=>status(e.message)),2500);await refresh();}catch(e){status(e.message);}};
function respond(channel,item,text){if(channel?.readyState==='open')channel.send(JSON.stringify({type:'delegation.context.append',delegation_item_id:item,content:[{type:'input_text',text}]}));}
function transcript(role,text,final=false){
  if(!text)return;
  if(role==='user')activity.input();else activity.output();
  append(role,text,final);
}
async function event(msg,channel,ownSession){
  if(session!==ownSession||!session)return;
  const t=msg.type;
  if(t==='input_audio_buffer.speech_started'){activity.speech('user',true);closeRole('assistant');}
  if(t==='input_audio_buffer.speech_stopped')activity.speech('user',false);
  if(t==='output_audio_buffer.started')activity.speech('assistant',true);
  if(['output_audio_buffer.stopped','output_audio_buffer.cleared'].includes(t))activity.speech('assistant',false);
  if(t==='input_transcript.added')transcript('user',msg.item?.text);
  if(t==='output_transcript.added')transcript('assistant',msg.item?.text);
  if(t==='conversation.item.input_audio_transcription.delta')transcript('user',msg.delta);
  if(t==='conversation.item.input_audio_transcription.completed')transcript('user',msg.transcript,true);
  if(t==='response.output_audio_transcript.delta')transcript('assistant',msg.delta);
  if(t==='response.output_audio_transcript.done')transcript('assistant',msg.transcript,true);
  if(['turn.created','turn.delta','turn.done'].includes(t))activity.touch();
  if(t==='turn.created'&&msg.turn?.role==='assistant'){turn=msg.turn.id||'';activity.output();controls();}
  if(t==='turn.done'&&msg.turn?.role==='assistant'){transcript('assistant',msg.turn.transcript,true);turn='';controls();}
  if(t==='turn.done'&&msg.turn?.role==='user'){if(msg.turn.transcript)lastUser=msg.turn.transcript;transcript('user',msg.turn.transcript,true);}
  if(t==='session.usage.updated'&&msg.usage?.audio_duration_ms!=null)$('usage').textContent='Audio dieser Sitzung: '+Math.round(msg.usage.audio_duration_ms/1000)+' s';
  if(t==='error'){note('Live-Verbindung meldet einen Fehler.');return;}
  if(t!=='delegation.created')return;
  const item=msg.item?.id;
  const text=(msg.item?.content||[]).map(x=>x.text||'').join('').trim()||lastUser||lastMessage('user')?.text;
  if(!item||seen.has(item))return;seen.add(item);
  if(!text||busy){respond(channel,item,'Keine weitere Aktion ausgeführt. Bitte nach Abschluss erneut fragen.');return;}
  if(!lastMessage('user')||messages[messages.length-1]?.role==='assistant'&&!lastUser){append('user',text,true,true);}
  busy=true;activity.input();status('Hausassistent arbeitet …','work');
  try{
    const r=await api('delegate',{id:ownSession,item,text});
    if(session!==ownSession)return;
    respond(channel,item,'Ergebnis des Hausassistenten (nicht ergänzen): '+r.text);
  }catch(e){if(session===ownSession){respond(channel,item,'Keine bestätigte Ausführung. Bitte nicht automatisch wiederholen.');note(e.message);}}
  finally{if(session===ownSession){busy=false;activity.input();}}
}
function meter(sourceStream,role){
  if(!ctx)return;
  try{
    const source=ctx.createMediaStreamSource(sourceStream),a=ctx.createAnalyser();a.fftSize=512;source.connect(a);
    if(role==='user'){localSource=source;localAnalyser=a;}else{remoteSource=source;remoteAnalyser=a;}
  }catch(_){}
}
function rms(a){if(!a)return 0;const b=new Float32Array(a.fftSize);a.getFloatTimeDomainData(b);let q=0;for(const x of b)q+=x*x;return Math.sqrt(q/b.length);}
async function prepareBuffer(mic,gen,moduleReady){
  const audio=ctx;
  if(!audio||!audio.audioWorklet||typeof AudioWorkletNode==='undefined')return null;
  try{
    await Promise.race([Promise.all([moduleReady,audio.resume()]),new Promise((_,reject)=>setTimeout(()=>reject(new Error('Audio worklet not ready')),700))]);
    if(gen!==generation||audio!==ctx||audio.state!=='running')return null;
    const source=audio.createMediaStreamSource(mic);
    const node=new AudioWorkletNode(audio,'first-voice-buffer',{numberOfInputs:1,numberOfOutputs:1,outputChannelCount:[1],channelCount:1,channelCountMode:'explicit'});
    const dest=audio.createMediaStreamDestination();
    captureSource=source;captureNode=node;captureDestination=dest;buffering=true;
    node.port.onmessage=e=>{
      if(gen!==generation||node!==captureNode)return;
      if(e.data==='capturing'&&!ready){
        status('Jetzt sprechen · Aufnahme läuft','listen');
        $('hint').textContent='Verbindung wird im Hintergrund aufgebaut';
      }else if(e.data==='live'){
        buffering=false;clearTimeout(captureTimer);captureTimer=null;activity.touch();
      }else if(e.data==='overflow'){
        stop('Verbindungsaufbau zu langsam. Bitte erneut versuchen.');
      }
    };
    node.onprocessorerror=()=>{if(gen===generation)stop('Audioaufnahme fehlgeschlagen. Bitte erneut versuchen.');};
    source.connect(node);node.connect(dest);
    captureTimer=setTimeout(()=>{if(gen===generation&&!ready)stop('Verbindungsaufbau zu langsam. Bitte erneut versuchen.');},12000);
    return dest.stream;
  }catch(_){
    releaseBuffer();
    return null;
  }
}
function releaseBuffer(){
  clearTimeout(captureTimer);captureTimer=null;buffering=false;
  if(captureNode){captureNode.port.onmessage=null;captureNode.onprocessorerror=null;try{captureNode.disconnect();}catch(_){}}
  if(captureSource)try{captureSource.disconnect();}catch(_){}
  if(captureDestination)captureDestination.stream.getTracks().forEach(t=>t.stop());
  captureNode=captureSource=captureDestination=null;
}
function tick(){
  if(!session||!ready)return;const now=Date.now();
  const remote=rms(remoteAnalyser)>.008;
  const local=rms(localAnalyser)>.035&&!remote;
  localHot=local?localHot+1:0;
  if(buffering)activity.touch(now);
  if(remote)activity.output(now);
  if(localHot>=2)activity.touch(now);
  const localSpeaking=activity.user||localHot>=2;
  const remoteSpeaking=activity.bot||remote;
  if(busy)status('Hausassistent arbeitet …','work');
  else if(localSpeaking)status('Ich höre dich','user');
  else if(remoteSpeaking||turn)status('Hausassistent spricht','speak');
  else if(buffering)status('Erster Befehl wird übertragen …','work');
  else if(now<activity.waitUntil)status('Antwort wird vorbereitet …','work');
  else status('Jetzt sprechen · Ich höre zu','listen');
  const remaining=activity.remaining(now,idle,buffering||busy||localSpeaking||remoteSpeaking||!!turn);
  $('hint').textContent=(playBlocked?'Ton bitte freigeben · ':'')+(remaining===null?'':'Automatisches Ende in '+remaining+' s');
  // A stale assistant turn ID must not keep the microphone open forever.
  if(turn&&now-activity.last>120000){turn='';controls();}
  if(activity.canEnd(now,idle,buffering||busy||localSpeaking||remoteSpeaking||!!turn))finish('Gespräch automatisch beendet.');
}
async function stop(reason='Gespräch beendet.'){
  generation++;const id=session;session=null;starting=false;ended=true;turn='';busy=false;ready=false;playBlocked=false;clearTimeout(readyTimer);readyTimer=null;
  clearInterval(timer);clearInterval(pingTimer);timer=pingTimer=null;
  if(dc)dc.close();dc=null;if(pc)pc.close();pc=null;
  if(stream)stream.getTracks().forEach(t=>t.stop());stream=null;
  releaseDashboardOutput();releaseBuffer();$('audio').srcObject=null;localSource?.disconnect();remoteSource?.disconnect();localSource=remoteSource=localAnalyser=remoteAnalyser=null;
  if(ctx){ctx.close().catch(()=>{});ctx=null;}controls();status(reason);$('hint').textContent='Mikrofon aus';
  if(id){try{await api('stop',{id},true);}catch(e){status('Mikrofon aus. Serverende nicht bestätigt.');}}
}
async function finish(reason){
  if(closing)return;closing=true;
  // stop() turns off capture and playback synchronously before awaiting the server.
  const done=stop(reason);stopPending=done;controls();
  await Promise.race([done,new Promise(resolve=>setTimeout(resolve,1500))]);
  navigate(HOME_PATH,true);
}
async function startSession(){
  if(starting||session||closing)return;
  starting=true;ended=false;ready=false;playBlocked=false;setupAt=performance.now();const gen=++generation;dashboardOutput=claimDashboardOutput();controls();clearMessages();$('usage').textContent='';$('hint').textContent='';$('settings').hidden=true;$('settings-toggle').setAttribute('aria-expanded','false');
  status('Mikrofon wird geöffnet …','work');
  try{
    if(!navigator.mediaDevices?.getUserMedia)throw new Error('HTTPS und Mikrofonfreigabe erforderlich.');
    try{const Audio=window.AudioContext||window.webkitAudioContext;if(Audio){ctx=new Audio();ctx.resume().catch(()=>{});}}catch(_){}
    const moduleReady=ctx?.audioWorklet?ctx.audioWorklet.addModule('capture-worklet.js').catch(()=>false):Promise.resolve(false);
    const mic=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    if(gen!==generation){mic.getTracks().forEach(t=>t.stop());return;}
    stream=mic;meter(mic,'user');
    const buffered=await prepareBuffer(mic,gen,moduleReady);
    if(gen!==generation){mic.getTracks().forEach(t=>t.stop());return;}
    const outgoing=buffered||stream;
    if(!buffered){for(const track of stream.getAudioTracks())track.enabled=false;status('Verbindung wird aufgebaut …','work');$('hint').textContent='Bitte auf das Startsignal warten';}
    const peer=new RTCPeerConnection();pc=peer;outgoing.getTracks().forEach(t=>peer.addTrack(t,outgoing));
    const channel=peer.createDataChannel('oai-events');dc=channel;
    seen=new Set();lastUser='';turn='';busy=false;localHot=0;activity=new Activity();
    let remoteSet=false;
    function markReady(){
      if(gen!==generation||!remoteSet||!session||ready||!transportReady(peer,channel))return;
      clearTimeout(readyTimer);readyTimer=null;
      ready=true;starting=false;readyMs=performance.now()-setupAt;
      clearTimeout(captureTimer);captureTimer=null;
      if(captureNode)captureNode.port.postMessage('ready');else for(const track of stream.getAudioTracks())track.enabled=true;
      activity=new Activity();controls();status('Jetzt sprechen · Ich höre zu','listen');
      $('hint').textContent='Verbunden in '+(readyMs/1000).toFixed(1).replace('.',',')+' s';
      $('connection-time').textContent='Verbindungsaufbau: '+(readyMs/1000).toFixed(1).replace('.',',')+' s';
      if(!captureNode)readyTone();
      const id=session;
      timer=setInterval(tick,250);
      pingTimer=setInterval(()=>{if(!busy&&session===id)api('ping',{id}).catch(()=>stop('Verbindung unterbrochen.'));},5000);
    }
    peer.ontrack=e=>{if(gen!==generation||e.track.kind!=='audio')return;const remote=e.streams[0]||new MediaStream([e.track]);meter(remote,'assistant');playRemote(remote,gen);};
    channel.onopen=markReady;
    peer.onconnectionstatechange=()=>{if(gen!==generation)return;if(['failed','closed'].includes(peer.connectionState))stop('Live-Verbindung beendet.');else markReady();};
    await peer.setLocalDescription(await peer.createOffer());if(gen!==generation)return;
    if(!buffering)status('Live-Sitzung wird aufgebaut …','work');
    const r=await api('start',{offer:peer.localDescription.sdp,voice:$('voice').value});
    if(gen!==generation){await api('stop',{id:r.id},true).catch(()=>{});return;}
    session=r.id;channel.onmessage=e=>{try{event(JSON.parse(e.data),channel,r.id).catch(()=>{});}catch(_){}};
    await peer.setRemoteDescription({type:'answer',sdp:r.answer});
    if(gen!==generation)return;
    remoteSet=true;markReady();
    if(!ready)readyTimer=setTimeout(()=>{if(gen===generation&&!ready)stop('Verbindung nicht bereit. Bitte erneut versuchen.');},20000);
  }catch(e){if(gen===generation){await stop();status(e.message);}}
}
$('start').onclick=startSession;
$('unlock-audio').onclick=unlockAudio;
$('interrupt').onclick=async()=>{if(!session||!turn)return;try{await api('interrupt',{id:session,turn});turn='';activity.speech('assistant',false);controls();status('Unterbrochen · ich höre zu','listen');}catch(e){note(e.message);}};
$('stop').onclick=()=>finish('Gespräch beendet.');
$('close').onclick=()=>finish('Gespräch beendet.');
window.addEventListener('pagehide',()=>{generation++;clearInterval(timer);clearInterval(pingTimer);clearTimeout(readyTimer);releaseDashboardOutput();releaseBuffer();if(stream)stream.getTracks().forEach(t=>t.stop());if(pc)pc.close();if(session)api('stop',{id:session},true).catch(()=>{});});
refresh().catch(e=>status(e.message));
}
