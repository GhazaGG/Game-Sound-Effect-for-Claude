# 🔊 game-sfx: game sound effects Claude can actually design

Ask Claude for a coin sound and you usually get a raw beep that clicks, hisses and lasts too long. Claude can't hear, so it can't tell.

**game-sfx** is a Claude Code skill that works around that:

- **Recipes.** Layered patches (transient + body + tail) built from sound-design practice and sfxr's own presets.
- **Synth.** A click-proof synth with band-limited oscillators, envelopes that always end at zero, DC removal, LUFS-matched loudness and tail trimming.
- **Doctor.** Measures peak, LUFS, crest, brightness and harsh/aliasing energy, then draws a **spectrogram PNG**. Claude reads that picture to check its own work.

The synth is **pure Python stdlib**: no pip install, no API key, works offline. For realistic foley (hooves, footsteps, water) the **sample pipeline** finds CC0 recordings on Freesound, cuts out the cleanest hits and makes them game-ready (needs a free Freesound key + ffmpeg). Output is game-ready WAV for Godot, Unity, Unreal, Phaser and anything else.

## Install

In Claude Code:

```
/plugin marketplace add GhazaGG/Game-Sound-Effect-for-Claude
/plugin install game-sfx@game-sfx
```

Or copy `skills/game-sfx/` into `~/.claude/skills/`.

## Use

Just ask:

> make a coin pickup sound for my platformer, with 4 variants

> my hit sounds are weak, audit `assets/sfx/` and fix them

> I need a looping horse gallop for a courier game

Claude picks a recipe, renders it, reads the doctor report and spectrogram, iterates, and writes the files into your project. The JSON patch stays in your project too, so you can tweak it later.

You can also run the scripts yourself:

```bash
python skills/game-sfx/scripts/sfx.py skills/game-sfx/recipes/coin_cartoon.json -o out --variants 4 --png
python skills/game-sfx/scripts/doctor.py path/to/your/*.wav --png
```

```
coin_cartoon.wav  0.594s
  peak -6.4 dBFS | -16.0 LUFS | crest 12.1 dB | centroid 3452 Hz
  energy <80Hz 0% | 2-5kHz 41% | >16kHz 0.0% | lead 0 ms
  OK no problems found
```

## Included recipes

Listen to them in [`examples/`](examples/).

| Recipe | Style | What it is |
|---|---|---|
| `coin_cartoon` | cartoon | FM-bell "bling" with shimmer and a small room |
| `jump_cartoon` | cartoon | Springy "boing" with a decaying wobble |
| `hit_cartoon` | cartoon | Rounded "bonk": thump plus woodblock knock |
| `horse_gallop_cartoon` | cartoon | Coconut-shell clip-clop, seamless loop |
| `coin_retro` | retro | Two-note square pickup |
| `jump_retro` | retro | Detuned square sweeping up |
| `hit` | grounded | Noise snap + saturated thump + crunch |
| `horse_gallop` | grounded | Dirt gallop loop, humanized per hoof |
| `ui_click` | any | Tiny tick + blip |

Styles are first-class. Tell Claude your game's look and every sound comes from the same palette (see [SKILL.md](skills/game-sfx/SKILL.md#style)).

[SKILL.md](skills/game-sfx/SKILL.md) has a recipe table for 12 more categories: laser, explosion, power-up, hurt, death, jingle, footstep, whoosh, magic and the UI hover, confirm and error sounds.

## It learns your game

Claude doesn't make sounds blind. On first use it does three things:

1. **Detects your engine** (Godot, Unity, Unreal, Phaser, GameMaker, LÖVE, Pygame) and its audio folder.
2. **Reads your project.** It looks at the README, design docs and art, audits the sounds you already have, and greps your code for gameplay events (`jump`, `collect`, `hit`...) that have no sound yet.
3. **Writes `sfx/SOUND_STYLE.md`**, a short sound bible covering style, palette, world materials, music key and loudness tiers. Every future sound follows it, so they all sound like one game.

Every sound keeps its editable source in `sfx/patches/<name>.json`. To change one, say "the coin is too shrill" and Claude edits the patch, re-renders it to the same file and logs the decision. Or edit the JSON yourself.

## How it works

```
request → recipe → sfx.py (render) → doctor.py (metrics + spectrogram) → Claude looks → tweak → variants → your assets/
```

## Roadmap

- [ ] More tested recipes (explosion, laser, footsteps per surface, magic)
- [ ] OGG export and engine import snippets
- [ ] Optional AI backends for realistic sounds (ElevenLabs, Stable Audio Open)
- [ ] Web demo page: prompt → sound, side by side with a naive beep

## Test

```bash
python tests/test_recipes.py
```

MIT licensed. Sounds you make with it are yours.
