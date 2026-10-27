# Riset: Claude Skill untuk Game SFX (27 Okt 2026)

## 1. Peta kompetitor (bintang dicek via GitHub API)

| Repo | ★ | Pendekatan | Kelemahan |
|---|---|---|---|
| elevenlabs/elevenlabs-mcp | 1.540 | API resmi (TTS + SFX) | Berbayar, butuh API key, bukan khusus game |
| Tuntii/make-sfx | 3 | Procedural TS + MCP, LUFS mastering, demo | **Kompetitor terdekat**, bagus tapi tidak dikenal |
| RomaRogov/jsfxr-mcp-wrapper | 0 | Wrapper jsfxr | Build manual, tanpa demo |
| ronnqvist/sfx-mcp | 2 | Wrapper ElevenLabs | Tidak aktif |
| zavora-ai/mcp-sfxgen | 0 | Stable Audio lokal (Rust, Mac) | Setup berat |
| Freesound MCP (beberapa) | 3–10 | Cari sample | Tidak generate |

Tool procedural yang disukai banyak orang: bfxr (1k★), ZzFX (807★, 38k npm/bulan), rFXGen (517★), jsfxr (460★).
**Belum ada port sfxr/ZzFX di PyPI yang dirawat.**

Pola skill yang meledak (ui-ux-pro-max 141k★, visual-explainer 10.6k★, remotion skills 5.8k★):
output yang bisa *dilihat/didengar* + install satu baris (plugin marketplace) + tanpa API key.

**Pelajaran dari make-sfx:** idenya saja tidak cukup untuk dapat bintang. Yang menentukan adalah demo yang bisa didengar, distribusi (masuk awesome list atau marketplace), dan kualitas suara.

## 2. Teknologi

**Inti (gratis, offline):**
- Synth: Python **stdlib saja** (`wave`, `math`, `random`) cukup untuk SFX di bawah 2 detik. numpy opsional untuk kecepatan.
- Analisis: peak, DC, klik di ujung, durasi, crest factor, spectral centroid. LUFS lewat pyloudnorm (opsional).
- Persepsi: **spektrogram PNG** yang bisa dibaca Claude (bisa ditulis pakai stdlib `zlib`).

**Upgrade opsional (untuk suara realistis):**
| Opsi | Lisensi komersial game | Catatan |
|---|---|---|
| ElevenLabs SFX API `POST /v1/sound-generation` | Ya (paket berbayar) | 0.5–30 detik, ada `loop`, kualitas terbaik |
| Stable Audio Open 1.0 | Ya jika revenue < $1M/tahun | Lokal, GPU ~8–12 GB [belum diverifikasi] |
| AudioGen, MMAudio, TangoFlux, Sony Woosh | **Tidak** (non-komersial) | Hindari untuk game komersial |
| Freesound API | Filter `license:"Creative Commons 0"` | Download file asli butuh OAuth2; 60 req/menit |
| CLAP / Gemini audio | – | "Juri" semantik otomatis (fase 2) |

**Ekspor ke engine:** master WAV 16-bit 44.1/48 kHz. Mono untuk SFX di dunia game, stereo untuk UI. OGG untuk web/Godot. **Jangan pakai MP3 untuk loop** (ada gap).

## 3. Kenapa SFX buatan AI jelek, dan perbaikannya (aturan wajib engine)

| Masalah | Perbaikan |
|---|---|
| Klik | Attack ≥ 1–5 ms, release fade ≥ 5–20 ms, sampel terakhir = 0 |
| DC offset | Kurangi mean, atau HPF 20–40 Hz |
| Aliasing (kasar) | Oscillator PolyBLEP atau oversampling 8×, LPF 8–12 kHz |
| Tipis | Detune 2 osc ±5–15 cent, tambah noise/sub, saturasi tanh ringan |
| Statis | Selalu ada pitch sweep: turun untuk hit/laser/hurt, naik untuk jump/power-up |
| Clipping | Turunkan tiap layer 3–6 dB, soft-clip, normalize ke −1 dBTP |
| Terlalu panjang | UI/pickup 50–300 ms, potong tail di −60 dB |
| Mendem (mud) | HPF 150–300 Hz untuk UI/pickup |

**Model layering:** transient (0–30 ms, noise/klik, HPF > 1–2 kHz) + body (30–200 ms, tonal 100–1000 Hz) + tail (200 ms–2 s) + sweetener. Tiap layer menempati jalur frekuensinya sendiri.

## 4. Resep (dari source code sfxr dan praktik praktisi)

| SFX | Resep |
|---|---|
| Coin | Square 50%, dua nada naik sekwart/kwint (988→1319 Hz), 40 ms + 150–250 ms |
| Jump | Square, pitch 150→600 Hz, 100–250 ms |
| Hit/hurt | Transient noise + square 400→100 Hz, 100–200 ms |
| Explosion | Noise dengan LPF menyapu 3 kHz→200 Hz + sub 40–60 Hz, 0.8–2 s |
| Laser | Saw/square, 1500→300 Hz eksponensial, 100–250 ms |
| Power-up | Arpeggio/sweep naik 200→1200 Hz, 300–800 ms |
| UI click | 5–30 ms, 1–4 kHz, tanpa tail |
| UI hover | Sine 2–3 kHz, 20–40 ms, −6 dB dari click |
| UI confirm / error | Dua nada naik (terts mayor) / dua nada turun atau buzz 150–250 Hz |
| Whoosh/swing | Noise band-pass dengan center 300→2000→500 Hz, puncak di 40–60%, 150–500 ms |
| Footstep | Transient tumit + jari kaki 20–60 ms kemudian, noise LPF, 80–200 ms |
| Magic | Grain sine 2–8 kHz (10–30 ms, 20–50/detik) + reverb, 0.5–1.5 s |
| Death | Sweep 600→60 Hz + vibrato, 0.6–1.5 s |
| Level-up | Arpeggio C-E-G-C, 80–120 ms/nada, nada akhir 300–500 ms |
| **Derap kuda** | 3–4 ketukan per langkah, 1.5–2.5 langkah/detik, ritme "da-da-DUM". Tiap ketukan: klik 2 ms + thump noise LPF 150–400 Hz, 40–80 ms. Acak ±3 dB / ±10 ms |

**Delivery:** 3–5 variasi round-robin, pitch ±1–2 semitone, volume ±1–3 dB. Peak −1 dBTP. SFX menonjol sekitar −12 s/d −18 LUFS, UI 6–10 dB lebih pelan. Leading silence < 5 ms.

## 5. "SFX doctor": cek objektif tanpa mendengar
Peak ≤ −1 dBFS · sampel ujung ≈ 0 · |DC| < 0.001 · durasi sesuai kategori · LUFS ±3 LU dari target · centroid sesuai kategori (UI 1–4 kHz, ledakan < 1 kHz) · energi 2–5 kHz < 40% · ada pitch slope untuk jump/laser/hit · crest factor 6–20 dB · mono benar-benar mono.

## 6. Desain yang diusulkan

```
game-sfx/                     (Claude Code plugin + skill)
  SKILL.md                    workflow: klasifikasi → resep → generate → doctor → spektrogram → iterasi → variasi → ekspor
  recipes.md                  tabel di atas, dalam bentuk patch JSON siap pakai
  scripts/sfx.py              synth berlapis (JSON patch → WAV), tanpa dependency
  scripts/doctor.py           cek objektif + spektrogram PNG
  examples/                   pack demo (WAV + video MP4 untuk README)
```

Pembeda dibanding kompetitor:
1. **Zero dependency** (Python stdlib), offline, tanpa API key
2. **Pengetahuan sound design ikut tertanam** (bukan sekadar wrapper)
3. **Feedback loop**: doctor + spektrogram, supaya Claude bisa "mendengar"
4. Output **siap game**: pack variasi, loudness konsisten, penamaan sesuai engine
5. Halaman demo dengan perbandingan "sebelum (naif) vs sesudah (skill)"

**Batas jujur:** procedural cocok untuk gaya retro/stylized/UI. Untuk suara realistis, tambahkan backend opsional ElevenLabs/Stable Audio (fase 2).

**Rencana launch:** README dengan video A/B, demo di GitHub Pages, entri plugin marketplace, PR ke awesome-claude-skills, posting di r/gamedev dan r/ClaudeAI.
