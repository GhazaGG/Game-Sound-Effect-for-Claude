#!/usr/bin/env python3
"""Check a sound without listening to it. Python 3.8+ stdlib only.

  python doctor.py sound.wav [more.wav ...] [--png] [--duration A:B] [--centroid A:B] [--lufs A:B]
                   [--pitch rising|falling|steady] [--loop] [--set]

Prints peak and true peak, loudness, spectrum balance, attack/decay, hit count, pitch direction
and OK/WARN/FAIL findings. --loop checks the wrap point (automatic for WAVs with a smpl loop);
--set compares loudness across the files, for variants of one sound. --png writes
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


def ffmpeg_decode(path, sr=None):
    """Decode anything ffmpeg reads (float WAV, OGG, MP3, FLAC, M4A...) -> (mono samples, sr, channels)."""
    import subprocess
    try:
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                                "stream=sample_rate,channels", "-of", "csv=p=0", path],
                               capture_output=True, text=True, check=True).stdout.split(",")
        src_sr, ch = int(probe[0]), int(probe[1])
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr or src_sr), "-f", "s16le", "-"],
                             capture_output=True, check=True).stdout
    except FileNotFoundError:
        sys.exit(f"{path}: needs ffmpeg to read (https://ffmpeg.org), or convert it to 16-bit PCM WAV first")
    except (subprocess.CalledProcessError, ValueError, IndexError):
        sys.exit(f"{path}: not a readable audio file")
    return [v / 32768 for v in struct.unpack(f"<{len(raw) // 2}h", raw)], sr or src_sr, ch


def read_wav(path):
    """Any audio file -> (mono samples, sample rate, channels). PCM WAV is read natively, the rest via ffmpeg."""
    try:
        with wave.open(path, "rb") as w:
            ch, width, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            raw = w.readframes(n)
    except (wave.Error, EOFError):  # float WAV (Audacity's default export), OGG, MP3...
        return ffmpeg_decode(path)
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


def lufs(mean_square):
    return -0.691 + 10 * math.log10(mean_square) if mean_square > 0 else -120.0


def kweight(x, sr):
    """BS.1770 K-weighting: high-shelf +4 dB at 1.5 kHz, then high-pass at 38 Hz."""
    A = 10 ** (4.0 / 40)
    w = 2 * math.pi * 1500 / sr
    al = math.sin(w) / (2 * 0.7071)
    c, sa = math.cos(w), 2 * math.sqrt(A) * al
    y = biquad(x, (A * ((A + 1) + (A - 1) * c + sa), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - sa)),
               ((A + 1) - (A - 1) * c + sa, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - sa))
    w = 2 * math.pi * 38 / sr
    al, c = math.sin(w) / (2 * 0.5), math.cos(w)
    return biquad(y, ((1 + c) / 2, -(1 + c), (1 + c) / 2), (1 + al, -2 * c, 1 - al))


def loudness(x, sr, y=None):
    """BS.1770 K-weighted loudness in LUFS (gated; ungated if shorter than 400 ms)."""
    y = y or kweight(x, sr)
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


def momentary_max(y, sr):
    """Loudest 400 ms window of a K-weighted signal (BS.1770 momentary loudness), in LUFS.
    Most SFX are shorter than the 3 s short-term window, so this is the 'how loud does it hit' number."""
    size, step = int(0.4 * sr), int(0.1 * sr)
    y = list(y) + [0.0] * max(0, size - len(y))
    acc = [0.0]
    for v in y:
        acc.append(acc[-1] + v * v)
    return lufs(max((acc[i + size] - acc[i]) / size for i in range(0, len(y) - size + 1, step)))


def true_peak(x, over=4, taps=8):
    """Peak after 4x windowed-sinc upsampling (BS.1770 Annex 2 idea). Catches inter-sample overs that clip
    once the WAV is encoded to OGG/MP3 or resampled, even when every stored sample is under the ceiling."""
    peak = max((abs(v) for v in x), default=0.0)
    best, n = peak, len(x)
    span = range(-taps + 1, taps + 1)
    kernels = []
    for p in range(1, over):
        f = p / over
        kernels.append([(math.sin(math.pi * (f - k)) / (math.pi * (f - k))) * (0.5 + 0.5 * math.cos(math.pi * (f - k) / taps))
                        for k in span])
    for i in range(n - 1):
        if abs(x[i]) < 0.5 * peak and abs(x[i + 1]) < 0.5 * peak:
            continue  # an inter-sample over only happens next to loud samples
        lo, hi = i - taps + 1, i + taps + 1
        seg = x[max(lo, 0):min(hi, n)]
        off = max(lo, 0) - lo
        for kern in kernels:
            s = sum(a * b for a, b in zip(seg, kern[off:]))
            best = max(best, abs(s))
    return best


def envelope_stats(x, sr, hop_s=0.005):
    """Attack and decay of the loudest event (10%->90% rise, then peak -> 40 dB down), and onset count."""
    hop = max(1, int(hop_s * sr))
    env = [math.sqrt(sum(v * v for v in x[i:i + hop]) / hop) for i in range(0, len(x), hop)]
    pk = max(env)
    ip = env.index(pk)
    i10 = ip
    while i10 > 0 and env[i10 - 1] >= 0.1 * pk:
        i10 -= 1
    i90 = next(i for i in range(i10, ip + 1) if env[i] >= 0.9 * pk)
    floor = pk * 10 ** (-40 / 20)
    end = next((i for i in range(ip, len(env)) if env[i] < floor), len(env))
    gate, rise = pk * 10 ** (-30 / 20), 10 ** (6 / 20)
    hits, low, last = 0, 0.0, -10 ** 9
    for i, e in enumerate(env):  # an onset = level jumps 6 dB over the lowest point since the previous one
        if e > gate and e > rise * low and i - last >= 0.03 / hop_s:
            hits, low, last = hits + 1, e, i
        low = min(low, e)
    return {"attack_ms": (i90 - i10) * hop_s * 1000, "decay_ms": (end - ip) * hop_s * 1000, "hits": hits}


def pitch_track(x, sr, fmin=60.0, fmax=3000.0, max_frames=60):
    """YIN pitch track -> [(time s, Hz), ...] over the frames where a pitch is clear. Noise gives few or none."""
    d = max(1, int(sr // 11025))
    if d > 1:  # anti-alias, then decimate to ~11 kHz: fast enough in pure Python, fine up to fmax
        w = 2 * math.pi * min(fmax * 1.3, 0.45 * sr / d) / sr
        al, c = math.sin(w) / (2 * 0.7071), math.cos(w)
        lp = (((1 - c) / 2, 1 - c, (1 - c) / 2), (1 + al, -2 * c, 1 - al))
        x = biquad(biquad(x, *lp), *lp)[::d]
    s = sr / d
    W = int(s / fmin) + 1
    tmin = max(2, int(s / fmax))
    hop = max(1, int(0.01 * s))
    starts = list(range(0, len(x) - 2 * W, hop))
    if not starts:
        return []
    loud = max(sum(v * v for v in x[st:st + W]) for st in starts)
    starts = [st for st in starts if sum(v * v for v in x[st:st + W]) > loud * 1e-3]  # within 30 dB of the loudest
    starts = starts[::max(1, len(starts) // max_frames)]
    track = []
    for st in starts:
        a, seg = x[st:st + W], x[st:st + 2 * W]
        diff = [sum((p - q) ** 2 for p, q in zip(a, seg[tau:tau + W])) for tau in range(W)]
        run, cmn = 0.0, [1.0]
        for tau in range(1, W):
            run += diff[tau]
            cmn.append(diff[tau] * tau / run if run else 1.0)
        tau = next((t for t in range(tmin, W - 1) if cmn[t] < 0.15), None)
        if tau is None:
            tau = min(range(tmin, W - 1), key=cmn.__getitem__)
            if cmn[tau] > 0.3:
                continue  # no clear period: noise or a chord
        while tau + 1 < W - 1 and cmn[tau + 1] < cmn[tau]:
            tau += 1
        a0, b0, c0 = cmn[tau - 1], cmn[tau], cmn[tau + 1]
        den = a0 - 2 * b0 + c0
        exact = tau + (0.5 * (a0 - c0) / den if den else 0.0)
        track.append(((st + W / 2) / s, s / exact))
    return track


def pitch_shape(track):
    """Net pitch movement in semitones (median of the last quarter vs the first), or None if untracked."""
    import statistics
    if len(track) < 3:
        return None
    st = [12 * math.log2(f / 440) for _, f in track]
    k = max(1, len(st) // 4)
    a, b = statistics.median(st[:k]), statistics.median(st[-k:])
    return {"pitch_st": b - a, "pitch_from": 440 * 2 ** (a / 12), "pitch_to": 440 * 2 ** (b / 12)}


def loop_seam(x):
    """How far the wrap point (last sample -> first) jumps off the waveform's own path,
    compared with the file's 99th-percentile step. A seamless loop scores about 1 or below."""
    if len(x) < 4:
        return 0.0
    jump = abs(x[0] - (2 * x[-1] - x[-2]))
    steps = sorted(abs(x[i + 1] - (2 * x[i] - x[i - 1])) for i in range(1, len(x) - 1))
    return jump / max(steps[int(0.99 * (len(steps) - 1))], 1e-4)


def wav_loop(path):
    """(start, end) sample frames of the first loop in a WAV's smpl chunk, or None."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    i = 12
    while i + 8 <= len(data):
        tag, size = data[i:i + 4], struct.unpack("<I", data[i + 4:i + 8])[0]
        if tag == b"smpl" and size >= 60 and struct.unpack("<I", data[i + 36:i + 40])[0]:
            return struct.unpack("<II", data[i + 52:i + 60])
        i += 8 + size + (size & 1)
    return None


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


PITCH_SHAPES = ("rising", "falling", "steady")


def analyze(x, sr, expect=None, loop=False):
    """Metrics + (level, message) findings. `expect` holds [lo, hi] ranges for numeric metrics,
    plus "pitch": rising | falling | steady. `loop` checks the wrap point instead of the end fades."""
    m, issues = {}, []
    n = len(x)
    peak = max((abs(v) for v in x), default=0.0)
    m["duration"] = n / sr
    if peak == 0:
        return m, [("FAIL", "file is silent")]
    rms = math.sqrt(sum(v * v for v in x) / n)
    m["peak_db"] = 20 * math.log10(peak)
    m["true_peak_db"] = 20 * math.log10(true_peak(x))
    m["crest_db"] = m["peak_db"] - 20 * math.log10(rms)
    m["dc"] = sum(x) / n
    y = kweight(x, sr)
    m["lufs"] = loudness(x, sr, y)
    m["mmax"] = momentary_max(y, sr)
    m.update(envelope_stats(x, sr))
    m.update(pitch_shape(pitch_track(x, sr)) or {})
    if loop:
        m["seam"] = loop_seam(x)
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
    elif m["true_peak_db"] > -0.9:
        issues.append(("WARN", f"true peak {m['true_peak_db']:.1f} dBTP: inter-sample overs, will clip after OGG/MP3 encoding"))
    if loop:
        if m["seam"] > 2:
            issues.append(("WARN", f"loop seam jumps {m['seam']:.1f}x the largest normal step: audible click on every repeat"))
    elif abs(x[0]) > 0.02 or abs(x[-1]) > 0.02:
        issues.append(("WARN", "starts/ends off zero: click risk, add attack/release fade"))
    if abs(m["dc"]) > 0.01:
        issues.append(("WARN", "DC offset: high-pass at 20-40 Hz"))
    expect = expect or {}
    if m["lead_ms"] > 10 and "lead_ms" not in expect and not loop:
        issues.append(("WARN", f"{m['lead_ms']:.0f} ms leading silence: trim, it reads as input lag"))
    if m["tail_ms"] > 100 and "tail_ms" not in expect and not loop:
        issues.append(("WARN", f"{m['tail_ms']:.0f} ms silent tail: trim"))
    if m["crest_db"] < 6:
        issues.append(("WARN", "crest < 6 dB: flat/droning, needs an envelope with a transient"))
    if m["air"] > 0.05:
        issues.append(("WARN", f"{m['air']:.0%} energy above 16 kHz: aliasing or hiss, low-pass 8-12 kHz"))
    if m["harsh"] > 0.5:
        issues.append(("WARN", f"{m['harsh']:.0%} energy in 2-5 kHz: harsh, ear-fatiguing"))
    m["pitch"] = shape(m.get("pitch_st"))
    for key, want in expect.items():
        if key == "pitch":
            if m["pitch"] is None:
                issues.append(("WARN", f"expected pitch {want}, but no clear pitch to track (noise or too short)"))
            elif m["pitch"] != want:
                issues.append(("FAIL", f"pitch is {m['pitch']} ({m['pitch_st']:+.1f} st), expected {want}"))
        elif key in m:
            lo, hi = want
            if not lo <= m[key] <= hi:
                issues.append(("FAIL", f"{key} {m[key]:.3g} outside expected {lo}..{hi}"))
    return m, issues or [("OK", "no problems found")]


def shape(st):
    """Net semitone movement -> rising / falling / steady (None if the pitch couldn't be tracked)."""
    if st is None:
        return None
    return "rising" if st >= 1 else "falling" if st <= -1 else "steady"


def report(path, m, issues):
    if "peak_db" not in m:
        return f"{path}\n  " + "\n  ".join(f"{lv} {msg}" for lv, msg in issues)
    pitch = (f"pitch {m['pitch']} {m['pitch_st']:+.1f} st ({m['pitch_from']:.0f}->{m['pitch_to']:.0f} Hz)"
             if m.get("pitch") else "pitch untracked (noise or too short)")
    lines = [
        f"{os.path.basename(path)}  {m['duration']:.3f}s",
        f"  peak {m['peak_db']:.1f} dBFS (true {m['true_peak_db']:.1f}) | {m['lufs']:.1f} LUFS (max momentary {m['mmax']:.1f})"
        f" | crest {m['crest_db']:.1f} dB | centroid {m['centroid']:.0f} Hz",
        f"  energy <80Hz {m['low']:.0%} | 2-5kHz {m['harsh']:.0%} | >16kHz {m['air']:.1%} | lead {m['lead_ms']:.0f} ms",
        f"  attack {m['attack_ms']:.0f} ms | decay {m['decay_ms']:.0f} ms | hits {m['hits']} | {pitch}"
        + (f" | loop seam {m['seam']:.1f}" if "seam" in m else ""),
    ]
    return "\n".join(lines + [f"  {lv} {msg}" for lv, msg in issues])


def set_report(results, tolerance=1.5):
    """Loudness spread across a set (variants, one sound family). Files more than `tolerance` dB
    from the set's median LUFS stand out when the game plays them round-robin."""
    import statistics
    vals = {p: m["lufs"] for p, m in results if "lufs" in m}
    if len(vals) < 2:
        return ""
    mid = statistics.median(vals.values())
    out = [f"set: {len(vals)} files, median {mid:.1f} LUFS, spread {max(vals.values()) - min(vals.values()):.1f} dB"]
    odd = [(p, v - mid) for p, v in vals.items() if abs(v - mid) > tolerance]
    out += [f"  WARN {os.path.basename(p)} is {d:+.1f} dB off the set: change its gain by {-d:+.1f} dB" for p, d in odd]
    return "\n".join(out + ([] if odd else [f"  OK every file within {tolerance} dB of the median"]))


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
    ap.add_argument("--pitch", choices=PITCH_SHAPES, help="FAIL unless the pitch moves this way")
    ap.add_argument("--loop", action="store_true", help="check the wrap point (automatic for WAVs with a smpl loop)")
    ap.add_argument("--set", action="store_true", help="also compare loudness across the files (variants, one family)")
    args = ap.parse_args()
    expect = {k: [float(v) for v in getattr(args, k).split(":")] for k in ("duration", "centroid", "lufs") if getattr(args, k)}
    if args.pitch:
        expect["pitch"] = args.pitch

    failed, results = False, []
    for path in args.files:
        x, sr, ch = read_wav(path)
        loop = args.loop or wav_loop(path) is not None
        m, issues = analyze(x, sr, expect, loop)
        print(report(path, m, issues) + (f"\n  INFO stereo file analyzed as mono sum" if ch > 1 else ""))
        if args.png:
            write_png(x, sr, os.path.splitext(path)[0] + ".png")
        failed |= any(lv == "FAIL" for lv, _ in issues)
        results.append((path, m))
    if args.set:
        print(set_report(results))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
