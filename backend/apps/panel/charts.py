"""Server-rendered SVG column chart (single series, no JS). Hover: native <title> tooltip + CSS highlight."""
import math
from decimal import Decimal

from django.utils.html import escape
from django.utils.safestring import mark_safe

H = 220
PAD_L, PAD_R, PAD_T, PAD_B = 48, 8, 16, 26


def compact(v: float) -> str:
    v = float(v)
    for div, suf in ((1e9, " млрд"), (1e6, " млн"), (1e3, "K")):
        if abs(v) >= div:
            s = f"{v / div:.1f}".rstrip("0").rstrip(".")
            return f"{s}{suf}"
    return f"{v:.0f}"


def nice_ticks(vmax: float, n: int = 4) -> list[float]:
    if vmax <= 0:
        return [0, 1]
    raw = vmax / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    top = step * math.ceil(vmax / step)
    return [step * i for i in range(int(round(top / step)) + 1)]


def column_chart(points: list[tuple[str, str, Decimal | int]], title: str, fmt=compact, width: int = 760) -> str:
    """points: [(axis_label, tooltip_label, value)]. Axis labels are thinned to fit."""
    if not points:
        return ""
    values = [float(v or 0) for _, _, v in points]
    ticks = nice_ticks(max(values))
    top = ticks[-1] or 1
    W = width  # noqa: N806 — viewBox width; match the container so text is not scaled up
    plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    slot = plot_w / len(points)
    bw = max(2.0, min(24.0, slot - 2))
    y = lambda v: PAD_T + plot_h * (1 - v / top)  # noqa: E731

    parts = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)}">']
    for t in ticks:
        parts.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        parts.append(f'<text class="tick" x="{PAD_L - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{compact(t)}</text>')
    every = max(1, math.ceil(len(points) / 12))
    imax = values.index(max(values))
    for i, ((axis, tip, _), v) in enumerate(zip(points, values, strict=True)):
        cx = PAD_L + slot * i + slot / 2
        x0 = cx - bw / 2
        parts.append(f'<g class="col"><title>{escape(tip)}: {escape(fmt(v))}</title>')
        parts.append(f'<rect class="hit" x="{PAD_L + slot * i:.1f}" y="{PAD_T}" width="{slot:.1f}" height="{plot_h}"/>')
        if v > 0:
            yt, yb = y(v), y(0)
            r = min(4.0, bw / 2, yb - yt)
            parts.append(
                f'<path class="bar" d="M{x0:.1f},{yb:.1f} V{yt + r:.1f} Q{x0:.1f},{yt:.1f} {x0 + r:.1f},{yt:.1f} '
                f'H{x0 + bw - r:.1f} Q{x0 + bw:.1f},{yt:.1f} {x0 + bw:.1f},{yt + r:.1f} V{yb:.1f} Z"/>'
            )
            if i == imax:
                parts.append(f'<text class="val" x="{cx:.1f}" y="{yt - 4:.1f}" text-anchor="middle">{escape(compact(v))}</text>')
        parts.append("</g>")
        if i % every == 0:
            parts.append(f'<text class="tick" x="{cx:.1f}" y="{H - 8}" text-anchor="middle">{escape(axis)}</text>')
    parts.append(f'<line class="axis" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    parts.append("</svg>")
    return mark_safe("".join(parts))
