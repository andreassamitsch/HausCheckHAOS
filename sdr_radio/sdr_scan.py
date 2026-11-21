"""Single-shot UKW spectrum scan for RTL-SDR using rtl_power.

One SDR device cannot receive audio and scan the band concurrently.
The calling tuner pauses briefly, then resumes or tunes to the next
detected peak. Results are cached in RAM and not written to disk.
"""
import csv
import io
import math
import statistics
import subprocess
import time

MIN_MHZ = 87.5
MAX_MHZ = 108.0


def scan_spectrum(device=0, gain="auto", ppm=0):
    cmd = ["rtl_power", "-d", str(device), "-f", "87.5M:108M:100k",
           "-i", "1", "-1", "-p", str(ppm)]
    if gain != "auto":
        cmd += ["-g", str(float(gain))]
    cmd += ["-"]
    start = time.monotonic()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=18)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Sendersuchlauf nicht verfügbar: " + str(exc)) from exc
    if result.returncode != 0:
        raise RuntimeError("Spektrumsuche: " + (result.stderr.strip()[-450:] or
                                               "rtl_power konnte den Empfänger nicht öffnen."))
    points = {}
    for row in csv.reader(io.StringIO(result.stdout)):
        if len(row) < 7:
            continue
        try:
            low, high, step = map(float, row[2:5])
        except (ValueError, TypeError):
            continue
        if step <= 0:
            continue
        for idx, field in enumerate(row[6:]):
            try:
                power = float(field)
                center = (low + (idx + 0.5) * step) / 1e6
            except ValueError:
                continue
            if math.isfinite(power) and MIN_MHZ <= center <= MAX_MHZ:
                bin_freq = round(center * 10) / 10
                # Favor stronger readings if FFT overlaps near a bin.
                if bin_freq not in points or power > points[bin_freq]:
                    points[bin_freq] = power

    if len(points) < 80:
        raise RuntimeError("Spektrumsuche lieferte keine vollständigen Messdaten.")

    items = sorted(points.items())
    values = [p for _f, p in items]
    estimates = []
    for i, (frequency, power) in enumerate(items):
        baseline_window = values[max(0, i-12):min(len(items), i+13)]
        baseline = statistics.median(baseline_window)
        # FM carriers are wide: aggregate the center and neighbors to avoid
        # choosing narrow interference spikes as a radio station.
        neighbors = values[max(0, i-1):min(len(items), i+2)]
        mean = sum(neighbors) / len(neighbors)
        score = (0.7 * power + 0.3 * mean) - baseline
        if score >= 3.6 and power >= max(values[max(0, i-1):min(len(items), i+2)]) - 0.01:
            estimates.append({"frequency": round(frequency, 2),
                              "signal_db": round(power, 1),
                              "contrast_db": round(score, 1)})
    estimates.sort(key=lambda e: e["contrast_db"], reverse=True)
    peaks = []
    for item in estimates:
        if all(abs(item["frequency"] - other["frequency"]) >= 0.28 for other in peaks):
            peaks.append(item)
    peaks.sort(key=lambda e: e["frequency"])
    return {"stations": peaks, "duration_ms": round((time.monotonic()-start)*1000),
            "bins": len(points)}


def find_next(stations, current, direction):
    frequencies = sorted(float(x["frequency"]) for x in stations)
    if not frequencies:
        return None
    if direction > 0:
        candidates = [freq for freq in frequencies if freq > current + 0.11]
        return candidates[0] if candidates else frequencies[0]
    candidates = [freq for freq in frequencies if freq < current - 0.11]
    return candidates[-1] if candidates else frequencies[-1]
