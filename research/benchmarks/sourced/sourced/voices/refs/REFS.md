# Reference clips for Chatterbox voice cloning

Chatterbox clones a voice zero-shot from a short clip. SOURCED uses five
clips, one per voice slot (`world.VOICES`), all cut from **LibriVox**
recordings. The owner of the synthetic life gets one slot to themselves; the
partner and friends share the other four (SPEC section 3.3).

## Licence

LibriVox, <https://librivox.org/pages/public-domain/>, checked 2026-10-28:

> LibriVox records only texts that are in the public domain (in the USA – see
> below for why), and all our recordings are public domain (definitely in the
> USA, and maybe in your country as well, see below). This means anyone can
> use all our recordings however they wish (even to sell them).

The same page adds that the recordings are "public domain in the USA, but not
necessarily in other countries", and asks listeners outside the USA to check
the status of the *work*. Every book below was first published between 1813
and 1883, and its author died before 1900, so the text is in the public
domain in every country we know of. Each archive.org item, in the
`librivoxaudio` collection, also carries a public-domain licence URL in its
metadata (given per clip below).

The clips are cut from the readers' voices only. They are used to give
synthetic, fictional characters a voice; no clip is presented as the reader,
and no reader endorses this benchmark. Every audio file Chatterbox makes from
them carries Resemble AI's Perth watermark, which marks it as synthetic.

## Clips

Cut with ffmpeg from the 64 kbps MP3: mono, 24 kHz, 16-bit PCM, 50 ms fades,
no other processing. Each segment starts and ends in a pause found with
`silencedetect` (noise -38 dB, 0.35 s) and contains no pause longer than
0.35 s. Gender is LibriVox's catalogue name and the recording; accent is our
label, not stated on the reader pages, and is to be confirmed by ear.

| Slot | Reader (LibriVox id) | Book | Segment |
|---|---|---|---|
| `female_a.wav` | Elizabeth Klett (1259), US English | Jane Austen, *Persuasion* (1817), chapter 1 | 87.19–97.62 s (10.4 s) |
| `female_b.wav` | Kara Shallenberg (19), US English | R. L. Stevenson, *Treasure Island* (1883), chapter 1 | 78.69–88.31 s (9.6 s) |
| `male_a.wav` | Mark F. Smith (204), US English | R. L. Stevenson, *Treasure Island* (1883), chapter 1 | 76.89–88.01 s (11.1 s) |
| `male_b.wav` | Stewart Wills (196), US English | Herman Melville, *Moby Dick* (1851), chapters 1-2 | 76.42–87.44 s (11.0 s) |
| `female_gb.wav` | Karen Savage (103), British English | Jane Austen, *Pride and Prejudice* (1813), chapter 1 | 76.20–86.56 s (10.4 s) |

### `female_a.wav`
- LibriVox project: <https://librivox.org/persuasion-by-jane-austen-2/> (Persuasion, version 2, solo)
- File: <https://archive.org/download/persuasion_etk/persuasion_01_austen_64kb.mp3>
- archive.org licence: http://creativecommons.org/licenses/publicdomain/
- Source MP3 SHA-256: `d94488b4064ef1520b18275e6b637e0848dee745f52a9f4bf9dad03146025fa6`
- Clip SHA-256: `83698655c117b1943712cda52d69b82bbc781a2f2fbafd4d0628983333e9bac0`

### `female_b.wav`
- LibriVox project: <https://librivox.org/treasure-island-by-robert-louis-stevenson-5/> (Treasure Island, version 5, solo)
- File: <https://archive.org/download/treasureisland_ks_1510_librivox/treasureisland_01_stevenson_64kb.mp3>
- archive.org licence: http://creativecommons.org/publicdomain/mark/1.0/
- Source MP3 SHA-256: `a8b0b0a4b41e767bbcf424d5aba241e35a364c4df17c5cbdc19a55e6e6db20de`
- Clip SHA-256: `688b0efd976f0030b08a4448a1da3f5c3555186f831e678a7dc5d398c0ee02d6`

### `male_a.wav`
- LibriVox project: <https://librivox.org/treasure-island-version-4-by-robert-louis-stevenson/> (Treasure Island, version 4, solo)
- File: <https://archive.org/download/treasure_island_1307_librivox/treasureisland_01_stevenson_64kb.mp3>
- archive.org licence: http://creativecommons.org/publicdomain/mark/1.0/
- Source MP3 SHA-256: `e197b9cbc973631086895bbb77ae4f151f37b8519644c5084733c2b09fe13425`
- Clip SHA-256: `99ec7aa340553c399285bcaaf4f8a72bf12a26787f81b05a4ce933a559feacf8`

### `male_b.wav`
- LibriVox project: <https://librivox.org/moby-dick-by-herman-melville> (Moby Dick, solo)
- File: <https://archive.org/download/moby_dick_librivox/mobydick_001_002_melville_64kb.mp3>
- archive.org licence: http://creativecommons.org/publicdomain/mark/1.0/
- Source MP3 SHA-256: `5ec76198d81c3b0618342448b3bd688485032c84f4d3acd35d4c20bb8496f7e5`
- Clip SHA-256: `4faf8facd1d960b64df79e68003be748d5413193e0fab5d8a92a90eff9fa0a60`

### `female_gb.wav`
- LibriVox project: <https://librivox.org/pride-and-prejudice-by-jane-austen-2/> (Pride and Prejudice, version 3, solo)
- File: <https://archive.org/download/pride_prejudice_krs_librivox/pride_and_prejudice_01_austen_64kb.mp3>
- archive.org licence: http://creativecommons.org/licenses/publicdomain/
- Source MP3 SHA-256: `194a8e83364f1cbdcecc0237b4331efc2848befc41a86b114a4d11a9180d14c9`
- Clip SHA-256: `8a422687c8a54d9e31b1c71e0cf5f594b04a2a42576f52f2fa6ced198982fa19`

All URLs and statements checked 2026-10-28. The clips have not been
listened to by the person who cut them (no audio playback was available);
listen to each one before a release and replace any that holds a page turn,
a mouth noise or another voice.

## Recutting a clip

```bash
ffmpeg -ss <start> -to <end> -i <source.mp3> -ac 1 -ar 24000 \
  -af "afade=t=in:d=0.05,areverse,afade=t=in:d=0.05,areverse" \
  -map_metadata -1 -fflags +bitexact -flags:a +bitexact -c:a pcm_s16le <slot>.wav
```

Then update the SHA-256 here and in `REFS` in `sourced/tts_worker.py`.

## Listening check

All five clips were listened to and approved by the author on 2026-10-28: clean speech, no music or noise, and the British reader (female_gb) confirmed by ear.
