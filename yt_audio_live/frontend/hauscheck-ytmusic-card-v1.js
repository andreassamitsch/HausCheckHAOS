/* YouTube Music Family Card - secure MQTT controls, no browser secrets. */
(()=>{
if(customElements.get("hauscheck-ytmusic-card"))return;
const HUB="sensor.youtube_music_live_youtube_music_live",TOPIC="hauscheck/ytmusic_live/command",PLAY_MEDIA=131072;
const E=(tag,cls,txt)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(txt!==undefined)e.textContent=txt;return e;};
const I=name=>{const e=E("ha-icon");e.setAttribute("icon","mdi:"+name);return e;};
const B=(icon,title)=>{const b=E("button","ib");b.type="button";b.title=title;b.setAttribute("aria-label",title);b.append(I(icon));return b;};
class MusicFamilyCard extends HTMLElement{
 constructor(){super();this.attachShadow({mode:"open"});this._h=null;this._config={entity:HUB};this._ready=false;this._selected="";this._tab="library";this._kind="songs";this._query="";this._listPid="";this._listRequested=0;this._modalKey="";this._playersKey="";this._msg="";this._drag=false;}
 static getStubConfig(){return {type:"custom:hauscheck-ytmusic-card",entity:HUB};}
 setConfig(c){this._config={...this._config,...c};this._init();}
 connectedCallback(){this._init();}
 set hass(v){this._h=v;if(this._ready)this._render();}
 getCardSize(){return 6;}
 getLayoutOptions(){return {grid_columns:12,grid_rows:"auto"};}
 _q(id){return this.shadowRoot.getElementById(id);}
 _a(){return this._h?.states?.[this._config.entity]?.attributes||{};}
 _init(){
  if(this._ready)return;this._ready=true;
  const style=E("style");
  style.textContent=[
":host{display:block;min-width:0}*{box-sizing:border-box}button,select,input{font:inherit}button{cursor:pointer;touch-action:manipulation}button:disabled{opacity:.3;cursor:default}",
"ha-card{display:block;overflow:hidden;border-radius:19px;background:linear-gradient(130deg,#028eab,#086b98 64%,#15527b);color:#fff;border:1px solid #ffffff25;padding:15px}",
".head,.hero,.row,.controls,.extras,.vol,.foot,.modalhead,.tabs,.searchline,.item{display:flex;align-items:center;gap:10px}",
".head{margin-bottom:13px}.brand{font-size:17px;font-weight:750;flex:1}.pill{font-size:11px;border:1px solid #ffffff68;border-radius:7px;padding:4px 7px;font-weight:700}",
".ib{width:42px;height:42px;border:0;border-radius:10px;padding:0;display:grid;place-items:center;background:transparent;color:inherit;flex:0 0 auto}.ib ha-icon{--mdc-icon-size:25px}.ib:focus-visible{outline:2px solid white}.ib.on{background:#ffffff33;color:#bcfff5}",
".hero{min-height:100px}.art{width:100px;height:100px;flex:0 0 100px;background:#ffffff26;border-radius:12px;overflow:hidden;display:grid;place-items:center}.art img{width:100%;height:100%;object-fit:cover}.art ha-icon{--mdc-icon-size:48px}",
".meta{flex:1;min-width:0}.song{font-weight:750;font-size:20px;line-height:1.2;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}.artist{font-size:13px;opacity:.85;margin-top:7px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
".controls{justify-content:center;gap:13px;margin:12px 0 5px}.controls .ib{width:48px;height:48px}.controls .primary{height:58px;width:58px;border-radius:50%;background:#ffffff2d;border:1px solid #ffffff55}.controls .primary ha-icon{--mdc-icon-size:32px}",
".extras{justify-content:center;gap:9px;margin:0 0 13px}.extras .ib{width:45px;height:38px}.line{border:0;border-top:1px solid #ffffff50;margin:12px 0}",
".row{gap:9px}.row span{font-size:12px;white-space:nowrap;display:flex;align-items:center;gap:4px}.output{width:100%;flex:1;min-width:0;min-height:43px;border:1px solid #ffffff70;background:#075474;color:white;border-radius:10px;padding:8px;font-size:13px}.output option{background:#19527a}",
".vol{gap:4px;margin-top:8px}.vol .ib{width:34px;height:35px}.vol .ib ha-icon{--mdc-icon-size:20px}.vol input{flex:1;min-width:0;accent-color:white}.pct{width:42px;text-align:right;font-size:12px}",
".foot{justify-content:space-between;gap:6px;font-size:11px;margin-top:11px;opacity:.83}.foot span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.note{font-size:12px;min-height:13px;margin-top:7px;color:#ffe6a4}",
"dialog{padding:0;border:0;border-radius:18px;width:min(520px,calc(100vw - 16px));max-height:90dvh;overflow:hidden;background:var(--card-background-color,#fff);color:var(--primary-text-color,#222);box-shadow:0 14px 70px #0008}dialog::backdrop{background:#031b34b7;backdrop-filter:blur(3px)}",
".dialogbody{padding:14px;max-height:90dvh;overflow:auto}.modalhead{font-size:18px;font-weight:700;margin-bottom:9px}.modalhead b{flex:1}.modalhead .ib{color:var(--primary-text-color)}",
".tabs{gap:4px;margin-bottom:9px}.tabs button{flex:1;min-height:40px;border:1px solid var(--divider-color,#ddd);border-radius:8px;background:var(--secondary-background-color,#eee);color:var(--primary-text-color,#222);font-size:12px;padding:6px}.tabs button.on{background:#087ca3;color:white}",
".searchline{gap:5px;flex-wrap:wrap;margin-bottom:7px}.searchline input{min-width:90px;flex:1;min-height:43px;border:1px solid var(--divider-color,#ddd);padding:8px;border-radius:8px;background:var(--card-background-color);color:var(--primary-text-color)}.searchline select{min-height:43px;border-radius:8px;border:1px solid var(--divider-color);padding:7px;background:var(--card-background-color);color:var(--primary-text-color)}",
".act{min-height:39px;border:0;border-radius:9px;background:#037ba5;color:white;font-weight:650;padding:8px 11px}",
".result{max-height:54dvh;overflow:auto}.item{padding:7px 0;min-height:57px;border-bottom:1px solid var(--divider-color,#ddd);gap:6px}.item img{width:47px;height:47px;object-fit:cover;border-radius:8px;background:var(--secondary-background-color,#eee)}.desc{min-width:0;flex:1;cursor:pointer}.desc strong,.desc small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.desc strong{font-size:13px}.desc small{font-size:12px;color:var(--secondary-text-color,#888)}.item .ib{width:34px;height:38px;color:var(--primary-text-color)}.item .ib ha-icon{--mdc-icon-size:21px}",
".muted{font-size:12px;color:var(--secondary-text-color,#888);margin:7px 0}.actions{display:flex;gap:7px;flex-wrap:wrap;margin:7px 0}.actions button{flex:1}",
"@media(max-width:480px){ha-card{padding:11px}.art{width:87px;height:87px;flex-basis:87px}.song{font-size:17px}.controls{gap:6px}.head{margin-bottom:8px}.brand{font-size:16px}.hero{min-height:86px}.row{gap:5px}}"
 ].join("");
  this.shadowRoot.append(style);
  const card=E("ha-card"),head=E("div","head");
  head.append(I("music-circle"),E("b","brand","YouTube Music"));
  const status=E("span","pill","BEREIT");status.id="statusChip";
  const open=B("magnify","Suche, Playlists und Warteschlange öffnen");
  head.append(status,open);card.append(head);
  const hero=E("div","hero"),art=E("div","art"),empty=I("music-box-multiple");empty.id="emptyArt";art.append(empty);
  const img=E("img");img.id="cover";img.hidden=true;img.alt="Cover";art.append(img);
  const meta=E("div","meta"),song=E("div","song","Musik auswählen"),artist=E("div","artist","Suche oder Playlist öffnen");
  song.id="song";artist.id="artist";meta.append(song,artist);hero.append(art,meta);card.append(hero);
  const ctrl=E("div","controls"),prev=B("skip-previous","Zurück"),stop=B("stop","Stopp"),play=B("magnify","Abspielen oder Musik auswählen"),next=B("skip-next","Weiter");
  play.classList.add("primary");ctrl.append(prev,stop,play,next);card.append(ctrl);
  const extras=E("div","extras"),shuffle=B("shuffle","Zufallswiedergabe umschalten"),repeat=B("repeat","Wiederholen"),radio=B("radio","Radio");
  extras.append(shuffle,repeat,radio);card.append(extras);card.append(E("hr","line"));
  const row=E("div","row"),lab=E("span");lab.append(I("speaker"),"Ausgabe");
  const select=E("select","output");select.id="output";select.setAttribute("aria-label","Audio-Ausgabegerät");
  row.append(lab,select);card.append(row);
  const vol=E("div","vol"),minus=B("minus","1 % leiser"),plus=B("plus","1 % lauter"),range=E("input");range.type="range";range.min=0;range.max=100;range.step=1;range.value=0;range.id="volume";
  const pct=E("span","pct","–");pct.id="pct";vol.append(minus,range,plus,pct);card.append(vol);
  const footer=E("div","foot");footer.append(E("span",null,"YouTube Music Live"),E("span",null,"0 Folgetitel"));footer.lastChild.id="qcount";card.append(footer);
  const note=E("div","note");note.id="note";card.append(note);this.shadowRoot.append(card);
  const dlg=E("dialog");dlg.id="dlg";const inner=E("div","dialogbody"),mh=E("div","modalhead");mh.append(I("music-circle"),E("b",null,"Musik entdecken"));
  const close=B("close","Schließen");mh.append(close);inner.append(mh);
  const tabs=E("div","tabs");
  for(const [id,name] of [["library","Meine Listen"],["search","Suche"],["queue","Warteschlange"]]){
   const t=E("button",null,name);t.dataset.tab=id;t.onclick=()=>{this._tab=id;this._listPid="";this._modalKey="";this._modal(true);};tabs.append(t);
  }
  inner.append(tabs);
  const searchline=E("div","searchline");searchline.id="searchline";
  const input=E("input");input.type="search";input.id="search";input.placeholder="Künstler, Titel, Playlist …";
  const kinds=E("select");kinds.id="kind";
  for(const [id,name] of [["songs","Songs"],["playlists","Playlists"],["radios","Radios"],["featured_playlists","YouTube-Mixes"],["community_playlists","Community"]]){
   const option=E("option",null,name);option.value=id;kinds.append(option);
  }
  const go=E("button","act","Suchen");searchline.append(input,kinds,go);inner.append(searchline);
  const caption=E("div","muted");caption.id="caption";inner.append(caption);
  const actions=E("div","actions");actions.id="actions";inner.append(actions);
  const results=E("div","result");results.id="results";inner.append(results);dlg.append(inner);this.shadowRoot.append(dlg);
  open.onclick=()=>this._open();
  close.onclick=()=>dlg.close();dlg.onclick=e=>{if(e.target===dlg)dlg.close();};
  play.onclick=()=>{const a=this._a();if(a.current)this._cmd({action:a.player_state==="playing"?"pause":"resume"});else this._open();};
  stop.onclick=()=>this._cmd({action:"stop"});next.onclick=()=>this._cmd({action:"next"});prev.onclick=()=>this._cmd({action:"previous"});
  shuffle.onclick=()=>this._cmd({action:"shuffle",enabled:!this._a().shuffle_enabled});
  repeat.onclick=()=>{const cur=this._a().repeat_mode||"off";this._cmd({action:"repeat",mode:cur==="off"?"all":cur==="all"?"one":"off"});};
  radio.onclick=()=>{if(this._a().current)this._cmd({action:"radio_toggle",enabled:!this._a().radio_enabled});else{this._tab="search";this._kind="radios";this._open();}};
  select.onchange=e=>this._select(e.target.value);
  range.onpointerdown=()=>this._drag=true;range.oninput=()=>{this._drag=true;pct.textContent=range.value+" %";};
  range.onchange=async()=>{await this._volume(Number(range.value));this._drag=false;};
  range.onpointerup=()=>this._drag=false;
  minus.onclick=()=>this._volume(Number(range.value)-1);plus.onclick=()=>this._volume(Number(range.value)+1);
  go.onclick=()=>this._search();input.onkeydown=e=>{if(e.key==="Enter")this._search();};
  kinds.onchange=e=>this._kind=e.target.value;this._render();
 }
 async _cmd(value){
  try{await this._h.callService("mqtt","publish",{topic:TOPIC,payload:JSON.stringify(value),qos:0,retain:false});this._msg="";}
  catch(e){this._msg=String(e?.message||e);this._q("note").textContent=this._msg.slice(0,160);}
 }
 _open(){this._modal(true);if(!this._q("dlg").open)this._q("dlg").showModal();if(!this._a().playlists?.length)this._cmd({action:"library"});}
 _available(){
  const unique=new Map();
  for(const p of Object.values(this._h?.states||{})){
   const id=p.entity_id;
   if(!id.startsWith("media_player.")||["unknown","unavailable"].includes(p.state)||!(Number(p.attributes?.supported_features||0)&PLAY_MEDIA))continue;
   if(/youtube_music_live|kreativ_tonie|toniebox|this_device|uberall/i.test(id))continue;
   if(/^(Android|This Device|Überall)$/i.test(String(p.attributes?.friendly_name||"").trim()))continue;
   const group=id.replace(/_\d+$/,""),score=(id===group?20:0)+(p.attributes?.volume_level!=null?1:0);
   if(!unique.has(group)||unique.get(group).score<score)unique.set(group,{p,score});
  }
  return [...unique.values()].map(x=>x.p).sort((a,b)=>String(a.attributes?.friendly_name||a.entity_id).localeCompare(String(b.attributes?.friendly_name||b.entity_id),"de"));
 }
 _drawOutputs(){
  const items=this._available(),key=items.map(x=>x.entity_id).join("|");
  if(key!==this._playersKey){
   this._playersKey=key;const sel=this._q("output");sel.replaceChildren();
   const choose=E("option",null,"Ausgabegerät wählen …");choose.value="";sel.append(choose);
   const mobile=E("option",null,"📱 Dieses Handy (Webplayer)");mobile.value="phone";sel.append(mobile);
   for(const p of items){const opt=E("option",null,p.attributes?.friendly_name||p.entity_id);opt.value=p.entity_id;sel.append(opt);}
   if(this._selected&&!["phone",...items.map(x=>x.entity_id)].includes(this._selected))this._selected="";
  }
  this._q("output").value=this._selected;
 }
 _select(id){
  const a=this._a();if(a.current && id!==a.selected_output){this._msg="Bitte zuerst die laufende Wiedergabe stoppen.";this._q("note").textContent=this._msg;this._q("output").value=this._selected;return;}
  this._selected=id;
  if(id?.startsWith("media_player.")){this._msg="Ausgabe gewählt – keine Wiedergabe gestartet.";this._cmd({action:"select_output",entity_id:id});}
  else if(id==="phone")this._msg="Handy: Musik in der YouTube-Music-App-Weboberfläche abspielen.";
  else this._msg="Ausgabe wählen.";
  this._q("note").textContent=this._msg;this._drawVolume();
 }
 _confirm(){
  if(!this._selected){this._msg="Zuerst Ausgabegerät wählen.";this._q("note").textContent=this._msg;return false;}
  if(this._selected==="phone"){
   this._msg="Für Handy-Wiedergabe: Home Assistant → Einstellungen → Apps → YouTube Music Live → Weboberfläche → Musik am Handy testen.";
   this._q("note").textContent=this._msg;return false;
  }
  const name=this._h?.states?.[this._selected]?.attributes?.friendly_name||this._selected;
  return window.confirm("Jetzt wirklich auf „"+name+"“ Musik starten? Das Gerät könnte zuhause sein.");
 }
 _start(action,fields){
  if(!this._confirm())return;
  this._cmd({action,...fields,confirmed:true,entity_id:this._selected});
  this._q("dlg").close();
 }
 _drawVolume(){
  const value=this._h?.states?.[this._selected]?.attributes?.volume_level;
  const n=Number(value),valid=this._selected?.startsWith("media_player.")&&value!=null&&Number.isFinite(n);
  const range=this._q("volume");range.disabled=!valid;
  if(!this._drag){range.value=valid?String(Math.round(n*100)):"0";this._q("pct").textContent=valid?Math.round(n*100)+" %":"–";}
 }
 async _volume(n){
  if(!this._selected?.startsWith("media_player."))return;
  try{await this._h.callService("media_player","volume_set",{entity_id:this._selected,volume_level:Math.max(0,Math.min(100,Math.round(n)))/100});}
  catch(e){this._msg=String(e);}
  this._drawVolume();
 }
 _render(){
  if(!this._ready||!this._h)return;
  const a=this._a(),track=a.current;
  this._q("statusChip").textContent=track?(a.player_state==="playing"?"LIVE":"PAUSE"):"BEREIT";
  this._q("song").textContent=track?.title||"Musik auswählen";
  this._q("artist").textContent=track?.artist||(a.playlists?.length?"Meine Musik ist bereit":"Musik suchen");
  this._q("cover").hidden=!track?.thumbnail;this._q("emptyArt").hidden=!!track?.thumbnail;
  if(track?.thumbnail&&this._q("cover").src!==track.thumbnail)this._q("cover").src=track.thumbnail;
  const ctrl=this.shadowRoot.querySelector(".controls"),buttons=ctrl.querySelectorAll("button");
  buttons[2].querySelector("ha-icon").setAttribute("icon","mdi:"+(track?(a.player_state==="playing"?"pause":"play"):"magnify"));
  buttons[0].disabled=!track;buttons[1].disabled=!track;buttons[3].disabled=!track;
  const icons=this.shadowRoot.querySelector(".extras").querySelectorAll("button");
  icons[0].classList.toggle("on",!!a.shuffle_enabled);icons[1].classList.toggle("on",a.repeat_mode!=="off");icons[2].classList.toggle("on",!!a.radio_enabled);
  icons[1].querySelector("ha-icon").setAttribute("icon","mdi:"+(a.repeat_mode==="one"?"repeat-once":"repeat"));
  icons[1].title="Wiederholen: "+(a.repeat_mode==="one"?"ein Titel":a.repeat_mode==="all"?"alle":"aus");
  this._q("qcount").textContent=(a.queue_length||0)+" Folgetitel";
  this._drawOutputs();this._drawVolume();
  this._q("note").textContent=a.last_error?"Fehler: "+a.last_error:this._msg;
  if(this._q("dlg")?.open)this._modal(false);
 }
 _search(){
  const q=this._q("search").value.trim();if(!q)return;
  this._query=q;this._kind=this._q("kind").value;this._q("caption").textContent="Suche läuft …";
  this._cmd({action:"search",kind:this._kind,query:q});
 }
 _item(title,sub,thumb,actions){
  const row=E("div","item"),img=E("img");img.alt="";img.loading="lazy";if(typeof thumb==="string"&&thumb.startsWith("https://"))img.src=thumb;
  const desc=E("div","desc"),strong=E("strong",null,title||"Unbekannt"),small=E("small",null,sub||"");desc.append(strong,small);row.append(img,desc);
  if(actions)for(const [ic,label,fn] of actions){const b=B(ic,label);b.onclick=fn;row.append(b);}
  return {row,desc};
 }
 _load(pid,title){
  this._listPid=pid;this._listRequested=Date.now()/1000;
  this._q("caption").textContent="Lade "+title+" …";this._q("results").replaceChildren();this._q("actions").replaceChildren();
  this._cmd({action:"load_playlist",playlist_id:pid});
 }
 _tracks(items,title,pid){
  this._q("caption").textContent=title+" · "+items.length+" Titel";
  const actions=this._q("actions");
  if(pid){
   const start=E("button","act","▶ Playlist starten");start.onclick=()=>this._start("start_playlist",{playlist_id:pid});
   const back=E("button","act","‹ Zurück");back.onclick=()=>{this._listPid="";this._modalKey="";this._modal(true);};
   actions.append(start,back);
  }
  for(const t of items){
   const play=()=>this._start("start_track",{video_id:t.video_id}),rad=()=>this._start("start_radio",{video_id:t.video_id});
   const {row,desc}=this._item(t.title,t.artist,t.thumbnail,[["play","Abspielen",play],["radio","Radio starten",rad],["playlist-plus","Hinzufügen",()=>this._cmd({action:"enqueue",video_id:t.video_id})]]);
   desc.onclick=play;this._q("results").append(row);
  }
 }
 _modal(force){
  if(!this._h)return;const a=this._a(),r=this._q("results"),ac=this._q("actions");
  for(const b of this.shadowRoot.querySelectorAll(".tabs button"))b.classList.toggle("on",b.dataset.tab===this._tab);
  this._q("searchline").hidden=this._tab!=="search";
  if(this._tab==="search"){if(force)this._q("search").value=this._query;this._q("kind").value=this._kind;}
  const stamp=[this._tab,a.last_command_at,a.queue_length,this._listPid,a.list_title,a.search_query,a.search_kind].join("|");
  if(!force&&stamp===this._modalKey)return;this._modalKey=stamp;
  r.replaceChildren();ac.replaceChildren();
  if(this._tab==="library"){
   if(this._listPid){
    if(a.last_action!=="load_playlist"||Number(a.last_command_at)<this._listRequested){this._q("caption").textContent="Playlist wird geladen …";return;}
    this._tracks(a.list_tracks||[],a.list_title||"Playlist",this._listPid);return;
   }
   this._q("caption").textContent="Meine Playlists · "+(a.playlists||[]).length+" (mit „Mag ich“)";
   for(const p of a.playlists||[]){
    const load=()=>this._load(p.playlist_id,p.title);
    const {row,desc}=this._item(p.title,p.liked?"Meine Lieblingssongs":"Playlist",p.thumbnail,[["chevron-right","Öffnen",load]]);
    desc.onclick=load;r.append(row);
   }
  }else if(this._tab==="search"){
   const kind=a.search_kind||"songs",items=a.search_results||[],isList=kind.includes("playlist");
   this._q("caption").textContent=a.search_query?items.length+" Treffer: "+a.search_query:"Suche nach Songs, Playlists oder Radios";
   for(const t of items){
    if(isList){
     const load=()=>this._load(t.playlist_id,t.title);
     const {row,desc}=this._item(t.title,"YouTube-Music-Playlist",t.thumbnail,[["chevron-right","Öffnen",load]]);desc.onclick=load;r.append(row);
    }else{
     const play=()=>this._start("start_track",{video_id:t.video_id}),rad=()=>this._start("start_radio",{video_id:t.video_id});
     const {row,desc}=this._item(t.title,t.artist||"Radio",t.thumbnail,[["play","Abspielen",play],["radio","Radio starten",rad],["playlist-plus","Warteschlange",()=>this._cmd({action:"enqueue",video_id:t.video_id})]]);
     desc.onclick=kind==="radios"?rad:play;r.append(row);
    }
   }
  }else{
   const items=a.queue||[];this._q("caption").textContent="Warteschlange · "+(a.queue_length||0)+" Titel";
   if(a.current){const row=this._item(a.current.title,"▶ "+(a.current.artist||"Jetzt"),a.current.thumbnail).row;r.append(row);}
   items.forEach((t,i)=>{
    const fn=()=>{if(!this._confirm())return;this._cmd({action:"queue_play",index:i,video_id:t.video_id});this._q("dlg").close();};
    const {row,desc}=this._item(t.title,t.artist,t.thumbnail,[["play","Jetzt spielen",fn]]);desc.onclick=fn;r.append(row);
   });
  }
 }
}
customElements.define("hauscheck-ytmusic-card",MusicFamilyCard);
window.customCards=window.customCards||[];
window.customCards.push({type:"hauscheck-ytmusic-card",name:"HausCheck YouTube Music",description:"YouTube Music: Mag ich, Playlists, Radios, Shuffle, Wiederholung und Ausgabe"});
})();