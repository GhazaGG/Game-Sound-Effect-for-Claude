"""Every recipe renders cleanly, deterministically, and variants differ.  python tests/test_recipes.py"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "game-sfx", "scripts"))
import doctor  # noqa: E402
import sfx  # noqa: E402

recipes = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "skills", "game-sfx", "recipes", "*.json")))
assert recipes, "no recipes found"
for path in recipes:
    patch = json.load(open(path, encoding="utf-8"))
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
