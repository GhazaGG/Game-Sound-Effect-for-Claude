"""Every recipe renders cleanly, deterministically, and variants differ.  python tests/test_recipes.py"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "game-sfx", "scripts"))
import doctor  # noqa: E402
import sfx  # noqa: E402

recipes = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "skills", "game-sfx", "recipes", "*.json")))
assert recipes, "no recipes found"
for path in recipes:
    patch = sfx.load_patch(path)
    x = sfx.render(patch)
    m, issues = doctor.analyze(x, sfx.SR, patch.get("expect"))
    bad = [msg for lv, msg in issues if lv != "OK"]
    assert not bad, f"{os.path.basename(path)}: {bad}"
    if patch.get("duration"):  # loop: the wrap point must be continuous
        assert abs(x[-1] - x[0]) < 0.02, f"{path}: click at loop point"
    else:
        assert abs(x[0]) < 1e-3 and abs(x[-1]) < 1e-3, f"{path}: click at boundary"
    assert x == sfx.render(patch), f"{path}: not deterministic"
    assert sfx.render(patch, 1, True) != sfx.render(patch, 2, True), f"{path}: variants identical"
    print("ok", os.path.basename(path))

# doctor catches a classic bad sound: raw square, no envelope, clipped
bad = [1.0 if (i // 50) % 2 else -1.0 for i in range(4410)]
levels = {lv for lv, _ in doctor.analyze(bad, 44100)[1]}
assert "FAIL" in levels, levels
print("ok doctor flags bad sound")

# slicer finds isolated hits in a noisy "recording"; the limiter holds the ceiling
import random  # noqa: E402
import slice as slicer  # noqa: E402

rng = random.Random(1)
rec = [rng.uniform(-0.002, 0.002) for _ in range(sfx.SR * 2)]
for t in (0.3, 0.9, 1.5):
    for i in range(2000):
        rec[int(t * sfx.SR) + i] += rng.uniform(-1, 1) * 0.8 * (1 - i / 2000) ** 3
hits = slicer.detect(rec, 0.06, 0.3)
assert [round(h["start"] / sfx.SR, 1) for h in hits] == [0.3, 0.9, 1.5], hits
assert max(abs(v) for v in sfx.limit([v * 4 for v in rec], 0.89)) <= 0.89 + 1e-9
print("ok slicer + limiter")

# typos in a patch are errors, not silently ignored keys
try:
    sfx.validate({"layers": [{"wave": "sine", "filter": [], "env": {"decay": 0.2}}]})
    raise AssertionError("typo accepted")
except ValueError as e:
    assert "'filters'" in str(e) and "'release'" in str(e), e
print("ok patch validation")

# doctor checks intent: pitch direction, true peak, hits, loop seam, set loudness
import math  # noqa: E402
import tempfile  # noqa: E402
import wave  # noqa: E402

SR = sfx.SR


def sweep(f0, f1, dur=0.4):
    ph, out = 0.0, []
    for i in range(int(dur * SR)):
        ph += 2 * math.pi * f0 * (f1 / f0) ** (i / (dur * SR)) / SR
        out.append(0.5 * math.sin(ph) * min(1, i / 200, (dur * SR - i) / 200))
    return out


assert doctor.analyze(sweep(300, 900), SR, {"pitch": "rising"})[0]["pitch"] == "rising"
assert doctor.analyze(sweep(900, 200), SR)[0]["pitch"] == "falling"
assert doctor.analyze(sweep(440, 440), SR)[0]["pitch"] == "steady"
assert doctor.analyze([rng.uniform(-0.5, 0.5) for _ in range(SR // 2)], SR)[0]["pitch"] is None
m, issues = doctor.analyze(sweep(900, 200), SR, {"pitch": "rising"})
assert any(lv == "FAIL" and "pitch" in msg for lv, msg in issues), issues
print("ok pitch direction")

# a sine at SR/4 sampled 45 degrees off its peaks: every sample is 0.707, the real wave reaches 1.0
tp_sig = [math.sin(math.pi / 2 * i + math.pi / 4) for i in range(2000)]
assert max(abs(v) for v in tp_sig) < 0.71 and doctor.true_peak(tp_sig) > 0.95
print("ok true peak")

two = [0.0] * SR
for t in (0.1, 0.5):
    for i in range(800):
        two[int(t * SR) + i] = rng.uniform(-1, 1) * 0.6 * (1 - i / 800) ** 2
assert doctor.envelope_stats(two, SR)["hits"] == 2
print("ok hit count")

loop_patch = sfx.load_patch(os.path.join(os.path.dirname(recipes[0]), "horse_gallop_cartoon.json"))
lx = sfx.render(loop_patch)
assert doctor.loop_seam(lx) < 2, doctor.loop_seam(lx)
cut = [math.sin(2 * math.pi * 437 * i / SR) * 0.5 for i in range(SR // 3)]  # stops mid-cycle
assert doctor.loop_seam(cut) > 2, doctor.loop_seam(cut)
with tempfile.TemporaryDirectory() as tmp:
    p = os.path.join(tmp, "loop.wav")
    sfx.write_wav(p, lx, loop=True)
    assert doctor.wav_loop(p) == (0, len(lx) - 1)
    with wave.open(p, "rb") as w:
        assert w.getnframes() == len(lx)
    sfx.write_wav(p, lx)
    assert doctor.wav_loop(p) is None
print("ok loop seam + smpl chunk")

out = doctor.set_report([("a.wav", {"lufs": -18.0}), ("b.wav", {"lufs": -18.4}), ("c.wav", {"lufs": -14.0})])
assert "WARN c.wav" in out and "a.wav" not in out, out
print("ok set loudness")

try:
    sfx.validate({"layers": [{"wave": "sine"}], "expect": {"pitch": "up"}})
    raise AssertionError("bad pitch accepted")
except ValueError as e:
    assert "expect.pitch" in str(e), e
print("ok pitch validation")

# freesound builds the documented /search/ queries (no network: `call` is stubbed)
import freesound  # noqa: E402

sent = []
freesound.call = lambda path, **p: sent.append((path, p)) or {"results": []}
freesound.search("hooves", single=True, dry=True)
freesound.search("", similar_to=434804)
(p1, a), (p2, b) = sent
assert p1 == p2 == "/search/", sent
assert 'license:"Creative Commons 0"' in a["filter"] and "single_event:true" in a["filter"] and "reverbness:false" in a["filter"]
assert a["sort"] == "score" and "similar_to" not in a
assert b["similar_to"] == 434804 and b["similarity_space"] == "laion_clap" and "sort" not in b and "Creative Commons 0" in b["filter"]
print("ok freesound queries")
