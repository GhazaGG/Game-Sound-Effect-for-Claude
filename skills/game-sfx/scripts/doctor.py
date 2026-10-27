#!/usr/bin/env python3
"""Check a sound without listening to it. Python 3.8+ stdlib only.

  python doctor.py sound.wav [more.wav ...] [--png] [--duration A:B] [--centroid A:B] [--lufs A:B]

Prints peak, loudness, spectrum balance and OK/WARN/FAIL findings. --png writes
<name>.png: waveform strip on top, log-frequency spectrogram below with dotted
lines at 100 Hz, 1 kHz and 10 kHz, white ticks every 100 ms.
"""
import argparse
import cmath
import math
import os
import struct
import sys
import wave
import zlib


def read_wav(path):
    with wave.open(path, "rb") as w:
        ch, width, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 1:
        vals = [(b - 128) / 128 for b in raw]
    elif width == 2:
        vals = [v / 32768 for v in struct.unpack(f"<{len(raw) // 2}h", raw)]
    elif width == 3:
        vals = [int.from_bytes(raw[i:i + 3], "little", signed=True) / 8388608 for i in range(0, len(raw), 3)]
    else:
        vals = [v / 2147483648 for v in struct.unpack(f"<{len(raw) // 4}i", raw)]
    mono = [sum(vals[i:i + ch]) / ch for i in range(0, len(vals), ch)]
    return mono, sr, ch


def biquad(x, b, a):
    b0, b1, b2 = (v / a[0] for v in b)
    a1, a2 = a[1] / a[0], a[2] / a[0]
    x1 = x2 = y1 = y2 = 0.0
    out = []
    for v in x:
        y = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, v, y1, y
        out.append(y)
    return out


def loudness(x, sr):
    """BS.1770 K-weighted loudness in LUFS (gated; ungated if shorter than 400 ms)."""
    A = 10 ** (4.0 / 40)
    w = 2 * math.pi * 1500 / sr
    al = math.sin(w) / (2 * 0.7071)
    c, sa = math.cos(w), 2 * math.sqrt(A) * al
    y = biquad(x, (A * ((A + 1) + (A - 1) * c + sa), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - sa)),
               ((A + 1) - (A - 1) * c + sa, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - sa))
    w = 2 * math.pi * 38 / sr
    al, c = math.sin(w) / (2 * 0.5), math.cos(w)
    y = biquad(y, ((1 + c) / 2, -(1 + c), (1 + c) / 2), (1 + al, -2 * c, 1 - al))

    def lufs(ms):
        return -0.691 + 10 * math.log10(ms) if ms > 0 else -120.0

    size, step = int(0.4 * sr), int(0.1 * sr)
    if len(y) < size:
        return lufs(sum(v * v for v in y) / max(len(y), 1))
    blocks = [sum(v * v for v in y[i:i + size]) / size for i in range(0, len(y) - size + 1, step)]
    blocks = [b for b in blocks if lufs(b) > -70]
    if not blocks:
        return -120.0
    rel = lufs(sum(blocks) / len(blocks)) - 10
    blocks = [b for b in blocks if lufs(b) > rel]
    return lufs(sum(blocks) / len(blocks))


def fft(a):
    n = len(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    m = 2
    while m <= n:
        tw = [cmath.exp(-2j * math.pi * k / m) for k in range(m // 2)]
        for k in range(0, n, m):
            for t in range(m // 2):
                u, v = a[k + t], a[k + t + m // 2] * tw[t]
                a[k + t], a[k + t + m // 2] = u + v, u - v
        m <<= 1
    return a


def spectrogram(x, cols, size=512):
    """`cols` power spectra (size/2 bins each), Hann-windowed, evenly spread over x."""
    win = [0.5 - 0.5 * math.cos(2 * math.pi * i / size) for i in range(size)]
    out = []
    for c in range(cols):
        mid = int((c + 0.5) * len(x) / cols)
        frame = [complex(x[i] * win[k]) if 0 <= (i := mid - size // 2 + k) < len(x) else 0j for k in range(size)]
        out.append([abs(v) ** 2 for v in fft(frame)[: size // 2]])
    return out


def analyze(x, sr, expect=None):
    m, issues = {}, []
    n = len(x)
    peak = max((abs(v) for v in x), default=0.0)
    m["duration"] = n / sr
    if peak == 0:
        return m, [("FAIL", "file is silent")]
    rms = math.sqrt(sum(v * v for v in x) / n)
    m["peak_db"] = 20 * math.log10(peak)
    m["crest_db"] = m["peak_db"] - 20 * math.log10(rms)
    m["dc"] = sum(x) / n
    m["lufs"] = loudness(x, sr)
    m["lead_ms"] = 1000 * next(i for i, v in enumerate(x) if abs(v) > peak * 0.01) / sr
    m["tail_ms"] = 1000 * (n - 1 - max(i for i, v in enumerate(x) if abs(v) > peak * 1e-3)) / sr

    run = clipped = 0
    for v in x:
        run = run + 1 if abs(v) >= 0.999 else 0
        clipped += run == 3

    size = 512
    power = [sum(col) for col in zip(*spectrogram(x, 48, size))]
    total = sum(power) or 1.0
    hz = [b * sr / size for b in range(len(power))]

    def band(lo, hi):
        return sum(p for p, f in zip(power, hz) if lo <= f < hi) / total

    m["centroid"] = sum(p * f for p, f in zip(power, hz)) / total
    m["low"], m["harsh"], m["air"] = band(0, 80), band(2000, 5000), band(16000, sr)

    if clipped:
        issues.append(("FAIL", f"{clipped} clipped run(s): lower gain"))
    if m["peak_db"] > -0.9:
        issues.append(("WARN", "peak above -1 dBFS ceiling"))
    if abs(x[0]) > 0.02 or abs(x[-1]) > 0.02:
        issues.append(("WARN", "starts/ends off zero: click risk, add attack/release fade"))
    if abs(m["dc"]) > 0.01:
        issues.append(("WARN", "DC offset: high-pass at 20-40 Hz"))
    expect = expect or {}
    if m["lead_ms"] > 10 and "lead_ms" not in expect:
        issues.append(("WARN", f"{m['lead_ms']:.0f} ms leading silence: trim, it reads as input lag"))
    if m["tail_ms"] > 100 and "tail_ms" not in expect:
        issues.append(("WARN", f"{m['tail_ms']:.0f} ms silent tail: trim"))
    if m["crest_db"] < 6:
        issues.append(("WARN", "crest < 6 dB: flat/droning, needs an envelope with a transient"))
    if m["air"] > 0.05:
        issues.append(("WARN", f"{m['air']:.0%} energy above 16 kHz: aliasing or hiss, low-pass 8-12 kHz"))
    if m["harsh"] > 0.5:
        issues.append(("WARN", f"{m['harsh']:.0%} energy in 2-5 kHz: harsh, ear-fatiguing"))
    for key, (lo, hi) in expect.items():
        if key in m and not lo <= m[key] <= hi:
            issues.append(("FAIL", f"{key} {m[key]:.3g} outside expected {lo}..{hi}"))
    return m, issues or [("OK", "no problems found")]


def report(path, m, issues):
    if "peak_db" not in m:
        return f"{path}\n  " + "\n  ".join(f"{lv} {msg}" for lv, msg in issues)
    lines = [
        f"{os.path.basename(path)}  {m['duration']:.3f}s",
        f"  peak {m['peak_db']:.1f} dBFS | {m['lufs']:.1f} LUFS | crest {m['crest_db']:.1f} dB | centroid {m['centroid']:.0f} Hz",
        f"  energy <80Hz {m['low']:.0%} | 2-5kHz {m['harsh']:.0%} | >16kHz {m['air']:.1%} | lead {m['lead_ms']:.0f} ms",
    ]
    return "\n".join(lines + [f"  {lv} {msg}" for lv, msg in issues])


COLORS = [(0, 0, 0), (40, 0, 110), (190, 30, 70), (250, 150, 0), (255, 255, 210)]


def color(t):
    t = min(max(t, 0.0), 1.0) * (len(COLORS) - 1)
    i = min(int(t), len(COLORS) - 2)
    f = t - i
    return bytes(int(a + (b - a) * f) for a, b in zip(COLORS[i], COLORS[i + 1]))


def write_png(x, sr, path, cols=400, wave_h=48, spec_h=200, size=512):
    spec = spectrogram(x, cols, size)
    db = [[10 * math.log10(p + 1e-12) for p in col] for col in spec]
    top = max(max(col) for col in db)
    nyq, fmin = sr / 2, 50.0
    rows_hz = [fmin * (nyq / fmin) ** ((spec_h - 1 - r) / (spec_h - 1)) for r in range(spec_h)]
    grid = {min(range(spec_h), key=lambda r: abs(rows_hz[r] - g)) for g in (100, 1000, 10000) if g < nyq}

    chunk = len(x) / cols
    peaks = [max((abs(v) for v in x[int(c * chunk):int((c + 1) * chunk) + 1]), default=0) for c in range(cols)]
    ticks = {int(t * cols / (len(x) / sr)) for t in [i * 0.1 for i in range(int(len(x) / sr / 0.1) + 1)]}

    rows = []
    for r in range(wave_h):
        amp = abs(r - wave_h / 2) / (wave_h / 2)
        rows.append(b"".join(
            b"\xff\xff\xff" if c in ticks and r >= wave_h - 4 else
            b"\x60\xc0\xff" if peaks[c] >= amp else b"\x10\x10\x18" for c in range(cols)))
    for r in range(spec_h):
        b = min(int(rows_hz[r] * size / sr), size // 2 - 1)
        rows.append(b"".join(
            b"\x90\x90\x90" if r in grid and c % 4 < 2 else color((db[c][b] - top + 80) / 80) for c in range(cols)))

    def chunk_(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    h = wave_h + spec_h
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk_(b"IHDR", struct.pack(">IIBBBBB", cols, h, 8, 2, 0, 0, 0))
                + chunk_(b"IDAT", zlib.compress(b"".join(b"\x00" + row for row in rows), 9)) + chunk_(b"IEND", b""))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--png", action="store_true")
    for key in ("duration", "centroid", "lufs"):
        ap.add_argument(f"--{key}", metavar="A:B")
    args = ap.parse_args()
    expect = {k: [float(v) for v in getattr(args, k).split(":")] for k in ("duration", "centroid", "lufs") if getattr(args, k)}

    failed = False
    for path in args.files:
        x, sr, ch = read_wav(path)
        m, issues = analyze(x, sr, expect)
        print(report(path, m, issues) + (f"\n  INFO stereo file analyzed as mono sum" if ch > 1 else ""))
        if args.png:
            write_png(x, sr, os.path.splitext(path)[0] + ".png")
        failed |= any(lv == "FAIL" for lv, _ in issues)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
