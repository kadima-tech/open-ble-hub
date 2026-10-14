"""Small server-rendered SVG charts. No JavaScript, colours come from CSS tokens."""

from __future__ import annotations

from datetime import datetime


def _scale(points: list[tuple[datetime, float]], start: datetime, end: datetime, width: float, height: float, pad: float, min_span: float):
    values = [value for _, value in points]
    lo, hi = min(values), max(values)
    if hi - lo < min_span:
        middle = (hi + lo) / 2
        lo, hi = middle - min_span / 2, middle + min_span / 2
    span_t = max((end - start).total_seconds(), 1.0)

    def x(when: datetime) -> float:
        return round(min(max((when - start).total_seconds() / span_t, 0.0), 1.0) * width, 1)

    def y(value: float) -> float:
        return round(pad + (hi - value) / (hi - lo) * (height - 2 * pad), 1)

    return x, y, lo, hi


def line_chart(points: list[tuple[datetime, float]], *, start: datetime, end: datetime, tone: str, label: str, min_span: float = 1.0) -> str:
    """Trend line with a soft area, three grid lines and a dot on the latest value.

    ``points`` are oldest first. Returns the SVG and the y-axis bounds as HTML.
    """
    width, height, pad = 600.0, 200.0, 18.0
    if len(points) < 2:
        return ""
    x, y, lo, hi = _scale(points, start, end, width, height, pad, min_span)
    coords = " ".join(f"{x(when)},{y(value)}" for when, value in points)
    first_x, last_x = x(points[0][0]), x(points[-1][0])
    last_y = y(points[-1][1])
    grid = "".join(
        f'<line x1="0" x2="{width:g}" y1="{level}" y2="{level}" class="chart-grid" vector-effect="non-scaling-stroke"/>'
        for level in (pad, height / 2, height - pad)
    )
    return f"""<div class="chart">
<svg viewBox="0 0 {width:g} {height:g}" role="img" aria-label="{label}" class="tone-{tone}">
{grid}
<polygon points="{first_x},{height:g} {coords} {last_x},{height:g}" class="chart-area"/>
<polyline points="{coords}" class="chart-line" vector-effect="non-scaling-stroke"/>
<circle cx="{last_x}" cy="{last_y}" r="7" class="chart-dot"/>
</svg>
<div class="chart-y" aria-hidden="true"><span>{hi:.1f}</span><span>{lo:.1f}</span></div>
</div>"""


def sparkline(points: list[tuple[datetime, float]], *, start: datetime, end: datetime, tone: str, min_span: float = 1.0) -> str:
    if len(points) < 2:
        return ""
    width, height, pad = 200.0, 48.0, 6.0
    x, y, _, _ = _scale(points, start, end, width, height, pad, min_span)
    coords = " ".join(f"{x(when)},{y(value)}" for when, value in points)
    return (f'<svg viewBox="0 0 {width:g} {height:g}" class="spark tone-{tone}" aria-hidden="true" preserveAspectRatio="none">'
            f'<polyline points="{coords}" class="chart-line" vector-effect="non-scaling-stroke"/></svg>')
