/* HA Live Voice: prepare playback in the dashboard's real tap handler.
   No microphone, network call, or audio playback before explicit launch. */
(() => {
  const name='__haLiveVoicePlaybackV1';
  const route='/app/01c80471_ha_live_voice/live';
  if(window[name])return;
  let lease=null;
  function dispose(l){
    if(!l||l.closed)return;
    l.closed=true;clearTimeout(l.timer);
    try{l.source?.disconnect();}catch(_){}
    l.source=null;l.ctx.close().catch(()=>{});
    if(lease===l)lease=null;
  }
  function prepare(){
    if(navigator.userActivation&&!navigator.userActivation.isActive)return;
    if(lease)dispose(lease);
    const Audio=window.AudioContext||window.webkitAudioContext;
    if(!Audio)return;
    try{
      const ctx=new Audio();
      const l={ctx,closed:false,source:null,claimed:false,timer:null};
      lease=l;
      l.resuming=ctx.resume().then(()=>true,()=>false);
      l.timer=setTimeout(()=>dispose(l),45000);
    }catch(_){}
  }
  // Existing native shortcut emits hass-action before its navigate handler.
  // Limit this listener to the exact Live Voice shortcut and a tap.
  window.addEventListener('hass-action',e=>{
    const d=e.detail,a=d?.config?.tap_action;
    if(d?.action==='tap'&&a?.action==='navigate'&&a.navigation_path===route)prepare();
  },true);
  window[name]=Object.freeze({
    claim(){
      const l=lease;
      if(!l||l.closed||l.claimed)return null;
      l.claimed=true;clearTimeout(l.timer);
      l.timer=setTimeout(()=>dispose(l),120000);
      return Object.freeze({
        async play(stream){
          const ok=await Promise.race([l.resuming,new Promise(resolve=>setTimeout(()=>resolve(false),500))]);
          if(!ok||l.closed||l.ctx.state!=='running')return false;
          try{
            l.source?.disconnect();
            l.source=l.ctx.createMediaStreamSource(stream);
            l.source.connect(l.ctx.destination);
            clearTimeout(l.timer);
            return true;
          }catch(_){return false;}
        },
        close(){dispose(l);}
      });
    }
  });
  window.addEventListener('location-changed',()=>{
    if(lease?.claimed&&!location.pathname.startsWith('/app/01c80471_ha_live_voice'))dispose(lease);
  });
  window.addEventListener('pagehide',()=>dispose(lease));
})();
