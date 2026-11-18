/* Native Home Assistant media-control card with smarter YouTube Music popup.
 * Uses the standard dashboard card rendered by HA's own card helper.
 * No music is started by mounting the card or opening the media browser.
 */
class SmartYouTubeMusicMediaControlCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:"open"});
    this._card=null;
    this._hass=null;
    this._config=null;
    this._loading=null;
    this._stopPending=false;
    this._stopButton=document.createElement("ha-icon-button");
    this._stopButton.className="ytmusic-stop";
    this._stopButton.path="M18,18H6V6H18V18Z";
    this._stopButton.label="Wiedergabe stoppen";
    this._stopButton.title="Wiedergabe stoppen";
    this._stopButton.addEventListener("click",event=>this._stop(event));
    this._stopObserver=new MutationObserver(()=>this._syncStopControl());
  }

  static getStubConfig() {
    return {type:"custom:smart-youtube-music-player-card",
      entity:"media_player.youtube_music_live_youtube_music_live",name:"Ultra Slim Soundbar"};
  }

  setConfig(config) {
    if(!config.entity || !config.entity.startsWith("media_player.")){
      throw new Error("Ein media_player ist erforderlich");
    }
    this._config={...config};
    this._initialize();
  }

  connectedCallback(){
    if(this._card)this._observeStopControl();
    else this._initialize();
  }

  disconnectedCallback(){this._stopObserver.disconnect();}

  set hass(hass){
    this._hass=hass;
    if(this._card)this._card.hass=hass;
    this._syncStopControl();
  }
  getCardSize(){return this._card?.getCardSize?.()||3;}
  getLayoutOptions(){return this._card?.getLayoutOptions?.()||{grid_columns:12,grid_rows:"auto"};}

  async _initialize() {
    if(!this._config || this._card || this._loading)return this._loading;
    this._loading=(async()=>{
      // loadCardHelpers triggers Home Assistant's native card loader. Constructing
      // a bare <hui-media-control-card> before it is registered causes a
      // Lovelace configuration error; the helper avoids that race.
      const load=window.loadCardHelpers;
      if(typeof load!=="function")throw new Error("Home Assistant card helpers unavailable");
      const helpers=await load();
      const card=helpers.createCardElement({
        type:"media-control",
        entity:this._config.entity,
        ...(this._config.name?{name:this._config.name}:{})
      });
      card.addEventListener("show-dialog",ev=>this._prepareBrowseDialog(ev));
      this._card=card;
      if(this._hass)card.hass=this._hass;
      this.shadowRoot.replaceChildren(card);
      this._observeStopControl();
    })().catch(error=>{
      const fallback=document.createElement("ha-card");
      fallback.textContent="Medienkarte konnte nicht geladen werden: "+String(error?.message||error);
      this.shadowRoot.replaceChildren(fallback);
    }).finally(()=>{this._loading=null;});
    return this._loading;
  }

  async _observeStopControl(){
    // Card helpers can return the element before HA has loaded its class.
    await customElements.whenDefined(this._card.localName);
    await this._card.updateComplete;
    const root=this._card.shadowRoot;
    if(!this.isConnected || !root)return;
    this._stopObserver.observe(root,{childList:true,subtree:true});
    this._syncStopControl();
  }

  _syncStopControl(){
    const root=this._card?.shadowRoot;
    if(!root)return;
    const controls=root.querySelector(".controls .start");
    if(controls?.querySelector('ha-icon-button[action="media_stop"]')){
      this._stopButton.remove();
      return;
    }
    // Native Media Control hides secondary Stop and may rebuild its controls.
    const target=controls || root.querySelector(".top-info > div:last-child");
    if(target && this._stopButton.parentElement!==target){
      target.insertBefore(this._stopButton,controls?null:target.firstChild);
    }
    const player=this._hass?.states?.[this._config.entity];
    const stoppable=player && !["unavailable","unknown"].includes(player.state) &&
      (["playing","paused","buffering"].includes(player.state) ||
       Boolean(player.attributes.media_content_id) || Number(player.attributes.queue_length)>0);
    this._stopButton.disabled=this._stopPending || !stoppable;
  }

  async _stop(event){
    event.stopPropagation();
    if(this._stopButton.disabled || this._stopPending)return;
    this._stopPending=true;
    this._syncStopControl();
    try{
      await this._hass.callService("media_player","media_stop",{}, {entity_id:this._config.entity});
    }catch(error){
      this.dispatchEvent(new CustomEvent("show-toast",{bubbles:true,composed:true,
        detail:{message:"Wiedergabe konnte nicht gestoppt werden: "+String(error?.message||error)}}));
    }finally{
      this._stopPending=false;
      this._syncStopControl();
    }
  }

  _prepareBrowseDialog(event){
    const detail=event.detail,params=detail?.dialogParams;
    if(detail?.dialogTag!=="dialog-media-player-browse" ||
       params?.entityId!==this._config?.entity)return;
    const queue=Number(this._hass?.states?.[this._config.entity]?.attributes?.queue_length||0);
    params.navigateIds=[
      {media_content_id:undefined,media_content_type:undefined},
      {media_content_id:queue>0?"queue":"search",media_content_type:"music"}
    ];
    // The standard dialog closes on 'select' but deliberately stays open on
    // 'play'. Keep the native card's original mediaPickedCallback so it still
    // calls media_player.play_media with the selected song.
    params.action="pick";
  }
}
if(!customElements.get("smart-youtube-music-player-card")){
  customElements.define("smart-youtube-music-player-card",SmartYouTubeMusicMediaControlCard);
}
if(!customElements.get("smart-youtube-music-media-control-card")){
  customElements.define("smart-youtube-music-media-control-card",class extends SmartYouTubeMusicMediaControlCard{});
}
window.customCards=window.customCards||[];
if(!window.customCards.some(item=>item.type==="smart-youtube-music-player-card")){
  window.customCards.push({type:"smart-youtube-music-player-card",
    name:"YouTube Music – native Medienkarte",
    description:"Home Assistant Media Control mit automatischer Warteschlange/Suche und schließendem Popup."});
}
