import tempfile
import unittest
from pathlib import Path
from audio_level import AudioLevel, parse_levels, input_args

class AudioLevelTests(unittest.TestCase):
    def test_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "gain.json"
            a = AudioLevel(p)
            self.assertEqual(a.filter_args(), [])
            a.set(-6.5)
            self.assertEqual(AudioLevel(p).filter_args(), ["-af", "volume=-6.5dB"])

    def test_bounds(self):
        for v in (1, -19, float("nan"), True, "4"):
            with self.assertRaises(ValueError):
                AudioLevel.validate(v)

    def test_measurement_parser(self):
        s = "I: -12.4 LUFS\nmean_volume: -13.1 dB\nmax_volume: -0.5 dB"
        self.assertEqual(parse_levels(s), {"rms_dbfs": -13.1, "peak_dbfs": -.5, "integrated_lufs": -12.4})
        with self.assertRaises(RuntimeError):
            parse_levels("")

    def test_headers(self):
        a = input_args("https://test.invalid/audio", {"User-Agent":"ok", "Referer":"bad\nheader"}, 45)
        self.assertIn("45", a)
        self.assertNotIn("-referer", a)

if __name__ == "__main__": unittest.main()
