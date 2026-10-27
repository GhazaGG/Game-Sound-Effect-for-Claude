---
name: game-sfx
description: Design and render game sound effects (coin, jump, hit, UI click, footsteps, explosions, lasers, magic, horse gallop...) as game-ready WAV files, and audit existing sound files. Use whenever the user wants a sound effect, SFX, audio feedback, or game audio, or says their game sounds are bad. Zero dependencies, offline, no API key.
---

# Game SFX

You cannot hear. This skill replaces hearing with three things: **proven recipes**, a **synth that makes the classic mistakes impossible** (clicks, aliasing, DC, clipping, silent tails), and a **doctor** that measures the result and draws a spectrogram you can look at.

Scripts live next to this file: `scripts/sfx.py` (render) and `scripts/doctor.py` (check). Both are Python 3.8+ stdlib only.

## Step 0: know the project (before the first sound)

Generic sounds come from not knowing the game. Before designing anything, look for `sfx/SOUND_STYLE.md` in the project.

**If it exists, read it and follow it.** It is the project's sound bible, and every new sound must belong to that family.

**If it doesn't exist, build it.** Do this once per project and keep it short:

1. **Engine and audio folder.** Detect the engine from files in the project, then use its usual audio folder (or the one the project already uses):

   | File | Engine | Audio folder |
   |---|---|---|
   | `project.godot` | Godot | `audio/sfx/` |
   | `ProjectSettings/ProjectVersion.txt` | Unity | `Assets/Audio/SFX/` |
   | `*.uproject` | Unreal | `Content/Audio/SFX/` |
   | `package.json` with phaser/pixi/howler | Web | `public/assets/sfx/`, plus OGG |
   | `*.yyp` | GameMaker | `sounds/` |
   | `conf.lua` / `main.lua` | LÖVE | `assets/sfx/` |
   | `import pygame` | Pygame | `assets/sfx/` |
2. **Identity.** Read the README, design docs and store text. Glance at the sprites and art folder: they show the style better than prose does. Note the theme, mood, setting, world materials (wood, stone, metal, dirt, water, cloth, magic), and the music's key and tempo if there is music.
3. **Existing sounds.** Run the doctor over them: `doctor.py <audio folder>/*.wav --png`. Keep what works. The good ones show what the project already sounds like.
4. **Missing sounds.** Grep the game code for gameplay events and for where sounds are already played. Look for jump, land, collect, pickup, coin, hit, hurt, damage, die, attack, shoot, click, button, open, close, win, lose, level, spawn, dash and step. Also look for the engine's play calls: `AudioStreamPlayer`, `PlayOneShot`, `this.sound.play`, `love.audio.play`, `pygame.mixer`. List the events that have no sound yet, ranked by how often the player triggers them.
5. **Write `sfx/SOUND_STYLE.md`** from [templates/SOUND_STYLE.md](templates/SOUND_STYLE.md). Fill in everything you found, ask only about what you couldn't find (usually just the style, in one question), and show the user the sound list before generating it.

Layout in the user's project:

```
sfx/SOUND_STYLE.md        sound bible: style, palette, materials, loudness, decisions
sfx/patches/<name>.json   one patch per sound (the editable source)
<audio folder>/<name>.wav rendered output that the game loads
```

## Changing a sound later

When the user says something like "the coin is too shrill" or "the jump needs more bounce":

1. Open `sfx/patches/<name>.json`.
2. Translate the words into parameters. For example:
   - shrill → lower the notes or the FM index, low-pass at 6-8 kHz
   - weak → add a driven sub layer or a longer body
   - cheap/generic → add a layer or partials, a small room, pitch that moves
   - too long → shorter release, less reverb
3. Re-render to the **same file name**, so the game's references keep working.
4. Add one line to Decisions in `SOUND_STYLE.md` (e.g. "coin: lowered a 4th, players found it shrill"), so future sounds don't repeat the mistake.

## Workflow

1. **Classify** the request into a category from the table below. Take the style from `SOUND_STYLE.md`; if there isn't one, do Step 0 first.
2. **Start from a recipe** in `recipes/` that matches the style. Copy it to `sfx/patches/<name>.json` and edit it for the game's materials and palette. Otherwise write a patch using the category table.
3. **Render with a picture** into a preview folder while you iterate:
   `python <skill>/scripts/sfx.py sfx/patches/<name>.json -o sfx/preview --png`
   Once it's right, render the final version (without `--png`) with `-o <audio folder>`. `sfx/preview/` is scratch space, so suggest adding it to `.gitignore`.
4. **Read the doctor report and open the PNG.** Fix every FAIL/WARN. Check the picture matches intent: the pitch moves the right way, the transient is at the start, the tail dies out.
5. **Iterate** 1-3 times, changing one thing at a time. Tell the user what you changed and why in sound terms ("lowered the thump to 60 Hz for more weight").
6. **Variants** for anything heard often (footsteps, hits, pickups): `--variants 4` writes `name_01..04.wav` with pitch/gain variation from the patch's `vary`. Play them round-robin in the game, never the same one twice in a row.
7. **Wire it up** in the engine (see Delivery) and keep the patch JSON in the repo so the sound can be tweaked later.

Audit sounds the user already has: `python <skill>/scripts/doctor.py assets/sfx/*.wav --png`.

## Patch format

```json
{
  "name": "coin",
  "duration": null,
  "layers": [
    {
      "wave": "square",
      "duty": 0.5,
      "freq": [[0, 988], [0.06, 988], [0.06, 1319]],
      "detune_cents": 0,
      "env": {"attack": 0.001, "hold": 0.06, "release": 0.22, "curve": 2.5},
      "filters": [{"type": "lowpass", "cutoff": 9000, "q": 0.707}],
      "drive": 0,
      "gain_db": 0,
      "at": [0],
      "jitter": {"time": 0, "pitch": 0, "gain_db": 0}
    }
  ],
  "master": {"lufs": -16, "peak_db": -1, "highpass": 150},
  "vary": {"pitch": 1, "gain_db": 1},
  "expect": {"duration": [0.2, 0.4], "centroid": [1500, 6000]}
}
```

| Field | Meaning |
|---|---|
| `wave` | `sine` (pure, thin alone), `triangle` (soft), `square` (+`duty`, chiptune), `saw` (buzzy), `noise` (white; shape it with filters) |
| `freq`, `cutoff` | A number, or `[[t, value], ...]` breakpoints in seconds from the layer start. Sweeps are exponential. Two points with the same `t` make an instant step (arpeggios). |
| `env` | `attack` (min 0.5 ms), `hold` at full level, `release` to exactly zero. `curve` 1 = linear fade, 2-3 = percussive. Layer length = attack + hold + release. |
| `filters` | Applied in order. `lowpass` / `highpass` / `bandpass`; `q` 0.7 = gentle, 4-8 = resonant ring. Bandpass is unity gain at the center. |
| `detune_cents` | Two slightly detuned copies. 5-15 makes it thick instead of thin. |
| `drive` | tanh saturation. 0.5-2 adds warmth and loudness to low thumps. |
| `fm` | `{"ratio": 3, "index": [[0, 2.5], [0.4, 0.3]]}` (sine only). Integer ratio = glassy/bell; 1.4 or 3.5 = metallic/gong. A falling index gives a "bling" that mellows. |
| `partials` | `[[ratio, gain_db, release_scale], ...]` stacks copies of the layer at frequency ratios. Wood/xylophone `[[1,0,1],[2.76,-8,0.5],[5.4,-16,0.3]]`. Bell `[[1,0,1],[2.4,-4,0.8],[5.95,-10,0.5]]`. Rich tone `[[1,0,1],[2,-10,0.6],[3,-18,0.4]]`. |
| `vibrato` | `{"rate": 16, "depth": semitones or breakpoints}`. 5-7 Hz = singing. 12-20 Hz with a decaying depth = spring "boing". |
| `gain_db` | Layer balance. The master is normalized afterwards, so only the differences between layers matter. |
| `at` | Start times. A list fires the layer repeatedly (footsteps, gallops, rolls). |
| `jitter` | Per-hit humanizing: ±seconds, ±semitones, ±dB. Layers firing at the same `at` time share the same draw, so stacked layers move together. |
| `duration` | Fixed length in seconds, for loops. Leave it null for one-shots: the tail is trimmed at -60 dB. |
| `master` | Final high-pass (Hz), loudness target (`lufs`), and peak ceiling (`peak_db`); the quieter of the two wins. `reverb`: `{"mix": 0.1, "decay": 0.4}` adds a small room. Loops wrap their reverb tail seamlessly. |
| `vary` | Variant spread: ±semitones for the whole sound, and up to -dB. Only used with `--variants`. |
| `expect` | Ranges the doctor enforces as FAIL: `duration`, `centroid`, `lufs`, `lead_ms`, `tail_ms`. |

## Rules that make SFX sound good

- **Layer it.** One oscillator sounds like a test tone. Build **transient** (0-30 ms, noise or click, high-passed above 1-2 kHz) + **body** (30-200 ms, tonal, 100-1000 Hz) + **tail** (filtered noise or a decaying tone) + an optional **sweetener** (sparkle, debris). Give each layer its own frequency lane.
- **Pitch should move.** Down for hits, lasers, hurt and death. Up for jumps, power-ups and confirms. Steps for coins and jingles. Static pitch only for UI ticks.
- **Short.** UI 15-80 ms. Pickups 150-400 ms. Impacts 100-300 ms. Only explosions, magic and jingles go past 0.5 s.
- **No mud.** High-pass UI and pickups at 150-300 Hz. Keep the sub (40-80 Hz) for impacts and explosions only.
- **Tame the top.** Low-pass bright square/saw/noise layers at 8-12 kHz. Too much 2-5 kHz energy is fatiguing when heard 500 times.
- **Loudness ladder** (`master.lufs`): hero impacts and explosions -12 to -14, pickups and jumps -16, footsteps and loops -18 to -20, UI -20 to -24. Peak is never above -1.

## Style

Each style uses one toolset. Use it for every sound in the game so they all feel related.

| Style | Sources | Character |
|---|---|---|
| **Retro / chiptune** | `square` (duty 0.125/0.25/0.5), `triangle`, `noise`; no reverb | Hard pitch steps, arpeggios, short decays |
| **Cartoon / casual** | `sine` + `fm` (bells, bling), `partials` (wood, xylophone, marimba), `vibrato` (boing, wobble), driven sine thumps; small `reverb` (mix 0.08-0.18) | Round, soft and bouncy. Pitch overshoot and settle. No harsh noise and no square buzz. |
| **Grounded / realistic** | Filtered `noise` textures, resonant band-passes, low thumps, modal `partials` for objects | Sounds like a material. Many jittered micro-hits. Ceiling: for truly realistic sounds, suggest recorded CC0 samples (Freesound) layered with these. |

## Category recipes

Starting points. Values are typical ranges; ✓ marks a tested recipe in `recipes/`, named `<sound>_<style>.json`.

| SFX | Recipe |
|---|---|
| Coin, retro ✓ | Square at 50% duty, two notes a 4th up (988→1319 Hz), 60 ms + 200 ms decay, plus a quiet octave sine |
| Coin, cartoon ✓ | FM bell (ratio 3, index 2.5→0.3) on B5→F#6, octave shimmer partials, a noise glint on the 2nd note, reverb 0.18 |
| Jump, retro ✓ | Square, 8 cents detune, 180→520 Hz over 180 ms, low-pass opening 2.5→6 kHz |
| Jump, cartoon ✓ | "Boing": sine with rich partials rising 220→540 Hz then settling to 480 Hz, a 16 Hz spring vibrato that decays, a soft band-passed air whoosh |
| Hit, grounded ✓ (`hit`) | Noise snap (HP 2 kHz, 15 ms) + driven sine 160→55 Hz (150 ms) + band-pass noise 1200→400 Hz crunch |
| Hit, cartoon ✓ | "Bonk": driven sine 300→70 Hz + woodblock partials at 520 Hz + soft cloth slap, reverb 0.1 |
| UI click ✓ | Noise tick (HP 3 kHz, 6 ms) + triangle 2000→1700 Hz (25 ms), master HP 300 Hz, -20 LUFS |
| Horse gallop, grounded ✓ (`horse_gallop`) | Loop of 4 strides at 0.42 s, footfalls at 0/0.07/0.16/0.22 s within each stride. Each hoof = click + band-pass noise "clop" (850 Hz, q 5) + sine thump 140→70 Hz + dirt noise. Accent the 4th footfall. Jitter ±8 ms, ±3 dB, ±0.8 st. |
| Horse gallop, cartoon ✓ | Coconut-shell "clip-clop": woodblock partials alternating 900/640 Hz on the same footfalls + hollow band-pass at 450 Hz (q 6) + a soft accent thump, reverb 0.12 |
| UI hover | Sine or triangle at 2-3 kHz, 20-40 ms, 6 dB below the click |
| UI confirm | Two rising notes (major 3rd or 5th), 60 + 120 ms, triangle or square |
| UI error / deny | Two falling notes, or a buzz at 150-250 Hz (square/saw), 200-300 ms |
| Laser / shoot | Saw or square, 1500→300 Hz over 100-250 ms + a 5 ms noise click |
| Explosion | Noise with low-pass sweeping 3 kHz→200 Hz over 0.8-1.5 s, driven sub sine 60→35 Hz, noise crack at the start (HP 1 kHz, 30 ms), -12 LUFS |
| Power-up | Square or saw sweep 200→1200 Hz over 300-600 ms, or a fast rising arpeggio |
| Hurt / damage | Square 600→150 Hz over 150 ms + noise burst, a little drive |
| Death / game over | Square or triangle 600→60 Hz over 0.8-1.2 s, or a slow falling arpeggio |
| Level-up jingle | Major arpeggio C-E-G-C (523/659/784/1047 Hz), 90 ms per note, last note held 400 ms; layer square + triangle an octave up |
| Footstep | Heel hit + toe hit 30-50 ms later: noise LP 800-2000 Hz (by surface) + tiny thump at 100-150 Hz, 80-150 ms. 4-5 variants with jitter. |
| Whoosh / swing | Noise band-pass with center 300→2000→500 Hz (q 1.5-3), envelope peaking 40-60% in, 150-400 ms |
| Magic / sparkle | 15-40 sine layers at 2-8 kHz, 20-40 ms each, `at` scattered over 0.6 s with jitter, plus a soft pad note |

## Reading the doctor

- **peak / LUFS**: the level. LUFS is perceived loudness; compare it against the loudness ladder above.
- **crest**: peak-to-RMS ratio. Below 6 dB the sound is flat or droning (no transient). Above 20 dB it is mostly a spike with weak body.
- **centroid**: the brightness centre of gravity. UI 1-4 kHz, pickups 1.5-5 kHz, impacts 150-1500 Hz, explosions below 800 Hz, gallops and footsteps 200-1500 Hz.
- **energy bands**: below 80 Hz is weight or rumble. 2-5 kHz above 50% is harsh. Above 16 kHz above 5% means aliasing or hiss.
- **PNG**: the top strip is the amplitude envelope, with white ticks every 100 ms. Below it is the spectrogram: log frequency from 50 Hz at the bottom to 22 kHz at the top, dotted lines at 100 Hz, 1 kHz and 10 kHz, brighter = louder. Things to look for:
  - Sweeps show up as diagonal lines.
  - Noise shows up as vertical smears.
  - A tonal sound shows its harmonics as stacked horizontal lines.

## Delivery

- Keep the defaults: WAV, 16-bit, 44.1 kHz, mono. Every engine imports it, and mono is right for anything positional. Stereo is only for UI and music stingers.
- **Godot**: import the WAV. For loops, set loop mode in the Import dock.
- **Unity**: use the WAV; Unity compresses it on import. Check "Loop" on the AudioSource.
- **Unreal**: import the WAV directly.
- **Web / Phaser / Howler**: convert with `ffmpeg -i x.wav -c:a libvorbis -q:a 5 x.ogg` and add an `.m4a` fallback for Safari. Never use MP3 for loops (the encoder adds a gap).
- Trigger variants round-robin. Optionally add ±1 semitone of random pitch at runtime on top.
