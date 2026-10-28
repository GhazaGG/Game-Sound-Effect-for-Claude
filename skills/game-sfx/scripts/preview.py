#!/usr/bin/env python3
"""Lay sounds out the way the game will play them, so the user can judge them by ear.

  python preview.py "out/hoof_Dirt_*.wav" "out/hoof_Rock_*.wav" --pattern gallop -o sfx/preview/hooves.wav
  python preview.py "new/coin_*.wav" --before "old/coin*.wav" --pattern seq -o sfx/preview/coin_ab.wav

Each positional glob is one set (a surface, a sound). Its files play round-robin in --pattern.
With --before (one glob per set), every set plays its old version first, then the new one,
so the file is an A/B. Relative levels are kept (one gain for the whole file), and the
timeline of what plays when is printed for the user.
"""
import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sfx  # noqa: E402

SR = sfx.SR
# (hit offsets within one cycle, cycle length) in seconds
PATTERNS = {
    "gallop": ([0, 0.07, 0.16, 0.22], 0.42),
    "canter": ([0, 0.12, 0.24], 0.55),
    "trot": ([0, 0.25], 0.5),
    "walk": ([0, 0.3, 0.6, 0.9], 1.2),
}


def files(pattern):
    found = sorted(glob.glob(pattern))
    if not found:
        sys.exit(f"no files match {pattern!r}")
    return found


def play(clips, pattern, repeat, gap):
    """Mono buffer of `clips` round-robin in `pattern`; 'seq' = one after another."""
    if pattern == "seq":
        hits, t = [], 0.0
        for k in range(repeat * len(clips)):
            hits.append((t, clips[k % len(clips)]))
            t += len(clips[k % len(clips)]) / SR + gap
    else:
        offs, cycle = PATTERNS[pattern]
        hits = [(c * cycle + o, clips[(c * len(offs) + i) % len(clips)]) for c in range(repeat) for i, o in enumerate(offs)]
    n = max(int(t * SR) + len(x) for t, x in hits)
    buf = [0.0] * n
    for t, x in hits:
        s = int(t * SR)
        for i, v in enumerate(x):
            buf[s + i] += v
    return buf


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sets", nargs="+", help="one glob per set, quoted")
    ap.add_argument("--before", nargs="+", help="one glob per set: the old version, played first")
    ap.add_argument("--pattern", choices=["seq", *PATTERNS], default="seq")
    ap.add_argument("--repeat", type=int, default=3, help="cycles per set (seq: passes through the files)")
    ap.add_argument("-o", "--out", default="preview.wav")
    args = ap.parse_args()
    if args.before and len(args.before) != len(args.sets):
        sys.exit("--before needs one glob per set")

    out, timeline = [], []

    def add(label, pattern):
        timeline.append(f"{len(out) / SR:6.1f}s  {label}  ({len(files(pattern))} files)")
        out.extend(play([sfx.load_audio(f) for f in files(pattern)], args.pattern, args.repeat, 0.35))

    for i, new in enumerate(args.sets):
        label = os.path.basename(new).replace("*", "").replace(".wav", "").strip("_")
        if args.before:
            add(f"{label}  BEFORE", args.before[i])
            out.extend([0.0] * (SR // 3))
            add(f"{label}  AFTER", new)
        else:
            add(label, new)
        out.extend([0.0] * SR)

    peak = max(abs(v) for v in out) or 1.0
    sfx.write_wav(args.out, [v * 0.89 / peak for v in out])
    print(f"{args.out}  {len(out) / SR:.1f}s\n" + "\n".join(timeline))


if __name__ == "__main__":
    main()
