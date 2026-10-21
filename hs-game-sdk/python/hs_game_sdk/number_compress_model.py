"""When the game's Steam number shortener ends the process (hand-written, stdlib only).

The mechanism is written down, in our own words and with every claim labelled
static reading, measured, our code or not established, in
`docs/models/number-compress-spec.md`. `tests/test_number_compress_model.py`
holds the checks.

The game shortens a number for display through `num_compressSteam`, which
hands it to the export `SteamCompressNumber` of `PAS_Steam_GMS_x64.dll`. That
export writes its text into a fixed buffer of 8 bytes, and a range check on
that buffer ends the process (exit code `0xC0000409`) for any number it cannot
fit: NaN, a positive number of 1e14 or more, a negative number of -1e6 or less
(static reading). For every other number this module gives the text the export
writes and whether the text's terminator also fits inside the 8 bytes.

This module models the game only. ForgePact's cap (`numguard`, ForgePact#230)
is that mod's own code and lives in the test as an input transform.

Not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns;
import it as `from hs_game_sdk import number_compress_model`.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

#: The smallest positive value the export fails on (static reading): from here
#: up the band quotient has 7 or more digits.
POSITIVE_LIMIT = 1e14
#: The largest negative value the export fails on (static reading): from here
#: down the truncated magnitude has 7 or more digits after the minus sign.
NEGATIVE_LIMIT = -1e6

#: The export's text buffer, terminator included (static reading).
BUFFER_BYTES = 8

#: Positive values below this are written as the truncated whole number.
WHOLE_NUMBER_BELOW = 10_000.0

#: The three shortening bands, lowest first: (lower bound, divisor, suffix).
#: A value at or above the lower bound and below the next band's lower bound
#: takes that band; NaN takes the last (static reading).
BANDS: Tuple[Tuple[float, float, str], ...] = (
    (10_000.0, 100.0, "K"),
    (1_000_000.0, 100_000.0, "M"),
    (1_000_000_000.0, 100_000_000.0, "B"),
)


def fails(x: float) -> bool:
    """True when `SteamCompressNumber` ends the process for `x`.

    NaN; `x >= POSITIVE_LIMIT` (`+inf` included); `x <= NEGATIVE_LIMIT`
    (`-inf` included). False for every other value.
    """
    x = float(x)
    if math.isnan(x):
        return True
    return x >= POSITIVE_LIMIT or x <= NEGATIVE_LIMIT


def band(x: float) -> Optional[Tuple[int, str]]:
    """The band quotient `q` and its suffix for a positive `x` of 10,000 or
    more that does not fail, or None for a value no band shortens.

    `q` is computed as the export does: the value divided by the band's
    divisor, then truncated toward zero.
    """
    x = float(x)
    if fails(x) or not x >= BANDS[0][0]:
        return None
    lower, divisor, suffix = BANDS[0]
    for b_lower, b_divisor, b_suffix in BANDS:
        if x >= b_lower:
            lower, divisor, suffix = b_lower, b_divisor, b_suffix
    return math.trunc(x / divisor), suffix


def text(x: float) -> Optional[str]:
    """The text the export writes for `x`, or None when `x` fails (the model
    never returns a text for a value that ends the process).

    Zero (and `-0.0`) is `"0"`; a negative value is `-` and its truncated
    magnitude, never shortened; a positive value below 10,000 is its truncated
    whole number; from 10,000 up, `q` is shown as tenths: the digits of
    `q // 10`, then `,` and `q % 10` unless that digit is 0, then the suffix.
    """
    x = float(x)
    if fails(x):
        return None
    if x == 0.0:
        return "0"
    if x < 0.0:
        return "-" + str(math.trunc(-x))
    if x < WHOLE_NUMBER_BELOW:
        return str(math.trunc(x))
    q, suffix = band(x)
    whole, tenth = divmod(q, 10)
    return str(whole) + ("," + str(tenth) if tenth else "") + suffix


def fits_with_terminator(x: float) -> bool:
    """For an `x` that does not fail, true when its text and the terminator
    both fit in the 8-byte buffer (the text is at most 7 characters).

    False for a value that fails, and false for a positive value in the `B`
    band whose `q` has 6 digits and a nonzero last digit (1e13 <= x < 1e14,
    `q % 10 != 0`): its 8-character text leaves the terminator past the buffer.
    """
    shown = text(x)
    return shown is not None and len(shown) <= BUFFER_BYTES - 1
