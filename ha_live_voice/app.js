/* WebRTC and client handoff protocol based on Synero/hermes-live-voice (MIT). */
'use strict';
const $ = id => document.getElementById(id);
let csrf, pc, dc, stream, session, timer, loginTimer, idle = 45, last = 0;
let busy = false, starting = false, generation = 0, turn = '', lastUser = '';
let seen = new Set();
const status = text => { $('status').textContent = text; };
const log = text => { $('log').textContent = ($('log').textContent + '\n' + text).slice(-8000); $('log').scrollTop = $('log').scrollHeight; };
async function api(path, body, keepalive = false) {
  const opts = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Voice-CSRF':csrf}, body:JSON.stringify(body), keepalive};
  const res = await fetch('api/' + path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Anfrage fehlgeschlagen');
  return data;
}
async function refresh() {
  const s = await api('status');
  csrf = s.csrf; idle = s.idle_seconds;
  $('voice').value = s.voice;
  $('device').hidden = !s.login_code; $('code').textContent = s.login_code || '';
  $('start').disabled = !s.signed_in || starting || !!session;
  if (!session && !starting) status(s.signed_in ? 'Bereit. Mikrofon startet erst nach Tastendruck.' : 'Bitte mit ChatGPT anmelden.');
  if (s.signed_in) {clearInterval(loginTimer); loginTimer = null;}
}
$('login').onclick = async () => {
  try {await api('login', {}); clearInterval(loginTimer); loginTimer = setInterval(() => refresh().catch(e=>status(e.message)), 2500); await refresh();}
  catch(e) {status(e.message);}
};
function respond(channel, item, text) {
  if (channel?.readyState === 'open') channel.send(JSON.stringify({type:'delegation.context.append', delegation_item_id:item, content:[{type:'input_text',text}]}));
}
async function event(msg, channel, ownSession) {
  if (session !== ownSession || !session) return;
  const t = msg.type;
  if (['input_transcript.added','output_transcript.added','turn.created','turn.delta','turn.done'].includes(t)) last = Date.now();
  if (t === 'turn.created' && msg.turn?.role === 'assistant') turn = msg.turn.id || '';
  if (t === 'turn.done' && msg.turn?.role === 'assistant') turn = '';
  if (t === 'turn.done' && msg.turn?.role === 'user' && msg.turn.transcript) lastUser = msg.turn.transcript;
  if (t === 'session.usage.updated' && msg.usage?.audio_duration_ms != null) $('usage').textContent = 'Audio dieser Sitzung: ' + Math.round(msg.usage.audio_duration_ms / 1000) + ' s';
  if (t === 'error') { status('Live-Verbindung meldet einen Fehler.'); return; }
  if (t !== 'delegation.created') return;
  const item = msg.item?.id;
  const text = (msg.item?.content || []).map(x=>x.text || '').join('').trim() || lastUser;
  if (!item || seen.has(item)) return;
  seen.add(item);
  if (!text || busy) {respond(channel,item,'Keine weitere Aktion ausgeführt. Bitte nach Abschluss erneut fragen.'); return;}
  busy = true; status('Hausassistent arbeitet …'); log('Du: '+text);
  try {
    const r = await api('delegate',{id:ownSession,item,text});
    log('Hausassistent: '+r.text);
    respond(channel,item,'Ergebnis des Hausassistenten (nicht ergänzen): '+r.text);
  } catch(e) {respond(channel,item,'Keine bestätigte Ausführung. Bitte nicht automatisch wiederholen.'); log(e.message);}
  finally {busy=false; last=Date.now(); if(session===ownSession)status('Live · hört zu');}
}
async function stop() {
  generation++;
  const id=session; session=null; starting=false;
  clearInterval(timer); timer=null;
  if (dc) dc.close(); dc=null;
  if (pc) pc.close(); pc=null;
  if (stream) stream.getTracks().forEach(t=>t.stop()); stream=null;
  $('audio').srcObject=null;
  $('stop').disabled=true; $('interrupt').disabled=true;
  status('Gespräch beendet.');
  if(id) {try {await api('stop',{id},true);} catch(e){status('Mikrofon aus. Serverende nicht bestätigt.');}}
  try {await refresh();}catch(e){status(e.message);}
}
$('start').onclick = async () => {
  if(starting || session) return;
  starting=true; const gen=++generation;
  $('start').disabled=true; $('stop').disabled=false; $('log').textContent=''; $('usage').textContent='';
  status('Mikrofon wird geöffnet …');
  try {
    if(!navigator.mediaDevices?.getUserMedia) throw new Error('HTTPS und Mikrofonfreigabe erforderlich.');
    const mic=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    if(gen!==generation){mic.getTracks().forEach(t=>t.stop()); return;}
    stream=mic;
    const peer=new RTCPeerConnection(); pc=peer;
    stream.getTracks().forEach(t=>peer.addTrack(t,stream));
    const channel=peer.createDataChannel('oai-events'); dc=channel;
    seen=new Set(); lastUser=''; turn=''; busy=false;
    peer.ontrack=e=>{ $('audio').srcObject=e.streams[0] || new MediaStream([e.track]); $('audio').play().catch(()=>status('Bitte Audio-Wiedergabe erlauben.')); };
    peer.onconnectionstatechange=()=>{if(gen===generation && ['failed','closed'].includes(peer.connectionState)) stop();};
    await peer.setLocalDescription(await peer.createOffer());
    status('Live-Sitzung wird aufgebaut …');
    const r=await api('start',{offer:peer.localDescription.sdp,voice:$('voice').value});
    if(gen!==generation){await api('stop',{id:r.id},true).catch(()=>{});return;}
    session=r.id;
    channel.onmessage=e=>{try{event(JSON.parse(e.data),channel,r.id).catch(()=>{});}catch(_){}};
    await peer.setRemoteDescription({type:'answer',sdp:r.answer});
    starting=false; last=Date.now(); $('interrupt').disabled=false;
    status('Live · hört zu');
    timer=setInterval(()=>{
      if(!busy && Date.now()-last>idle*1000){stop();return;}
      if(!busy && session===r.id)api('ping',{id:r.id}).catch(()=>stop());
    },5000);
  } catch(e){await stop();status(e.message);}
};
$('interrupt').onclick=async()=>{
  if(!session || !turn)return;
  try{await api('interrupt',{id:session,turn});status('Unterbrochen · hört zu');}catch(e){status(e.message);}
};
$('stop').onclick=stop;
window.addEventListener('pagehide',()=>{if(stream)stream.getTracks().forEach(t=>t.stop());if(pc)pc.close();if(session)api('stop',{id:session},true).catch(()=>{});});
refresh().catch(e=>status(e.message));
