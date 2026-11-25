"""Streaming 171 kHz FM multiplex -> 48 kHz stereo PCM.
Pilot coherent demodulation, automatic stereo blend, 50 us de-emphasis,
slow linked RMS gain and linked peak limiter. No receiver control here.
"""
import json
import math
import sys
import numpy as np
from scipy import signal

FS = 171000
OUT = 48000
BLOCK = 3420
OVERLAP = 171

class Decoder:
    def __init__(self, target_db=-18.0, max_gain_db=15.0):
        self.target = 10 ** (target_db / 20)
        self.max_gain = 10 ** (max_gain_db / 20)
        self.gain = min(2., self.max_gain)
        self.level2 = (self.target / self.gain) ** 2
        self.limiter = 1.
        self.blend = 0.
        self.pilot_filter = signal.butter(2, 220, fs=FS, output="sos")
        self.pilot_zi = np.zeros((len(self.pilot_filter), 2, 2))
        self.audio_filter = signal.firwin(161, 16000, fs=FS, window=("kaiser", 8.0))
        self.audio_zi = np.zeros((160, 2))
        self.osc = 2*np.pi*np.arange(BLOCK)/9
        self.sn = np.sin(self.osc)
        self.cs = np.cos(self.osc)
        self.sn2 = np.sin(2*self.osc)
        self.cs2 = np.cos(2*self.osc)
        self.tail = np.zeros((OVERLAP, 2))
        self.pending = None
        a = math.exp(-1/(OUT*50e-6))
        self.de_b, self.de_a = [1-a], [1,-a]
        self.de_zi = np.zeros((1, 2))
        self.dc = signal.butter(1, 30, btype="highpass", fs=OUT, output="sos")
        self.dc_zi = np.zeros((len(self.dc), 2, 2))
        self.metrics = {}
        self.n = 0

    def process(self, raw):
        x = np.asarray(raw, dtype=np.float64)/32768.
        if len(x) != BLOCK:
            raise ValueError("invalid multiplex block")
        # For a sine pilot, I/Q recover cos(phi), sin(phi). The standard
        # 38 kHz reference is sin(2*omega*t+2*phi).
        iq, self.pilot_zi = signal.sosfilt(self.pilot_filter,
            np.column_stack((x*self.sn, x*self.cs)), axis=0, zi=self.pilot_zi)
        i,q = iq.T
        power = i*i+q*q
        amp = 2*math.sqrt(float(np.mean(power)))
        mpx_rms = math.sqrt(float(np.mean(x*x)))
        ratio = amp/max(mpx_rms, 1e-8)
        desired = float(np.clip((ratio-.07)/.15, 0, 1)) if amp>.0006 else 0.
        old = self.blend
        self.blend += (desired-self.blend)*(.18 if desired>old else .35)
        blend = np.linspace(old, self.blend, BLOCK)
        carrier = ((i*i-q*q)*self.sn2+2*i*q*self.cs2)/np.maximum(power,1e-12)
        base,self.audio_zi = signal.lfilter(self.audio_filter, [1.],
            np.column_stack((x,2*x*carrier*blend)), axis=0, zi=self.audio_zi)
        stereo = np.column_stack((base[:,0]+base[:,1],base[:,0]-base[:,1]))
        # 1 ms overlap on both sides avoids resampler edge artifacts. All
        # lengths are multiples of 171 -> exact 48 kHz timing.
        if self.pending is None:
            self.pending=stereo
            return None
        extended=np.concatenate((self.tail,self.pending,stereo[:OVERLAP]))
        pcm=signal.resample_poly(extended,16,57,axis=0)[48:1008]
        self.tail=self.pending[-OVERLAP:].copy()
        self.pending=stereo
        pcm,self.de_zi=signal.lfilter(self.de_b,self.de_a,pcm,axis=0,zi=self.de_zi)
        pcm,self.dc_zi=signal.sosfilt(self.dc,pcm,axis=0,zi=self.dc_zi)
        rms=math.sqrt(float(np.mean(pcm*pcm)))
        if rms>0.001:
            alpha=1-math.exp(-.02/2.)
            self.level2+=(rms*rms-self.level2)*alpha
            target=float(np.clip(self.target/math.sqrt(max(self.level2,1e-12)),.25,self.max_gain))
            previous=self.gain
            self.gain+=(target-self.gain)*(1-math.exp(-.02/1.5))
        else:
            previous=self.gain
        pcm*=np.linspace(previous,self.gain,len(pcm))[:,None]
        peak=float(np.max(np.abs(pcm)))
        # Common gain preserves the stereo image. Fast attack, slow release.
        ceiling=10**(-2/20)
        need=min(1.,ceiling/max(peak,1e-12))
        oldlim=self.limiter
        self.limiter=min(need,self.limiter+(1-self.limiter)*.08)
        pcm*=np.linspace(min(oldlim,self.limiter),self.limiter,len(pcm))[:,None]
        pcm=np.clip(pcm,-ceiling,ceiling)
        db=lambda v: round(20*math.log10(max(v,1e-8)),1)
        self.metrics={"stereo":bool(self.blend>.65),"stereo_blend":round(self.blend,2),
            "pilot_ratio":round(ratio,3),"audio_input_rms_dbfs":db(rms),
            "audio_output_rms_dbfs":db(math.sqrt(float(np.mean(pcm*pcm)))),
            "audio_peak_dbfs":db(float(np.max(np.abs(pcm)))),
            "audio_gain_db":db(self.gain),"audio_limiter_db":db(self.limiter)}
        self.n+=1
        return np.rint(pcm*32767).astype("<i2").tobytes()

def main():
    target=float(sys.argv[1]) if len(sys.argv)>1 else -18.
    maximum=float(sys.argv[2]) if len(sys.argv)>2 else 15.
    decoder=Decoder(target,maximum)
    while True:
        raw=sys.stdin.buffer.read(BLOCK*2)
        if len(raw)!=BLOCK*2: break
        packet=decoder.process(np.frombuffer(raw,dtype="<i2"))
        if packet is not None:
            sys.stdout.buffer.write(packet)
            sys.stdout.buffer.flush()
            if decoder.n%250==0:
                print("AUDIO_METRICS "+json.dumps(decoder.metrics),file=sys.stderr,flush=True)

if __name__=="__main__":
    main()
