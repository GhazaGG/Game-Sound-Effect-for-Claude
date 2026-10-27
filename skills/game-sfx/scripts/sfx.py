#!/usr/bin/env python3
"""Render a JSON sound patch to a game-ready WAV. Python 3.8+ stdlib only.

  python sfx.py patch.json [-o OUT_DIR] [--variants N] [--seed S] [--png]

Every render is followed by a doctor report (see doctor.py). Patch format: SKILL.md.
"""
import argparse
import json
import math
import os
import random
import struct
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import doctor  # noqa: E402

SR = 44100
WAVES = ("sine", "triangle", "square", "saw", "noise")
FILTERS = ("lowpass", "highpass", "bandpass")


def sample_curve(spec, n, scale=1.0):
    """A number, or [[t, value], ...] breakpoints (t in seconds). Equal t = instant step.
    Positive values interpolate in log space, so Hz sweeps sound even."""
    if isinstance(spec, (int, float)):
        return [spec * scale] * n
    pts = [(float(t), float(v) * scale) for t, v in spec]
    out, i = [], 0
    for s in range(n):
        t = s / SR
        while i + 1 < len(pts) and t >= pts[i + 1][0]:
            i += 1
        t0, v0 = pts[i]
        if i + 1 == len(pts) or t < t0:
            out.append(v0)
            continue
        t1, v1 = pts[i + 1]
        x = (t - t0) / (t1 - t0)
        out.append(v0 * (v1 / v0) ** x if v0 > 0 and v1 > 0 else v0 + (v1 - v0) * x)
    return out


def polyblep(p, dt):
    # Band-limits the waveform jump so square/saw don't alias into harshness.
    if p < dt:
        p /= dt
        return p + p - p * p - 1
    if p > 1 - dt:
        p = (p - 1) / dt
        return p * p + p + p + 1
    return 0.0


def oscillator(kind, freqs, duty, rng, fm=None):
    """fm = (ratio, index per sample): sine phase-modulated by a sine at ratio * freq."""
    out, ph, mph = [], 0.0, 0.0
    for s, f in enumerate(freqs):
        dt = min(max(f, 0.0) / SR, 0.5)
        if kind == "sine":
            v = math.sin(2 * math.pi * ph + (fm[1][s] * math.sin(2 * math.pi * mph) if fm else 0.0))
            if fm:
                mph = (mph + f * fm[0] / SR) % 1.0
        elif kind == "triangle":
            v = 4 * abs(ph - 0.5) - 1
        elif kind == "square":
            v = (1.0 if ph < duty else -1.0) + polyblep(ph, dt) - polyblep((ph - duty) % 1.0, dt)
        elif kind == "saw":
            v = 2 * ph - 1 - polyblep(ph, dt)
        else:
            v = rng.uniform(-1, 1)
        out.append(v)
        ph += dt
        if ph >= 1:
            ph -= 1
    return out


def svf(x, kind, cutoffs, q):
    """Zavalishin TPT state-variable filter; stable under fast cutoff sweeps."""
    k = 1.0 / q
    ic1 = ic2 = 0.0
    out = []
    for v0, fc in zip(x, cutoffs):
        g = math.tan(math.pi * min(max(fc, 10.0), 0.45 * SR) / SR)
        a1 = 1 / (1 + g * (g + k))
        a2 = g * a1
        a3 = g * a2
        v3 = v0 - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2 * v1 - ic1
        ic2 = 2 * v2 - ic2
        if kind == "lowpass":
            out.append(v2)
        elif kind == "highpass":
            out.append(v0 - k * v1 - v2)
        else:
            out.append(k * v1)  # unity gain at center
    return out


def reverb(x, mix, decay, circular=False):
    """Small Schroeder room: 4 damped combs + 2 allpasses. `decay` = RT60 seconds.
    circular=True processes the buffer twice and keeps the second pass, so loops wrap their tail."""
    src = x + x if circular else x
    wet = [0.0] * len(src)
    for d in (1116, 1188, 1277, 1356):
        fb = 10 ** (-3 * d / (decay * SR))
        line, lp, i = [0.0] * d, 0.0, 0
        for s, v in enumerate(src):
            y = line[i]
            lp = y * 0.7 + lp * 0.3  # damping: tails get darker like real rooms
            line[i] = v + lp * fb
            i = (i + 1) % d
            wet[s] += y * 0.25
    for d in (556, 441):
        line, i = [0.0] * d, 0
        for s, v in enumerate(wet):
            y = line[i]
            line[i] = v + y * 0.5
            wet[s] = y - v * 0.5
            i = (i + 1) % d
    out = [(1 - mix) * a + mix * b for a, b in zip(src, wet)]
    return out[len(x):] if circular else out


def render_layer(layer, rng, pitch, gain_db):
    partials = layer.get("partials")
    if partials:  # [[ratio, gain_db, release_scale?], ...]: additive/modal timbres (wood, bell, metal)
        base = {k: v for k, v in layer.items() if k != "partials"}
        outs = []
        for ratio, gdb, *scale in partials:
            env = dict(base.get("env", {}))
            env["release"] = env.get("release", 0.1) * (scale[0] if scale else 1)
            outs.append(render_layer({**base, "env": env, "gain_db": base.get("gain_db", 0) + gdb}, rng, pitch * ratio, gain_db))
        mix = [0.0] * max(map(len, outs))
        for o in outs:
            for i, v in enumerate(o):
                mix[i] += v
        return mix

    kind = layer.get("wave", "sine")
    if kind not in WAVES:
        raise ValueError(f"unknown wave {kind!r}, use one of {WAVES}")
    env = layer.get("env", {})
    a = max(env.get("attack", 0.002), 0.0005)  # floor = no start click
    h = max(env.get("hold", 0.0), 0.0)
    r = max(env.get("release", 0.1), 0.005)
    curve = env.get("curve", 2.0)
    n = int((a + h + r) * SR)

    freqs = sample_curve(layer.get("freq", 440), n, pitch)
    vib = layer.get("vibrato")
    if vib:
        depth = sample_curve(vib.get("depth", 0.5), n)
        freqs = [f * 2 ** (d * math.sin(2 * math.pi * vib.get("rate", 6) * s / SR) / 12)
                 for s, (f, d) in enumerate(zip(freqs, depth))]
    fm = layer.get("fm")
    fm = (fm.get("ratio", 2), sample_curve(fm.get("index", 1), n)) if fm else None
    cents = layer.get("detune_cents", 0)
    duty = layer.get("duty", 0.5)
    if cents and kind != "noise":
        up = oscillator(kind, [f * 2 ** (cents / 2400) for f in freqs], duty, rng, fm)
        dn = oscillator(kind, [f * 2 ** (-cents / 2400) for f in freqs], duty, rng, fm)
        x = [(u + d) * 0.5 for u, d in zip(up, dn)]
    else:
        x = oscillator(kind, freqs, duty, rng, fm)

    for flt in layer.get("filters", []):
        if flt.get("type") not in FILTERS:
            raise ValueError(f"unknown filter {flt.get('type')!r}, use one of {FILTERS}")
        x = svf(x, flt["type"], sample_curve(flt["cutoff"], n, pitch), flt.get("q", 0.707))

    drive = layer.get("drive", 0)
    if drive:
        norm = math.tanh(1 + drive)
        x = [math.tanh(v * (1 + drive)) / norm for v in x]

    g = 10 ** ((layer.get("gain_db", 0) + gain_db) / 20)
    ai, hi = a * SR, (a + h) * SR
    rn = n - hi
    for s in range(n):
        if s < ai:
            amp = s / ai
        elif s < hi:
            amp = 1.0
        else:
            amp = max(0.0, 1 - (s - hi) / rn) ** curve  # always lands on 0 = no end click
        x[s] *= amp * g
    return x


def render(patch, seed=0, variant=False):
    rng = random.Random(seed)
    vary = patch.get("vary", {}) if variant else {}
    master = patch.get("master", {})
    gpitch = 2 ** (rng.uniform(-1, 1) * vary.get("pitch", 0) / 12)

    events = []
    for layer in patch["layers"]:
        j = layer.get("jitter", {})
        for t in layer.get("at", [0]):
            # Same draw for every layer firing at the same time, so stacked layers move together.
            jr = random.Random(f"{seed}/{t}")
            dt, dp, dg = jr.uniform(-1, 1), jr.uniform(-1, 1), jr.uniform(-1, 1)
            start = max(0.0, t + dt * j.get("time", 0))
            p = gpitch * 2 ** (dp * j.get("pitch", 0) / 12)
            events.append((int(start * SR), render_layer(layer, rng, p, dg * j.get("gain_db", 0))))

    fixed = patch.get("duration")
    rv = master.get("reverb")
    n = int(fixed * SR) if fixed else max(s + len(x) for s, x in events) + (int(rv["decay"] * SR) if rv else 0)
    buf = [0.0] * n
    for s, x in events:
        for i, v in enumerate(x if fixed else x[: max(0, n - s)]):
            buf[(s + i) % n] += v  # fixed duration = loop: tails wrap to the start

    hp = [master.get("highpass", 20)] * (2 * n if fixed else n)
    buf = svf(buf + buf, "highpass", hp, 0.707)[n:] if fixed else svf(buf, "highpass", hp, 0.707)  # kills DC + rumble
    if rv:
        buf = reverb(buf, rv.get("mix", 0.15), rv["decay"], circular=bool(fixed))

    peak = max(abs(v) for v in buf) or 1.0
    if not fixed:  # trim tail below -60 dB, before measuring loudness
        end = max((i for i, v in enumerate(buf) if abs(v) > peak * 1e-3), default=0)
        buf = buf[: end + 1]

    gain = 10 ** (master.get("peak_db", -1.0) / 20) / peak
    if "lufs" in master:
        gain = min(gain, 10 ** ((master["lufs"] - doctor.loudness(buf, SR)) / 20))
    gain *= 10 ** (-rng.uniform(0, vary.get("gain_db", 0)) / 20)
    buf = [v * gain for v in buf]

    if fixed:
        return buf  # seamless loop: end flows into start, a fade would make a gap
    fade = min(int(0.005 * SR), len(buf))
    for i in range(fade):
        buf[len(buf) - 1 - i] *= i / fade
    return buf


def write_wav(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(round(max(-1.0, min(1.0, v)) * 32767))) for v in x))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patch")
    ap.add_argument("-o", "--out", default=".")
    ap.add_argument("--variants", type=int, default=0, help="render N randomized round-robin variants")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--png", action="store_true", help="also write a spectrogram PNG per file")
    args = ap.parse_args()

    with open(args.patch, encoding="utf-8") as f:
        patch = json.load(f)
    name = patch.get("name") or os.path.splitext(os.path.basename(args.patch))[0]
    os.makedirs(args.out, exist_ok=True)

    jobs = [(f"{name}_{i + 1:02d}", args.seed + i, True) for i in range(args.variants)] or [(name, args.seed, False)]
    failed = False
    for stem, seed, variant in jobs:
        x = render(patch, seed, variant)
        path = os.path.join(args.out, stem + ".wav")
        write_wav(path, x)
        expect = dict(patch.get("expect") or {})
        if variant and "lufs" in expect:  # variants are deliberately up to vary.gain_db quieter
            lo, hi = expect["lufs"]
            expect["lufs"] = [lo - patch.get("vary", {}).get("gain_db", 0), hi]
        metrics, issues = doctor.analyze(x, SR, expect)
        print(doctor.report(path, metrics, issues))
        if args.png:
            doctor.write_png(x, SR, os.path.join(args.out, stem + ".png"))
        failed |= any(level == "FAIL" for level, _ in issues)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
