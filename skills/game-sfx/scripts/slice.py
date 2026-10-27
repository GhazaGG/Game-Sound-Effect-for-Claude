#!/usr/bin/env python3
"""Cut single hits (hoofbeats, footsteps, impacts) out of a recording and make them game-ready.

  python slice.py rec.ogg [more ...] --list                  # show every detected hit, scored
  python slice.py rec.ogg -o assets/sfx --name hoof_Dirt --count 4 [--pick 0:12,1:3] [--png]

Each output is trimmed, faded, high-passed and normalized to --lufs under a --peak ceiling,
then checked by the doctor. Without --pick, the cleanest --count hits are taken: loud, with
little sound bleeding in just before them, and decayed before the next hit. --pick takes
SOURCE:INDEX pairs from --list (SOURCE is the file's position on the command line).
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import doctor  # noqa: E402
import sfx  # noqa: E402

SR = sfx.SR
HOP = 128  # ~3 ms envelope frames


def envelope_db(x):
    out = []
    for i in range(0, len(x) - HOP, HOP):
        ms = sum(v * v for v in x[i:i + HOP]) / HOP
        out.append(10 * math.log10(ms + 1e-12))
    return out


def detect(x, min_gap, max_len, rise_db=9.0, floor_db=35.0):
    """Hits = frames where the envelope jumps rise_db above its last ~12 ms, within floor_db of the loudest."""
    env = envelope_db(sfx.svf(x, "highpass", [150] * len(x), 0.707))  # ignore rumble and wind
    top = max(env)
    gap = int(min_gap * SR / HOP)
    onsets = []
    for i in range(4, len(env)):
        if env[i] - min(env[i - 4:i]) > rise_db and env[i] > top - floor_db and (not onsets or i - onsets[-1] >= gap):
            onsets.append(i)
    hits = []
    for k, i in enumerate(onsets):
        start = max(0, i * HOP - int(0.003 * SR))
        nxt = onsets[k + 1] * HOP - int(0.003 * SR) if k + 1 < len(onsets) else len(x)
        end = min(nxt, start + int(max_len * SR), len(x))
        if end - start < int(0.04 * SR):
            continue
        seg_env = env[i:end // HOP] or [env[i]]
        peak = max(seg_env)
        pre = max(env[max(0, i - int(0.05 * SR / HOP)):i - 1] or [-120])
        decay = peak - seg_env[-1]
        hits.append({"start": start, "end": end, "peak": peak - top, "clean": peak - pre, "decay": decay,
                     "score": (peak - top) + 0.5 * min(peak - pre, 30) + 0.4 * min(decay, 40)})
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="+")
    ap.add_argument("-o", "--out", default=".")
    ap.add_argument("--name", default="hit")
    ap.add_argument("--count", type=int, default=4)
    ap.add_argument("--pick", help="SOURCE:INDEX,... from --list")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--min-gap", type=float, default=0.06, help="s between hits (gallop ~0.06, walk ~0.2)")
    ap.add_argument("--max-len", type=float, default=0.3, help="s, longest cut")
    ap.add_argument("--lufs", type=float, default=-19)
    ap.add_argument("--peak", type=float, default=-1)
    ap.add_argument("--highpass", type=float, default=60)
    ap.add_argument("--lowpass", type=float, default=0, help="Hz, 0 = off")
    ap.add_argument("--tail-db", type=float, default=35, help="cut the tail this far under the peak")
    ap.add_argument("--limit-db", type=float, default=6, help="max peak limiting used to reach --lufs")
    ap.add_argument("--png", action="store_true")
    args = ap.parse_args()

    audio = [sfx.load_audio(p) for p in args.sources]
    found = [(s, k, h) for s, x in enumerate(audio)
             for k, h in enumerate(detect(x, args.min_gap, args.max_len))]
    if args.list or not found:
        print(f"{len(found)} hits   (peak = dB below loudest, clean = dB above what precedes it, decay = dB it falls before the cut)")
        for s, k, h in sorted(found, key=lambda f: -f[2]["score"]):
            print(f"  {s}:{k:<4} at {h['start'] / SR:7.2f}s  len {1000 * (h['end'] - h['start']) / SR:4.0f} ms  "
                  f"peak {h['peak']:5.1f}  clean {h['clean']:4.1f}  decay {h['decay']:4.1f}  score {h['score']:5.1f}   {os.path.basename(args.sources[s])}")
        return

    by_id = {(s, k): h for s, k, h in found}
    if args.pick:
        chosen = [(int(a), int(b)) for a, b in (p.split(":") for p in args.pick.split(","))]
    else:
        chosen = [(s, k) for s, k, _ in sorted(found, key=lambda f: -f[2]["score"])[: args.count]]

    os.makedirs(args.out, exist_ok=True)
    master = {"lufs": args.lufs, "peak_db": args.peak, "highpass": args.highpass, "limit_db": args.limit_db}
    failed = False
    for n, (s, k) in enumerate(chosen, 1):
        h = by_id[(s, k)]
        x = audio[s][h["start"]:h["end"]]
        if args.lowpass:
            x = sfx.svf(x, "lowpass", [args.lowpass] * len(x), 0.707)
        env = envelope_db(x)
        if env:  # end where it sinks tail_db under its peak: drops the room/noise bed that would repeat every hit
            last = max(i for i, e in enumerate(env) if e > max(env) - args.tail_db)
            x = x[: min(len(x), (last + 1) * HOP + int(0.015 * SR))]
        fi, fo = min(int(0.002 * SR), len(x)), min(int(0.015 * SR), len(x))
        for i in range(fi):  # cut lands mid-noise: fade in so it can't click
            x[i] *= i / fi
        for i in range(fo):
            x[len(x) - 1 - i] *= i / fo
        x = sfx.finish(x, master)
        path = os.path.join(args.out, f"{args.name}_{n:02d}.wav")
        sfx.write_wav(path, x)
        m, issues = doctor.analyze(x, SR)
        print(doctor.report(path, m, issues) + f"\n  from {os.path.basename(args.sources[s])} at {h['start'] / SR:.2f}s")
        if args.png:
            doctor.write_png(x, SR, os.path.splitext(path)[0] + ".png")
        failed |= any(lv == "FAIL" for lv, _ in issues)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
