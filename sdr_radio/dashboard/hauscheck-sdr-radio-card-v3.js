/* HausCheck SDR UKW Radio Family Card 2026-11-21 v1 */
(() => {
if(customElements.get("hauscheck-sdr-radio-card"))return;
class HausCheckRadioCard extends HTMLElement{
 constructor(){super();this.attachShadow({mode:"open"});this._h=null;this._config={entity:"sensor.sdr_ukw_radio_sdr_radio"};this._initDone=false;this._selected="";this._drag=false;this._covers={};this._failedImages=new Set();this._navTarget=null;this._navAt=0;this._prevFav="";this._playerKey="";this._error="";}
 static getStubConfig(){return {type:"custom:hauscheck-sdr-radio-card",entity:"sensor.sdr_ukw_radio_sdr_radio"};}
 setConfig(c){this._config={...this._config,...c};if(this.isConnected)this._init();}
 connectedCallback(){this._init();}
 set hass(v){this._h=v;if(this._initDone)this._render();}
 getCardSize(){return 5;}
 getLayoutOptions(){return {grid_columns:12,grid_rows:"auto"};}
 _e(tag,cls,txt){const e=document.createElement(tag);if(cls)e.className=cls;if(txt!==undefined)e.textContent=txt;return e;}
 _i(name){const e=document.createElement("ha-icon");e.setAttribute("icon","mdi:"+name);return e;}
 _b(id,name,icon){const e=this._e("button","iconbtn");e.id=id;e.title=name;e.setAttribute("aria-label",name);e.type="button";e.append(this._i(icon));return e;}
 _q(id){return this.shadowRoot.getElementById(id);}
 _attrs(){return this._h?.states?.[this._config.entity]?.attributes||{};}
 _init(){if(this._initDone)return;this._initDone=true;
 const css=this._e("style");css.textContent=`
:host{display:block;min-width:0}*{box-sizing:border-box}[hidden]{display:none!important}
ha-card{display:block;border-radius:19px;overflow:hidden;background:linear-gradient(125deg,#078eaa,#086d99 65%,#18537f);color:white;padding:16px;border:1px solid #ffffff20;box-shadow:none}
button,select,input{font:inherit}button{cursor:pointer;touch-action:manipulation}button:disabled{opacity:.35;cursor:default}
.header,.headright,.stationline,.controls,.output,.vol,.bottom{display:flex;align-items:center;gap:9px}
.heading{font-size:17px;font-weight:650;flex:1}.pill{font-size:10px;font-weight:700;letter-spacing:.07em;padding:6px 7px;border:1px solid #ffffff50;border-radius:8px;white-space:nowrap}.pill.on{background:#0bba9750}
.iconbtn{width:43px;height:43px;display:grid;place-items:center;border:0;border-radius:11px;padding:0;color:inherit;background:transparent;flex-shrink:0}
.iconbtn ha-icon{--mdc-icon-size:25px}.iconbtn:hover{background:#ffffff22}.iconbtn:focus-visible,select:focus-visible{outline:2px solid white;outline-offset:1px}
.hero{display:flex;align-items:center;gap:14px;margin:12px 0 7px;min-height:112px}
.cover{width:112px;height:112px;flex:0 0 112px;border-radius:14px;background:#ffffff23;display:grid;place-items:center;overflow:hidden;position:relative}
.cover img{width:100%;height:100%;object-fit:contain;padding:5px}.cover ha-icon{--mdc-icon-size:52px;opacity:.7}
.details{flex:1;min-width:0}.logo{height:28px;width:28px;object-fit:contain;border-radius:5px}
.station{font-size:14px;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.freq{font-size:11px;opacity:.8;margin:5px 0 7px}.song{font-size:20px;font-weight:720;line-height:1.2;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
.artist{font-size:13px;opacity:.85;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.controls{justify-content:center;gap:14px;margin:6px 0 13px}.controls .iconbtn{height:48px;width:48px}.controls .main{width:56px;height:56px;border-radius:50%;background:#ffffff27;border:1px solid #ffffff33}.controls .main ha-icon{--mdc-icon-size:32px}
.line{height:1px;background:#ffffff45;margin-bottom:11px}
.output{gap:10px;margin-bottom:9px}.outputlabel{font-size:12px;display:flex;align-items:center;gap:5px;white-space:nowrap}.outputlabel ha-icon{--mdc-icon-size:19px}
select{min-width:0;flex:1;min-height:42px;background:#06577b;border:1px solid #ffffff70;border-radius:10px;color:#fff;padding:9px 8px;font-size:13px}
select option{background:#145474;color:white}
.vol{gap:4px}.vol .iconbtn{width:34px;height:34px}.vol .iconbtn ha-icon{--mdc-icon-size:19px}
input[type=range]{flex:1;min-width:0;accent-color:white;min-height:29px;touch-action:pan-y}
.pct{font-size:12px;width:44px;text-align:right;font-variant-numeric:tabular-nums}
.bottom{font-size:11px;opacity:.8;margin-top:8px;justify-content:space-between;gap:12px;min-width:0}.bottom span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
dialog{border:0;border-radius:18px;padding:19px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#222);width:min(480px,calc(100vw - 22px));max-height:83vh;box-shadow:0 15px 65px #0008}
dialog::backdrop{background:#001c30ad;backdrop-filter:blur(3px)}
.modalhead{display:flex;align-items:center;gap:8px;font-size:19px;font-weight:700;margin-bottom:12px}.modalhead strong{flex:1}
dialog .iconbtn{color:var(--primary-text-color)}
.favlist{max-height:52vh;overflow:auto}.favrow{display:flex;align-items:center;gap:9px;min-height:62px;border-bottom:1px solid var(--divider-color,#ddd)}
.favselect{border:0;background:transparent;color:inherit;display:flex;align-items:center;gap:11px;min-width:0;flex:1;text-align:left;padding:5px 0}
.favlogo{height:48px;width:48px;object-fit:contain;border-radius:9px;background:var(--secondary-background-color,#eee);padding:4px}
.favholder{width:48px;height:48px;border-radius:9px;background:var(--secondary-background-color,#eee);display:grid;place-items:center}
.favtxt{flex:1;min-width:0}.favname{font-weight:650;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.favfreq{font-size:12px;color:var(--secondary-text-color,#777)}
.del{border:0;color:var(--secondary-text-color);background:transparent;width:39px;height:40px}
.add{margin-top:13px;min-height:45px;width:100%;color:white;background:var(--primary-color,#087ba0);border:0;border-radius:11px;font-weight:650;padding:10px}
.help{font-size:12px;color:var(--secondary-text-color);margin-top:9px}
@media(max-width:480px){ha-card{padding:12px}.cover{height:90px;width:90px;flex-basis:90px}.hero{gap:10px;min-height:90px}.song{font-size:17px}.controls{gap:8px}.heading{font-size:16px}.output{gap:6px}}
`;this.shadowRoot.append(css);
 const card=this._e("ha-card"),header=this._e("div","header");
 header.append(this._i("radio-fm"),this._e("div","heading","UKW Radio"));
 const live=this._e("span","pill","UKW");live.id="live";header.append(live,this._b("fav","Favoriten","heart-outline"));card.append(header);
 const hero=this._e("div","hero"),art=this._e("div","cover");
 const artIcon=this._i("music-note");artIcon.id="placeholder";art.append(artIcon);
 const cover=this._e("img");cover.id="cover";cover.hidden=true;cover.alt="Titelcover";cover.referrerPolicy="no-referrer";art.append(cover);hero.append(art);
 const info=this._e("div","details"),st=this._e("div","stationline");
 const logo=this._e("img","logo");logo.id="logo";logo.hidden=true;logo.alt="Senderlogo";st.append(logo);
 const station=this._e("span","station","SDR Radio");station.id="station";st.append(station);info.append(st);
 for(const [id,cls,text] of [["freq","freq","99,7 MHz"],["song","song","Radio"],["artist","artist","UKW-Empfang"]]){const e=this._e("div",cls,text);e.id=id;info.append(e);}
 hero.append(info);card.append(hero);
 const ctrl=this._e("div","controls");
 ctrl.append(this._b("prev","Sender zurück","skip-previous"),this._b("stop","Wiedergabe stoppen","stop"));
 const play=this._b("play","Wiedergabe auf ausgewähltem Gerät starten","play");play.classList.add("main");ctrl.append(play,this._b("next","Nächster Sender","skip-next"));card.append(ctrl);
 card.append(this._e("div","line"));
 const row=this._e("div","output"),lab=this._e("span","outputlabel");lab.append(this._i("speaker"),this._e("span",null,"Ausgabe"));
 const select=this._e("select");select.id="device";select.setAttribute("aria-label","Ausgabegerät auswählen");row.append(lab,select);card.append(row);
 const volume=this._e("div","vol"),slider=this._e("input");slider.type="range";slider.id="volume";slider.min="0";slider.max="100";slider.value="0";slider.step="1";slider.setAttribute("aria-label","Lautstärke");
 const pct=this._e("span","pct","–");pct.id="pct";
 volume.append(this._b("minus","Leiser","minus"),slider,this._b("plus","Lauter","plus"),pct);card.append(volume);
 const bottom=this._e("div","bottom"),source=this._e("span",null,"RDS · UKW");source.id="source";
 const ps=this._e("span",null,"Ausgabe gestoppt");ps.id="playstate";bottom.append(source,ps);card.append(bottom);this.shadowRoot.append(card);
 const dlg=this._e("dialog");dlg.id="dialog";const head=this._e("div","modalhead");
 head.append(this._i("radio-fm"),this._e("strong",null,"Lieblingssender"),this._b("close","Schließen","close"));
 dlg.append(head);const list=this._e("div","favlist");list.id="favlist";dlg.append(list);
 const add=this._e("button","add","＋ Aktuellen Sender speichern");add.id="add";dlg.append(add);
 const hint=this._e("div","help","Sender antippen, um ihn zu wählen.");hint.id="hint";dlg.append(hint);this.shadowRoot.append(dlg);
 this._q("fav").onclick=()=>{this._drawFav();dlg.showModal();};this._q("close").onclick=()=>dlg.close();
 dlg.onclick=e=>{if(e.target===dlg)dlg.close();};
 this._q("prev").onclick=()=>this._cycleFavorite(-1);
 this._q("next").onclick=()=>this._cycleFavorite(1);
 this._q("play").onclick=()=>this._cmd({action:"play",entity_id:this._selected});
 this._q("stop").onclick=()=>this._cmd({action:"stop_output",entity_id:this._selected});
 this._q("device").onchange=e=>{this._selected=e.target.value;this._pending=Date.now()+5000;this._cmd({action:"select_output",entity_id:this._selected});this._drawVol();};
 this._q("volume").onpointerdown=()=>this._drag=true;
 this._q("volume").oninput=e=>{this._drag=true;this._q("pct").textContent=e.target.value+" %";};
 this._q("volume").onchange=async e=>{await this._setVol(Number(e.target.value));this._drag=false;};
 this._q("volume").onpointerup=()=>{this._drag=false;};
 this._q("minus").onclick=()=>this._setVol(Number(this._q("volume").value)-2);
 this._q("plus").onclick=()=>this._setVol(Number(this._q("volume").value)+2);
 this._q("add").onclick=()=>this._cmd({action:"add_favorite"});
 this._render();
 }
 async _cmd(obj){
  try{if(!this._h)throw Error("Home Assistant nicht verbunden");
   await this._h.callService("mqtt","publish",{topic:"hauscheck/sdr_radio/command",payload:JSON.stringify(obj),qos:0,retain:false});this._error="";
  }catch(e){this._error=String(e?.message||e);this._q("source").textContent="Fehler: "+this._error;}
 }
 _cycleFavorite(direction){
  const a=this._attrs();
  const items=(a.presets||[]).filter(p=>p&&Number.isFinite(Number(p.frequency)));
  if(!items.length){this._q("source").textContent="Keine Senderfavoriten vorhanden";return;}
  const current=(this._navTarget!==null&&Date.now()-this._navAt<2500)
    ?this._navTarget:Number(a.frequency);
  const index=items.findIndex(p=>Math.abs(Number(p.frequency)-current)<0.055);
  const next=index<0?(direction>0?0:items.length-1):(index+direction+items.length)%items.length;
  const target=Number(items[next].frequency);
  this._navTarget=target;this._navAt=Date.now();
  // Explicit tune only; never start or resume output on its own.
  this._cmd({action:"tune",frequency:target});
 }
 async _setVol(v){
  if(!this._selected)return;
  try{await this._h.callService("media_player","volume_set",{entity_id:this._selected,volume_level:Math.max(0,Math.min(1,Math.round(v)/100))});}
  catch(e){this._q("source").textContent="Lautstärke: "+String(e?.message||e);}
 }
 _img(id,url){
  const element=this._q(id);
  const src=typeof url==="string"&&url.startsWith("https://")&&!this._failedImages.has(url)?url:"";
  if(this._covers[id]===src)return;
  this._covers[id]=src;
  element.hidden=true;
  if(id==="cover")this._q("placeholder").hidden=false;
  if(!src){element.removeAttribute("src");return;}
  element.onload=()=>{
    if(this._covers[id]!==src)return;
    element.hidden=false;
    if(id==="cover")this._q("placeholder").hidden=true;
  };
  element.onerror=()=>{
    if(this._covers[id]!==src)return;
    this._failedImages.add(src);
    this._covers[id]="";
    element.hidden=true;
    element.removeAttribute("src");
    if(id==="cover")this._q("placeholder").hidden=false;
    // Retry with the verified station logo when album art fails;
    // never show a broken image placeholder.
    this._render();
  };
  element.src=src;
 }
 _drawPlayers(){
  const sel=this._q("device");
  const PLAY_MEDIA=131072;
  const candidates=Object.values(this._h?.states||{}).filter(p=>{
    if(!p.entity_id.startsWith("media_player."))return false;
    if(["unknown","unavailable"].includes(p.state))return false;
    if(!(Number(p.attributes?.supported_features||0)&PLAY_MEDIA))return false;
    // These media entities are Tonie figures/queues, not arbitrary MP3 sinks.
    if(/youtube_music_live|kreativ_tonie|toniebox|this_device|uberall/i.test(p.entity_id))return false;
    if(/^(Android|This Device|Überall)$/i.test(String(p.attributes?.friendly_name||"").trim()))return false;
    return true;
  });
  // Multiple HA integrations may represent one physical TV/soundbar.
  // Prefer the canonical entity without trailing _2/_3.
  const unique=new Map();
  for(const p of candidates){
    const group=p.entity_id.replace(/_\d+$/,"");
    const value=(p.entity_id===group?20:0)+
      (p.state==="playing"?2:0)+(p.attributes?.volume_level!==undefined?1:0);
    const prev=unique.get(group);
    if(!prev||value>prev.value)unique.set(group,{p,value});
  }
  const entries=[...unique.values()].map(v=>v.p);
  entries.sort((a,b)=>(a.entity_id==="media_player.ultra_slim_soundbar"?-1:0)-
    (b.entity_id==="media_player.ultra_slim_soundbar"?-1:0)||
    String(a.attributes?.friendly_name||a.entity_id).localeCompare(
      String(b.attributes?.friendly_name||b.entity_id),"de"));
  const key=entries.map(p=>p.entity_id).join("|")+"|"+this._selected;
  if(key!==this._playerKey){
    this._playerKey=key;sel.replaceChildren();
    for(const p of entries){
      const option=this._e("option");
      option.value=p.entity_id;
      option.textContent=p.attributes?.friendly_name||p.entity_id;
      sel.append(option);
    }
    if(this._selected&&!entries.some(p=>p.entity_id===this._selected)){
      const option=this._e("option");
      option.value=this._selected;
      option.textContent=(this._h?.states?.[this._selected]?.attributes?.friendly_name||this._selected)+" (nicht als UKW-Ausgabe geeignet)";
      option.disabled=true;sel.append(option);
    }
  }
  if(sel.value!==this._selected)sel.value=this._selected;
 }
 _drawVol(){
  const player=this._h?.states?.[this._selected],raw=player?.attributes?.volume_level,v=Number(raw);
  const good=raw!==null&&raw!==undefined&&Number.isFinite(v)&&player&&!["unknown","unavailable"].includes(player.state);
  this._q("volume").disabled=!good;this._q("minus").disabled=!good;this._q("plus").disabled=!good;
  if(!this._drag){this._q("volume").value=String(good?Math.round(v*100):0);this._q("pct").textContent=good?Math.round(v*100)+" %":"–";}
 }
 _render(){
  if(!this._initDone||!this._h)return;
  const a=this._attrs(),sensor=this._h.states?.[this._config.entity];
  const ready=!!sensor&&!["unavailable","unknown"].includes(sensor.state);
  const running=!!a.running&&ready,s=a.station||{},song=a.song||{};
  this._q("live").textContent=running?"UKW LIVE":"UKW AUS";
  this._q("live").classList.toggle("on",running);
  this._q("station").textContent=s.name||"SDR Radio";
  this._q("freq").textContent=a.frequency!=null?Number(a.frequency).toLocaleString("de-AT",{minimumFractionDigits:1,maximumFractionDigits:2})+" MHz · "+(a.station_name_source||"UKW"):"Empfang bereit";
  this._q("song").textContent=song.title||(running?"Kein Titel verfügbar":"Radio bereit");
  this._q("artist").textContent=song.artist||(running?"RDS · RadioText":"Sender auswählen und Play drücken");
  const coverCandidate=[song.cover_url,s.favicon].find(u=>
    typeof u==="string"&&u.startsWith("https://")&&!this._failedImages.has(u))||"";
  this._img("cover",coverCandidate);
  this._img("logo",s.favicon);
  if(a.selected_output&&(!this._selected||(!this._pending||Date.now()>this._pending)))this._selected=a.selected_output;
  if(!this._selected)this._selected="media_player.ultra_slim_soundbar";
  this._drawPlayers();this._drawVol();
  const p=this._h.states?.[this._selected],state=p?.state||"unavailable";
  const active=!!a.output_playing&&a.selected_output===this._selected;
  this._q("source").textContent=a.last_command_error?("Radio: "+a.last_command_error):(this._error||song.source||"RDS · UKW");
  this._q("playstate").textContent=active?"▶ Wiedergabe":state==="playing"?"Andere Quelle läuft":state==="paused"?"Pausiert":"Ausgabe gestoppt";
  this._q("play").disabled=!ready;this._q("prev").disabled=!ready||!(a.presets||[]).length;this._q("next").disabled=!ready||!(a.presets||[]).length;
  this._q("stop").disabled=!ready||!active;
  const fav=JSON.stringify(a.presets||[]);if(fav!==this._prevFav){this._prevFav=fav;if(this._q("dialog").open)this._drawFav();}
 }
 _drawFav(){
  const a=this._attrs(),list=this._q("favlist");list.replaceChildren();
  const items=(a.presets||[]).filter(x=>x&&Number.isFinite(Number(x.frequency)));
  this._q("add").disabled=!a.running;
  if(!items.length)list.append(this._e("div","help","Noch keine Favoriten vorhanden. Jetzt einen Sender einstellen und speichern."));
  for(const fav of items){
    const row=this._e("div","favrow"),main=this._e("button","favselect");main.type="button";
    const logo=typeof fav.logo==="string"&&fav.logo.startsWith("https://")&&!this._failedImages.has(fav.logo)?fav.logo:"";
    const placeholder=this._e("span","favholder");placeholder.append(this._i("radio-fm"));
    if(logo){
      const img=this._e("img","favlogo");img.alt="Senderlogo";img.hidden=true;
      img.onload=()=>{img.hidden=false;placeholder.hidden=true;};
      img.onerror=()=>{this._failedImages.add(logo);img.remove();placeholder.hidden=false;};
      img.src=logo;main.append(img,placeholder);
    }else main.append(placeholder);
    const text=this._e("div","favtxt");text.append(this._e("div","favname",fav.station_name||fav.name||"UKW"),this._e("div","favfreq",Number(fav.frequency).toFixed(1).replace(".",",")+" MHz"));
    main.append(text);main.onclick=()=>{this._cmd({action:"tune",frequency:Number(fav.frequency)});this._q("dialog").close();};row.append(main);
    const del=this._e("button","del");del.title="Favorit entfernen";del.append(this._i("delete-outline"));del.onclick=()=>this._cmd({action:"remove_favorite",name:fav.name});
    row.append(del);list.append(row);
  }
  this._q("hint").textContent=a.running?"Aktuell: "+(a.station?.name||"Sender")+" · "+a.frequency+" MHz":"Starte den Radioempfang, um einen Favoriten zu speichern.";
 }
}
customElements.define("hauscheck-sdr-radio-card",HausCheckRadioCard);
window.customCards=window.customCards||[];
window.customCards.push({type:"hauscheck-sdr-radio-card",name:"HausCheck SDR Radio",description:"UKW-Radiokarte mit RDS, Cover, Favoriten und Ausgabegerät."});
})();
