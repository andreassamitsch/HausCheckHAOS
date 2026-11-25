import unittest
import numpy as np
from stereo_decoder import Decoder, FS, BLOCK

class StereoTests(unittest.TestCase):
    def render(self, mode, amplitude=.15, pilot=.035):
        d=Decoder()
        result=[]
        for n in range(120):
            t=(np.arange(BLOCK)+n*BLOCK)/FS
            l=amplitude*np.sin(2*np.pi*1000*t)
            r=amplitude*np.sin(2*np.pi*1700*t) if mode=="stereo" else np.zeros_like(l)
            x=(l+r)/2
            if mode=="stereo":
                x+=(l-r)/2*np.sin(2*np.pi*38000*t+.6)+pilot*np.sin(2*np.pi*19000*t+.3)
            b=d.process(np.rint(x*32768).astype("<i2"))
            if b is not None: result.append(np.frombuffer(b,dtype="<i2").reshape(-1,2))
        return np.concatenate(result)[-48000:]/32768.,d.metrics

    def test_real_stereo(self):
        a,m=self.render("stereo")
        self.assertTrue(m["stereo"])
        f=np.abs(np.fft.rfft(a,axis=0))
        self.assertGreater(f[1000,0]/max(f[1000,1],1e-8),10)
        self.assertGreater(f[1700,1]/max(f[1700,0],1e-8),10)

    def test_mono(self):
        a,m=self.render("mono")
        self.assertFalse(m["stereo"])
        np.testing.assert_array_equal(a[:,0],a[:,1])

    def test_peak_protection(self):
        a,m=self.render("stereo",amplitude=.8,pilot=.035)
        self.assertLessEqual(np.max(np.abs(a)),.795)
        self.assertTrue(np.all(np.isfinite(a)))

    def test_silence(self):
        d=Decoder()
        for _ in range(5): b=d.process(np.zeros(BLOCK,dtype=np.int16))
        self.assertEqual(len(b),3840)
        self.assertFalse(np.any(np.frombuffer(b,dtype="<i2")))

if __name__=="__main__": unittest.main()
