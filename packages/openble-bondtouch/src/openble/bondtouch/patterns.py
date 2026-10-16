"""Touch patterns: ``[press, gap, press, …, press]`` in milliseconds.

That is the form the app and the Bond cloud use, rounded to 50 ms with a
minimum of 50 ms. V1, V2 and V4 send and receive it. V3 (Bond More) sends a
timeline of 50 ms samples instead, and the Mini always plays MINI_PATTERN.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

STEP_MS = 50
MIN_MS = 50
MINI_PATTERN = (500, 250, 500, 250, 500)

# V3 samples (TouchMessageContent): one byte per period, 0xFF not touching.
SAMPLE_TOUCH = 0x35  # what the app sends for touching
SAMPLE_IDLE = 0xFF
MAX_SAMPLES = 200  # 10 s at 50 ms


def round_ms(value: int) -> int:
    """Round to the nearest 50 ms, at least 50 ms."""
    if value < 0:
        raise ValueError(f"a duration is not negative, got {value}")
    return max(MIN_MS, (value + STEP_MS // 2) // STEP_MS * STEP_MS)


def normalise(pattern: Iterable[int]) -> tuple[int, ...]:
    """Check the press/gap shape and round every duration as the app does."""
    out = tuple(round_ms(int(value)) for value in pattern)
    if len(out) % 2 == 0:
        raise ValueError("a pattern starts and ends with a press, so its length is odd")
    return out


def steps(pattern: Sequence[int]) -> list[tuple[int, int]]:
    """``(press, gap after it)`` pairs. The last press has a gap of 0."""
    if len(pattern) % 2 == 0:
        raise ValueError("a pattern starts and ends with a press, so its length is odd")
    presses = list(pattern[0::2])
    gaps = [*pattern[1::2], 0]
    return list(zip(presses, gaps, strict=True))


def to_samples(pattern: Sequence[int]) -> bytes:
    """The V3 sample form: SAMPLE_TOUCH for presses, SAMPLE_IDLE for gaps.

    Up to 10 s each sample is 50 ms. A longer pattern is squeezed into
    MAX_SAMPLES by lengthening the sample period, as the app does; the app's
    exact rounding is not recorded, so this keeps run boundaries to the
    nearest sample and every run at least one sample long.
    """
    pattern = normalise(pattern)
    total = sum(pattern)
    period = max(STEP_MS, total / MAX_SAMPLES)
    out = bytearray()
    elapsed = 0
    for index, duration in enumerate(pattern):
        elapsed += duration
        count = max(1, round(elapsed / period) - len(out))
        out += bytes((SAMPLE_IDLE if index % 2 else SAMPLE_TOUCH,)) * count
    return bytes(out[:MAX_SAMPLES])


def from_samples(samples: bytes, period_ms: int = STEP_MS) -> tuple[int, ...]:
    """Runs of touching and idle samples -> ``[press, gap, …]``.

    Leading and trailing idle samples are dropped, as the app does. Any
    sample other than 0xFF counts as touching.
    """
    body = bytes(samples).strip(bytes((SAMPLE_IDLE,)))
    out: list[int] = []
    previous: bool | None = None
    for sample in body:
        touching = sample != SAMPLE_IDLE
        if touching == previous:
            out[-1] += period_ms
        else:
            out.append(period_ms)
        previous = touching
    return tuple(out)
