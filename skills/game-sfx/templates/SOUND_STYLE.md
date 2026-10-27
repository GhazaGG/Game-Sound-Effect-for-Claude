# Sound style: <game name>

Read this before making or changing any sound for this project. Every new sound should feel like it belongs to the same family as these.

## Identity
- **Game:** <one line: genre, what the player does>
- **Style:** <retro | cartoon | grounded> (<why: e.g. "chunky cartoon sprites, bright palette">)
- **Mood:** <e.g. cheerful, cozy, frantic, eerie>
- **Engine:** <Godot 4 / Unity / Phaser / ...> (audio folder: `<path>`)

## Palette
- **Sources:** <e.g. sine + FM bells, wood partials, spring vibrato; no square buzz>
- **Materials in the world:** <e.g. hooves on dirt road, wooden crates, leather bags, coins>
- **Music key / tempo:** <e.g. C major, 120 BPM; jingles use C-E-G>. Leave as "unknown" if there is no music yet.
- **Space:** <e.g. small room reverb mix 0.1, decay 0.3-0.5; outdoor = drier>

## Loudness ladder (master.lufs)
| Tier | LUFS | Sounds |
|---|---|---|
| Hero | -14 | <big hits, level complete> |
| Gameplay | -16 | <pickups, jump> |
| Ambient / loops | -19 | <gallop, footsteps> |
| UI | -21 | <click, hover> |

## Sound list
| Name | Event in code | Status |
|---|---|---|
| <coin> | <Player.gd: collect()> | <done / todo / replace> |

## Decisions
<!-- one line per change and why, newest last -->
- <date> <sound>: <what changed and why>
