/* HA Live Voice / Kiosk Satellite bridge. No audio capture, network traffic, or Cloud session in this module. Scoped to one assigned tablet. */
function installWakeBridge(w, d) {
  'use strict';
  const SAT='assist_satellite.family_dashboard_tablet';
  const BASE='/app/01c80471_ha_live_voice';
  const LIVE=BASE+'/live';
  const key='__haLiveWakeBridgeV1';
  const state={phase:'idle',lastError:null,launches:0};
  if(w[key])return w[key];
  const native=()=>w.kioskSatellite;
  const settings=()=>w.__vsExternalSettings;
  const hass=()=>d.querySelector('home-assistant')?.hass;
  const entityState=id=>hass()?.states?.[id]?.state;
  const bound=()=>{
    try{return native()?.platform==='kiosksatellite'&&settings()?.get()?.satellite===SAT;}
    catch(_){return false;}
  };
  const enabled=()=>bound()&&entityState('switch.family_dashboard_tablet_mute')==='off'&&
    /^On Device \(/.test(entityState('select.family_dashboard_tablet_wake_word_detection')||'');
  const onLive=()=>w.location.pathname===BASE||w.location.pathname.startsWith(BASE+'/');
  const onFamily=()=>w.location.pathname==='/family-dashboard'||w.location.pathname.startsWith('/family-dashboard/');
  function report(error){state.lastError=error;w.console?.warn('[HA Live Wake]',error);}
  function navigate(){
    w.history.pushState(null,'',LIVE);
    w.dispatchEvent(new w.CustomEvent('location-changed',{detail:{replace:false}}));
  }
  let resumeNeeded=false;
  let resumeTimer=null;
  function resume(){
    if(resumeTimer)w.clearTimeout(resumeTimer);
    state.phase='resuming';
    resumeTimer=w.setTimeout(()=>{
      resumeTimer=null;
      if(onLive())return;
      if(resumeNeeded&&bound()){
        try{settings().startEngine();}catch(_){report('Lokale Erkennung konnte nicht neu gestartet werden.');}
      }
      resumeNeeded=false;state.phase='idle';
    },700);
  }
  async function launch(){
    if(state.phase!=='idle')return;
    if(!enabled()||!settings()?.get()?.engine?.running)return;
    state.phase='releasing';state.lastError=null;
    resumeNeeded=true;
    let timeout=null;
    try{
      if(typeof native()?.releaseWakeWord!=='function')throw new Error('Native Mikrofonfreigabe fehlt');
      // Stop native capture and wait for confirmation before WebRTC opens its mic.
      await Promise.race([
        Promise.resolve(native().releaseWakeWord({reason:'browser'})),
        new Promise((_,reject)=>{timeout=w.setTimeout(()=>reject(new Error('Zeitlimit Mikrofonfreigabe')),4000);})
      ]);
      if(!bound())throw new Error('Satellit nicht mehr zugeordnet');
      settings().stopEngine();
      state.phase='live';state.launches++;
      if(!onLive())navigate();
    }catch(_){
      report('Live Voice konnte das Mikrofon nicht übernehmen. Lokale Erkennung wird neu gestartet.');
      try{settings()?.stopEngine();}catch(_){}
      resume();
    }finally{if(timeout!==null)w.clearTimeout(timeout);}
  }
  function wake(e){
    if(!enabled()||!onFamily()&&!onLive())return;
    // Capture before the upstream native wake listener can start its Assist pipeline.
    e.stopImmediatePropagation();
    if(state.phase==='idle'&&!onLive())void launch();
  }
  function route(){
    if(state.phase==='live'&&!onLive())resume();
  }
  function manual(e){
    const detail=e.detail,action=detail?.config?.tap_action;
    if(detail?.action!=='tap'||action?.action!=='navigate'||action.navigation_path!==LIVE)return;
    if(!enabled()||!settings()?.get()?.engine?.running)return;
    e.stopImmediatePropagation();
    if(state.phase==='idle')void launch();
  }
  w.addEventListener('kiosksatellite:wakeword',wake,true);
  w.addEventListener('hass-action',manual,true);
  w.addEventListener('location-changed',route);
  w.addEventListener('popstate',route);
  w[key]=Object.freeze({version:'1.0.0',getStatus:()=>({bound:bound(),enabled:enabled(),...state})});
  return w[key];
}
if(typeof window!=='undefined')installWakeBridge(window,document);
