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
if(typeof module!=='undefined'&&module.exports){module.exports={Activity,mergeText};}
else {
const $=id=>document.getElementById(id);
let csrf,pc,dc,stream,session,timer,pingTimer,loginTimer,idle=10;
let busy=false,starting=false,generation=0,turn='',lastUser='',signedIn=false,ended=false;
let seen=new Set(),activity=new Activity(),messages=[],ctx,localAnalyser,remoteAnalyser,localSource,remoteSource;
let closing=false,localHot=0;
function status(text,mode='ready'){ $('status').textContent=text; $('wave').dataset.mode=mode; }
function controls(){
  const active=!!session||starting;
  $('start').hidden=active;$('start').disabled=!signedIn||active;
  $('stop').hidden=!active;$('stop').disabled=!active;
  $('interrupt').hidden=!session||!turn;$('interrupt').disabled=!session||!turn;
  $('voice').disabled=active;$('login').hidden=signedIn;
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
  const s=await api('status');csrf=s.csrf;idle=s.idle_seconds;signedIn=s.signed_in;
  if(!starting&&!session){$('voice').value=s.voice;voiceLabel();}
  $('device').hidden=!s.login_code;$('code').textContent=s.login_code||'';
  if(!signedIn){$('settings').hidden=false;$('settings-toggle').setAttribute('aria-expanded','true');}
  controls();
  if(!session&&!starting&&!ended)status(signedIn?'Bereit zum Gespräch':'Bitte mit ChatGPT anmelden');
  if(s.signed_in){clearInterval(loginTimer);loginTimer=null;}
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
function tick(){
  if(!session)return;const now=Date.now();
  const remote=rms(remoteAnalyser)>.008;
  const local=rms(localAnalyser)>.035&&!remote;
  localHot=local?localHot+1:0;
  if(remote)activity.output(now);
  if(localHot>=2)activity.touch(now);
  const localSpeaking=activity.user||localHot>=2;
  const remoteSpeaking=activity.bot||remote;
  if(busy)status('Hausassistent arbeitet …','work');
  else if(localSpeaking)status('Ich höre dich','user');
  else if(remoteSpeaking||turn)status('Hausassistent spricht','speak');
  else if(now<activity.waitUntil)status('Antwort wird vorbereitet …','work');
  else status('Ich höre zu','listen');
  const remaining=activity.remaining(now,idle,busy||localSpeaking||remoteSpeaking||!!turn);
  $('hint').textContent=remaining===null?'':'Automatisches Ende in '+remaining+' s';
  // A stale assistant turn ID must not keep the microphone open forever.
  if(turn&&now-activity.last>120000){turn='';controls();}
  if(activity.canEnd(now,idle,busy||localSpeaking||remoteSpeaking||!!turn))stop('Gespräch automatisch beendet.');
}
async function stop(reason='Gespräch beendet.'){
  generation++;const id=session;session=null;starting=false;ended=true;turn='';busy=false;
  clearInterval(timer);clearInterval(pingTimer);timer=pingTimer=null;
  if(dc)dc.close();dc=null;if(pc)pc.close();pc=null;
  if(stream)stream.getTracks().forEach(t=>t.stop());stream=null;
  $('audio').srcObject=null;localSource?.disconnect();remoteSource?.disconnect();localSource=remoteSource=localAnalyser=remoteAnalyser=null;
  if(ctx){ctx.close().catch(()=>{});ctx=null;}controls();status(reason);$('hint').textContent='Mikrofon aus';
  if(id){try{await api('stop',{id},true);}catch(e){status('Mikrofon aus. Serverende nicht bestätigt.');}}
}
$('start').onclick=async()=>{
  if(starting||session||closing)return;
  starting=true;ended=false;const gen=++generation;controls();clearMessages();$('usage').textContent='';$('hint').textContent='';$('settings').hidden=true;$('settings-toggle').setAttribute('aria-expanded','false');
  status('Mikrofon wird geöffnet …','work');
  try{
    if(!navigator.mediaDevices?.getUserMedia)throw new Error('HTTPS und Mikrofonfreigabe erforderlich.');
    try{const Audio=window.AudioContext||window.webkitAudioContext;if(Audio){ctx=new Audio();ctx.resume().catch(()=>{});}}catch(_){}
    const mic=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    if(gen!==generation){mic.getTracks().forEach(t=>t.stop());return;}
    stream=mic;meter(mic,'user');
    const peer=new RTCPeerConnection();pc=peer;stream.getTracks().forEach(t=>peer.addTrack(t,stream));
    const channel=peer.createDataChannel('oai-events');dc=channel;
    seen=new Set();lastUser='';turn='';busy=false;localHot=0;activity=new Activity();
    peer.ontrack=e=>{const remote=e.streams[0]||new MediaStream([e.track]);$('audio').srcObject=remote;meter(remote,'assistant');$('audio').play().catch(()=>status('Bitte Audio-Wiedergabe erlauben.'));};
    peer.onconnectionstatechange=()=>{if(gen===generation&&['failed','closed'].includes(peer.connectionState))stop('Live-Verbindung beendet.');};
    await peer.setLocalDescription(await peer.createOffer());if(gen!==generation)return;
    status('Live-Sitzung wird aufgebaut …','work');
    const r=await api('start',{offer:peer.localDescription.sdp,voice:$('voice').value});
    if(gen!==generation){await api('stop',{id:r.id},true).catch(()=>{});return;}
    session=r.id;channel.onmessage=e=>{try{event(JSON.parse(e.data),channel,r.id).catch(()=>{});}catch(_){}};
    await peer.setRemoteDescription({type:'answer',sdp:r.answer});
    if(gen!==generation)return;
    starting=false;activity.touch();controls();status('Ich höre zu','listen');
    timer=setInterval(tick,250);
    pingTimer=setInterval(()=>{if(!busy&&session===r.id)api('ping',{id:r.id}).catch(()=>stop('Verbindung unterbrochen.'));},5000);
  }catch(e){if(gen===generation){await stop();status(e.message);}}
};
$('interrupt').onclick=async()=>{if(!session||!turn)return;try{await api('interrupt',{id:session,turn});turn='';activity.speech('assistant',false);controls();status('Unterbrochen · ich höre zu','listen');}catch(e){note(e.message);}};
$('stop').onclick=()=>stop();
$('close').onclick=async()=>{closing=true;await stop();if(window.parent!==window)window.parent.postMessage({type:'home-assistant/navigate',path:'/family-dashboard/home'},location.origin);else location.assign('/family-dashboard/home');};
window.addEventListener('pagehide',()=>{generation++;clearInterval(timer);clearInterval(pingTimer);if(stream)stream.getTracks().forEach(t=>t.stop());if(pc)pc.close();if(session)api('stop',{id:session},true).catch(()=>{});});
refresh().catch(e=>status(e.message));
}
