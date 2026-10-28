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
