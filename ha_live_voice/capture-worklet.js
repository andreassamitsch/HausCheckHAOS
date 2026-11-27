/* Local first-utterance buffer. Audio is held only in memory. */
'use strict';
class FirstAudioBuffer {
  constructor(rate,maxSeconds=12){
    this.rate=rate;this.max=Math.floor(rate*maxSeconds);this.q=[];this.head=0;this.samples=0;this.voiced=0;this.quietIn=0;this.quietOut=0;this.mode='capture';this.overflow=false;this.started=false;this.drainedSamples=0;this.offset=0;this.fraction=0;
  }
  quiet(block){let energy=0,peak=0;for(let i=0;i<block.length;i++){const x=block[i];energy+=x*x;peak=Math.max(peak,Math.abs(x));}return Math.sqrt(energy/block.length)<.004&&peak<.018;}
  push(input,q){
    const block={data:new Float32Array(input),quiet:q};this.q.push(block);this.samples+=input.length;if(!q)this.voiced++;
  }
  pop(){
    const b=this.q[this.head++];if(!b)return null;this.samples-=b.data.length-this.offset;this.offset=0;this.fraction=0;if(!b.quiet)this.voiced--;
    if(this.head>256&&this.head*2>=this.q.length){this.q=this.q.slice(this.head);this.head=0;}return b;
  }
  clear(){this.q=[];this.head=0;this.samples=0;this.voiced=0;this.offset=0;this.fraction=0;}
  ready(){
    if(this.mode!=='capture'||this.overflow)return;
    // Remove only verified leading silence, keeping 120 ms before the first sound.
    if(!this.voiced){this.clear();this.mode='live';return;}
    let leading=0;for(let i=this.head;i<this.q.length&&this.q[i].quiet;i++)leading+=this.q[i].data.length;
    while(leading>this.rate*.12&&this.q[this.head]?.quiet&&leading-this.q[this.head].data.length>=this.rate*.12){leading-=this.pop().data.length;}
    this.mode='drain';
  }
  advance(n){
    // Consume samples without allocating or discarding an entire voiced chunk.
    while(n>0&&this.samples>0){
      const b=this.q[this.head],left=b.data.length-this.offset,k=Math.min(n,left);
      this.offset+=k;this.samples-=k;n-=k;
      if(this.offset===b.data.length){if(!b.quiet)this.voiced--;this.head++;this.offset=0;
        if(this.head>256&&this.head*2>=this.q.length){this.q=this.q.slice(this.head);this.head=0;}}
    }
  }
  accelerated(out){
    // Only a fallback for continuous noise/speech that prevents a quiet-boundary
    // catch-up. A modest resample plays the queue faster, then returns to 1x.
    for(let i=0;i<out.length;i++){
      if(this.samples===0){this.clear();this.mode='live';break;}
      const b=this.q[this.head],x=b.data[this.offset];
      const next=this.offset+1<b.data.length?b.data[this.offset+1]:(this.q[this.head+1]?.data[0]??x);
      out[i]=x+(next-x)*this.fraction;
      this.fraction+=1.35;
      const n=Math.floor(this.fraction);this.fraction-=n;this.advance(n);
    }
    if(this.samples===0){this.clear();this.mode='live';}
  }
  process(input,out){
    out.fill(0);
    if(!input||!input.length)return;
    this.started=true;
    if(this.overflow)return;
    if(this.mode==='live'){out.set(input.subarray(0,out.length));return;}
    const quiet=this.quiet(input);this.quietIn=quiet?this.quietIn+input.length:0;
    if(this.mode==='capture'){
      if(this.samples+input.length>this.max){this.overflow=true;this.clear();return;}
      this.push(input,quiet);return;
    }
    // Drain in chronological order at natural speed. Never drop a voiced block.
    // Once only a sufficiently long quiet tail is queued, jump to live at silence.
    if(this.voiced===0&&quiet&&this.quietIn>=this.rate*.5&&this.quietOut>=this.rate*.5){
      this.clear();this.mode='live';out.set(input.subarray(0,out.length));return;
    }
    this.push(input,quiet);
    this.drainedSamples+=out.length;
    // At most six seconds of normal-speed replay before catch-up starts.
    // Once backlog is shorter than one block, finish at the natural rate.
    if(this.drainedSamples>=this.rate*6||this.offset!==0){
      if(this.samples<=out.length){this.accelerated(out);return;}
      this.accelerated(out);return;
    }
    const b=this.pop();
    if(b){out.set(b.data.subarray(0,out.length));this.quietOut=b.quiet?this.quietOut+b.data.length:0;}
  }
}
if(typeof module!=='undefined'&&module.exports)module.exports={FirstAudioBuffer};
if(typeof AudioWorkletProcessor!=='undefined'){
  class FirstVoiceProcessor extends AudioWorkletProcessor{
    constructor(){
      super();this.buffer=new FirstAudioBuffer(sampleRate);this.sentStarted=false;this.sentLive=false;this.sentOverflow=false;
      this.port.onmessage=e=>{if(e.data==='ready')this.buffer.ready();};
    }
    process(inputs,outputs){
      const out=outputs[0]?.[0];if(!out)return true;
      this.buffer.process(inputs[0]?.[0],out);
      if(this.buffer.started&&!this.sentStarted){this.sentStarted=true;this.port.postMessage('capturing');}
      if(this.buffer.mode==='live'&&!this.sentLive){this.sentLive=true;this.port.postMessage('live');}
      if(this.buffer.overflow&&!this.sentOverflow){this.sentOverflow=true;this.port.postMessage('overflow');}
      return true;
    }
  }
  registerProcessor('first-voice-buffer',FirstVoiceProcessor);
}
