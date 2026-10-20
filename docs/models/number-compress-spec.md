# When the game's Steam number shortener ends the process: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/number_compress_model.py`](../../hs-game-sdk/python/hs_game_sdk/number_compress_model.py)
(`number_compress_model`), tested by
[`tests/test_number_compress_model.py`](../../tests/test_number_compress_model.py).
It was written for ForgePact#230 (hub #539): with ForgePact's Modifiers raised
to their slider maxima (Total Damage x11, Critical Strike Damage x11, Critical
Strike Chance x6), hitting a training dummy ended the game with exit code
`0xC0000409` and a crash report that named nothing. The game shortens a number
for display through the script `num_compressSteam`
(`gml_Script_num_compressSteam`), which hands it to the export
`SteamCompressNumber` of the Steam extension `PAS_Steam_GMS_x64.dll`. That
export writes its text into a buffer of 8 bytes and ends the process for any
number it cannot fit. The spec answers two questions: which numbers end the
process, and, for the rest, what text comes back and whether its terminator
fits inside the 8 bytes.

Every claim carries one of four labels, and a source:

- **Static reading**: read from the compiled extension locally and written here
  in our own words. No listing, disassembly or byte of its code is quoted or
  transcribed, and no offset inside it is given (`AGENTS.md` § "Legal").
  Unless a claim says otherwise, each claim below is a static reading of
  `PAS_Steam_GMS_x64.dll` as installed with the game on 2026-10-20 (127,488
  bytes, file date 2026-09-18, sha256
  `c789ee5e5850e0d68c42a6d0b84876509eaea4f2ffab1ea9c35e71709c47b88f`),
  export `SteamCompressNumber`, made on 2026-10-20.
- **Measured**: observed in a running game: the positive limit's lower edge
  (bracketed between 9.9999e13, which passed, and below 1e15: the game ended
  after a traced 1.025e14, the first value of its decade, so the fatal value
  was at least 1.025e14 and below 1e15), the crash's dump and the cap's text, in Live 2; see
  § Measurements.
- **Our code**: what ForgePact does. The model leaves it out, and the test
  expresses it as an input transform.
- **Not established**: left out of the model, or carried as an open question.

The game facts behind this spec are in
[`docs/RUNTIME_DATA_MODELS.md`](../RUNTIME_DATA_MODELS.md) § 8.7 (the game's
number formatters) and § 15 (calls that crash or hang the game).

## Static reading

- **What goes in and what comes out.** `SteamCompressNumber` takes one number
  (a double) and returns a pointer to a static text buffer of 8 bytes. It
  clears the whole buffer before writing into it. `num_compressSteam` takes one
  argument and returns that text to the game, through the runtime's
  extension-call helper.
- **Zero.** A value equal to zero returns a constant text `"0"`. (`-0.0`
  compares equal to zero, so it takes the same path; our inference from the
  compare, not read separately.)
- **Negative values are never shortened.** For a value below zero the export
  takes its magnitude, converts it to a 32-bit integer by truncation toward
  zero, and writes that whole number after a minus sign: `-1234.7` shows as
  `-1234`. A negative value above `-1` therefore shows as `-0` by the same
  rule.
- **Positive values below 10,000** are written as the whole number, truncated:
  `9999.9` shows as `9999`.
- **Three bands from 10,000 up**, each dividing the value and truncating the
  quotient to a 32-bit integer `q`:

  | value `x` | `q` | suffix | `q` ranges over |
  |---|---|---|---|
  | 10,000 ≤ x < 1,000,000 | trunc(x / 100) | `K` | 100 to 9,999 |
  | 1,000,000 ≤ x < 1,000,000,000 | trunc(x / 100,000) | `M` | 10 to 9,999 |
  | x ≥ 1,000,000,000, and NaN | trunc(x / 100,000,000) | `B` | 10 up |

  NaN compares false against every threshold, so it is not zero, not negative
  and not below any band's upper bound: it lands in the `B` band.
- **The text of a band.** `q` is shown as tenths: the digits of `q // 10`, then
  a comma and the single digit `q % 10`, then the suffix. The comma and the
  digit are dropped when that digit is 0. So 12,345 (`q` = 123) shows as
  `12,3K`, 10,050 (`q` = 100) as `10K`, 1,000,000,000 (`q` = 10) as `1B`, and
  99,999,000,000,000 (`q` = 999,990) as `99999B`. The text is `digits(q) + 2`
  characters long when the decimal digit is nonzero and `digits(q)` characters
  when it is zero; the terminator is the next byte, left at zero by the clear.
- **Every write into the buffer is range-checked.** The extension was built
  with the compiler's range checks on its fixed buffer. A failed check calls
  the C runtime's range-check failure, which raises a fast fail with code 8
  (`FAST_FAIL_RANGE_CHECK_FAILURE`). The process ends at once with exit code
  `0xC0000409`; no exception is dispatched inside it, so no in-process handler
  (ForgePact's crash trap included) sees it.
- **Exactly when it fails.** The check fails, and the process ends, when:
  - `x` is NaN (the 32-bit conversion of NaN gives the integer minimum, ten
    digits after its sign);
  - `x` is positive and `q` has 7 or more digits, whatever its last digit: that
    is `x ≥ 1e14` (`q` ≥ 1,000,000). Past about 2.1e17 the quotient no longer
    fits a 32-bit integer and the conversion gives the integer minimum, which
    fails the same way; `+inf` does too;
  - `x` is negative and the truncated magnitude has 7 or more digits, that is
    `x ≤ -1e6` (seven digits plus the sign). `-inf` converts to the integer
    minimum and fails the same way.

  Which single write trips the check for a 7-digit `q` is not set out here; the
  reading is that every 7-digit `q` reaches a failing write.
- **The limits are exact in doubles.** The largest double below 1e14 divided by
  1e8 still rounds below 1,000,000, so for positive `x` "`q` has 7 or more
  digits" and "`x ≥ 1e14`" pick the same values. (Our arithmetic on the reading,
  checked in Python.) For negatives the truncation itself decides: `-999,999.9`
  truncates to 999,999 and passes; `-1,000,000` fails.
- **Texts that fill all 8 bytes.** A band text with a 6-digit `q` and a nonzero
  decimal digit is 8 characters long (`99999,9B`). That is every value from
  1e13 up to just under 1e14 whose `q % 10` is not 0. It does not fail, but its
  terminator falls outside the buffer. A negative text never fills the buffer
  without failing: `-999999` is 7 characters and its terminator is the eighth
  byte. Every other text that does not fail ends inside the buffer.
- To re-read it: `dumpbin /nologo /disasm <dll>` from the MSVC Build Tools
  (`...\bin\Hostx64\x64\dumpbin.exe`), with its output kept outside every
  repository.

How a number reaches the shortener is a static reading of `Hero_Siege.exe`,
recorded in `RUNTIME_DATA_MODELS.md` § 8.7. The script file's binder stores
`num_compressSteam` and `num_compressGML` as method values, and no code calls
either script or reads either of those globals directly. Every caller goes
through one other global, `num_compress`: the enemy health bars, the HUD, the
floating combat text (`Combat_Text_obj`), the DPS meter (`DPS_Meter_obj`) and a
few menus. Which script that global holds on the Steam PC build is not
established by the reading; Live 2 measured it holding `num_compressSteam`
(§ Measurements). Three display options decide whether a number gets there. The
floating text formats its number through `num_compress` only while
`combatTextCompress` is on, and an enemy hit draws a damage number at all only
while `showDamage` is on. The DPS meter calls `num_compress` while
`dpsMeterCompress` is on and the full-digit `RealFormat` otherwise. The player
sets all three in the game's options, and they are saved in the `[settings]`
section of `shop.ini`.

## Measurements

Live 1 of the workorder `forgepact-230-damage-crash` (capture
`forgepact-230-damage-crash-live-1`, 2026-10-20) ran with `showDamage` and
`dpsMeterCompress` off in the player's settings. It measured no call into
`num_compressSteam` or `SteamCompressNumber` and no crash up to about 1.6e18
per hit, so nothing reached the shortener and that session tests nothing in
this spec: for the shortener its result is "not observed", not a refutation.

Live 2 of the same workorder (capture `forgepact-230-damage-crash-live-2`,
2026-10-20, the research build, Sorak at the Act 1 town's training dummies, the
reporter's ForgePact settings) ran with `showDamage` and `combatTextCompress`
on, and in its second launch `dpsMeterCompress` too. Its values are in
[`hs-game-sdk/curated/number_compress_measurements.json`](../../hs-game-sdk/curated/number_compress_measurements.json),
which the model's test (`MeasurementTests`) reads. Against this spec:

- **The route** (measured). Floating damage numbers were drawn and shortened,
  and in one 20 s window debugger logging breakpoints counted 748 calls into
  `num_compressSteam` and 748 into `SteamCompressNumber`, one for one; none into
  `num_compressGML`, beside a control that kept logging.
- **The positive limit's lower edge** (measured). With ForgePact's cap forced
  off and Total Damage ramped from x11 to x1e6, the values traced into
  `num_compressSteam` (one line per new decade) rose to 15,038,794,170,000,
  which passed, and last traced 102,480,421,310,000 (the first value of its
  decade; later values in the decade write no line), after which the game
  ended. In the second launch the cap handed 99,999,000,000,000 itself to the
  shortener 29,990 times, which drew `99999B` with the game alive: a measured
  pass at 9.9999e13. So the limit lies in (9.9999e13, 1e15) as measured, which
  holds `POSITIVE_LIMIT` = 1e14; that it is exactly 1e14 is the static
  reading. The model passes both passing values and fails the last traced
  one. Only the band's lower edge is measured: no value of 1e15 or more ran
  uncapped.
- **How it ends** (measured). Exit code `0xC0000409`; the dump reads
  `code=0xc0000409 subcode=8 raised-in=PAS_Steam_GMS_x64`, with
  `SteamCompressNumber` on the stack: the range-check fast fail this spec reads.
- **The texts** (measured). The numbers drawn read like the model's bands:
  `970,4K`, `1,2M`, `5M`, `394,6M`, `1,2B`, `1296,2B`, a comma before the one
  decimal digit and none when it is 0.
- **The cap** (measured, our code). With the cap automatic and Total Damage
  ramped to x1e12, values up to about 2.2e20 reached the hook, 29,990 were
  capped to `kNumGuardLargestSafe` (99,999,000,000,000), the first at
  100,300,112,243,000, every floating number read `99999B`, and the game lived.
- **Not exercised:** NaN, the negative band (`NEGATIVE_LIMIT`), the positive
  band above its lower edge and the 32-bit overflow past about 2.1e17 without
  the cap, and the 8-character texts'
  missing terminator. The DPS meter read `0` with `dpsMeterCompress` on, so
  whether its total reaches the shortener is not observed.

## Our code

ForgePact's `numguard` (ForgePact#230,
`ForgePact/plugin/include/ForgePact/NumberGuard.hpp`) detours
`num_compressSteam` and, while armed, replaces a number the shortener would fail
on before the game's own call goes ahead. The damage dealt, the DPS sums and
enemy health are not changed; only the argument of that one call is.

| C++ constant / model name | value | meaning |
|---|---|---|
| `kNumGuardPositiveLimit` / `POSITIVE_LIMIT` | `1e14` | the smallest positive value that fails (the game's) |
| `kNumGuardNegativeLimit` / `NEGATIVE_LIMIT` | `-1e6` | the largest negative value that fails (the game's) |
| `kNumGuardLargestSafe` (test transform) | `99999000000000.0` | `q` = 999,990, shown `99999B`, terminator inside the buffer |
| `kNumGuardSmallestSafe` (test transform) | `-999999.0` | shown `-999999`, 7 characters and the terminator |

- A value `≥ POSITIVE_LIMIT`, or `+inf`, becomes `kNumGuardLargestSafe`.
- A value `≤ NEGATIVE_LIMIT`, or `-inf`, becomes `kNumGuardSmallestSafe`.
- NaN becomes `0.0` (shown `"0"`).
- Every other value passes through unchanged, bit for bit, including the
  8-character texts between 1e13 and 1e14: what the game shows for a number it
  can format is left alone.
- The guard arms only when a Modifiers lever (`stat`, `statadd`,
  `skillslider`) is set off vanilla; with every lever at vanilla nothing is
  hooked.

The two limits are the game's and live in the model; the two safe values are
ForgePact's choice and live in the test's transform. The test's
`LeverParityTests` reads the header and asserts the four constants equal the
model's limits and the transform's values.

## Not established

- **What the game reads for an 8-character text.** Its terminator falls past
  the buffer, so what follows depends on the byte after it. The model reports
  such a value as passing but not fitting with its terminator.
- **Which formatter shows a hit's floating number and which the DPS meter
  uses** (`CombatText`, `DPS_Meter_obj`). Live 2 measured the floating
  numbers reaching `num_compressSteam` with `combatTextCompress` on; the DPS
  meter's compressed route was not observed.
- **Whether anything else reaches `SteamCompressNumber`** than
  `num_compressSteam`.
- **Whether a vanilla character can put 1e14 on screen.** The shortener fails
  for such a number with or without ForgePact; ForgePact's Modifiers make it
  reachable. A DPS sum crosses 1e14 well before a single hit does; not
  measured.
- **The other formatters** (`num_compressGML`, `RealFormat`, the runner's
  `string_format`) at huge values. They have no fixed buffer of their own in
  the reading, and nothing here models them.

## The model

A pure function of one double
([`number_compress_model.py`](../../hs-game-sdk/python/hs_game_sdk/number_compress_model.py)),
stdlib only:

- `POSITIVE_LIMIT = 1e14`, `NEGATIVE_LIMIT = -1e6`: the boundaries above.
- `fails(x)`: true when the export ends the process for `x`. NaN; `x ≥
  POSITIVE_LIMIT` (`+inf` included); `x ≤ NEGATIVE_LIMIT` (`-inf` included).
  False for everything else.
- `fits_with_terminator(x)`: for an `x` that does not fail, true when its text
  and the terminator both fit in 8 bytes, that is the text is at most 7
  characters. False for a value that fails, and false for a positive `x` in the
  `B` band whose `q` has 6 digits and a nonzero last digit (1e13 ≤ x < 1e14,
  `q % 10 ≠ 0`).
- The band rules it needs: zero → `"0"`; negative → `-` and the truncated
  magnitude; below 10,000 → the truncated whole number; the `K`, `M` and `B`
  bands with `q` computed as the game does (divide, then truncate), and the
  decimal digit dropped when it is 0. The model may expose the text itself for
  a value that does not fail; it never returns one for a value that does.

The baseline values the test pins, all from the reading above: 0, 1, 9,999,
10,000, 123,456, 999,999, 1e9, 99,999,000,000,000 and 99,999,999,999,999.98
pass; 1e14, 1e15, 1e18, 1e300, `+inf`, NaN, -1e6, -1e12 and `-inf` fail.
99,999,999,999,999.98 passes without fitting its terminator; the others that
pass fit.

## What the model cannot catch

It is arithmetic on one number. It cannot tell whether the detour attaches
(every caller reaches `num_compressSteam` through the global `num_compress`,
whose value is a method, so only an inline detour at the function sees it, and
only while `combatTextCompress` or `dpsMeterCompress` routes a number there;
`RUNTIME_DATA_MODELS.md` § 8.7), which kind of value the game passes (a real, an int32
or an int64), whether some other route reaches the export, what the game draws
for an unterminated text, or whether the process that ended actually died in
this export. Those are the live session's: the dump's subcode 8 and raising
module `PAS_Steam_GMS_x64` name this crash, and the research build's
`numguard` counters show the cap firing.
