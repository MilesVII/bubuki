> [!NOTE]
> Original mod made by [유즈키 유카리_結月ゆかり](https://live.warthunder.com/post/1111762/en/).
>
> Huge thanks for the amazing mod <3

> [!WARNING]
> The whole conversion is performed by Claude without human supervision
>
> The mod is tested in game by me
>
> Check releases to download the final archive

# bubuki — crew voice mod, ported to the current War Thunder build

- `old/` is the original mod (FMOD Studio banks built July 2024) by [유즈키 유카리_結月ゆかり](https://live.warthunder.com/post/1111762/en/).
- `new/` is the port, built on 2026‑10‑13 against the game files currently in `sound/`.
- `tools/` rebuilds `new/` from `old/` + the current game banks (see "Re-running after a game update").

## What the old mod was, and why it stopped working

The 2024 mod replaced three things in `sound/mod`:

* `crew_dialogs_ground.bank` + `.assets.bank` — the ground‑crew *event* bank. The modder took
  Gaijin's sound‑mod project and swapped the programmer instruments of 300 of its 304 events for
  their own 49 embedded stereo clips (kill/hit/damage/spot/start/stop/reload/… lines).
* `Radio Voice/crew_dialogs_common.bank` + `.assets.bank` — same trick for the radio/common bank
  (420 of 460 events, 40 clips).
* `masterbank.bank`, `masterbank.strings.bank`, `masterbank.assets.bank` — a 2024 master bank.
* Per‑language `_crew_dialogs_*_<lang>.assets.bank` files that were unused leftovers of the build
  (the old `ru` one is just the stock 2024 Russian table).

The current game has 819 ground events and 744 common events (vs 304 / 460 in 2024), new buses in the
master bank, and a different set of voice keys. Dropping the 2024 event/master banks over the current
ones removes events and buses the game now expects, which is why the old mod is incompatible.

## How the port works

In the current build every crew line is a *programmer instrument* whose name is the key, e.g.
`high/gunner/voice_message_gunner_shot_v1`, resolved at runtime in the per‑language audio‑table banks
`_crew_dialogs_ground_<lang>.assets.bank`. So the port does **not** ship any event or master bank.
It only ships rebuilt per‑language asset banks, derived from the current game's own files:

* key list, key order and FMOD's key lookup table are kept byte‑for‑byte identical;
* each slot's audio is replaced by the old mod's clip when the old mod covered that event
  (old and new events share GUIDs, so the match is exact), otherwise by a 0.1 s silent clip
  (muted, as requested);
* when an old event had several clips, the keys of the new event cycle through them, with the start
  clip rotated per event so single‑key events do not all land on the same clip.

Audio stays FMOD‑Vorbis; the clips are copied bit‑exact from the old banks, and the silent clip uses a
Vorbis setup header FMOD already knows (same CRC as the game's own 44.1 kHz mono samples).

## Coverage

| | ground | radio ("Radio Voice") |
|---|---|---|
| current events | 819 | 744 |
| covered by old mod clips | 300 | 420 |
| events the old mod left stock → **muted** | 4 | 40 |
| events added since 2024 → **muted** | 512 | 279 |
| voice keys → old mod clip | 535 of 1191 | 1066 of 1681 |

Ground lines left stock by the old mod (now muted): driver `tracks_repaired`, driver
`transmission_damaged`, gunner `power_damaged`, gunner `power_repaired`. Radio lines left stock:
the `base_*`/`pilot_*` mission announcements (base captured/destroyed, zone capture, reinforcements…).
Everything newer than 2024 is silent: artillery‑crew lines, chief air/artillery danger, commander
load/move/night‑vision/stabilizer/shovel orders, target range/clock callouts, gunner/loader status
lines, etc. Full lists: `new/report/keys_*.tsv` (key → clip or `(muted)`), `new/report/events_*.tsv`,
`new/report/slots_<kind>_<lang>.tsv` (what every slot of every language bank got) and
`new/report/summary.json`.

All 35 ground languages (`ar … zh`, including the `sm_*` voice packs) and all 17 radio languages are
built, 1.1 GB in total.

## Install

1. Back up and empty `sound/mod/` — it currently holds an unrelated crew_dialogs_common mod from
   May 2023.
2. Copy every `*.bank` from `new/` into `sound/mod/`. Optionally also copy `new/Radio Voice/*.bank`
   into `sound/mod/` for the radio part.
3. In `config.blk`, inside `sound{ … }`, set `enable_mod:b=yes` (it is currently `no`).
4. Do **not** copy anything from `old/` (in particular not the master bank or the two event banks).

## Caveats

* Not tested in‑game. The banks were validated structurally (parsers re‑read them, FMOD's lookup
  table is untouched, the container/sound headers are consistent) and the audio was verified by
  decoding ported clips and silent slots with ffmpeg (ported clips decode sample‑identical to the
  old mod's clips).
* A muted line is a 0.1 s silent message, so the game's voice queue still "plays" it.
* Keys the game builds in code instead of naming in the bank (altitude/bearing callouts, the
  `mission_complete_victory_*_v1` set) have no event to map from and are muted.
* The `nw` (and partly `de`) language tables have an irregular layout; there the slot→key match
  fell back to matching by line name. Other languages matched exactly.

## Re-running after a game update

Requires Python 3 (ffmpeg only if you want to regenerate `tools/silence/`). From the game folder:

```bash
python bubuki/tools/port.py --silence bubuki/tools/silence
```

It re‑derives everything from `sound/crew_dialogs_*.bank`, `sound/_crew_dialogs_*_*.assets.bank`
and `bubuki/old/`, and rewrites `bubuki/new/` with fresh reports. Modules: `fev.py` (RIFF/FEV +
FSB5 reader), `events.py` (event → instrument resolver), `fsbwrite.py` (FSB5 + container writer,
byte‑identical on round trip), `silence.py` (silent FMOD‑Vorbis clip generator), `port.py` (pipeline).
