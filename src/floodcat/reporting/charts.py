"""Static PNG charts for the PDF and Word reports (Pillow only). Same palette as the interface: blue = baseline model,
grey band = simulation range, orange = AI-adjusted; log return-period axis as on the Loss curve page."""

import io
import math
from decimal import Decimal
from PIL import Image, ImageDraw, ImageFont

BLUE, ORANGE, GREY, INK, MUTED, GRID = (
    (42, 120, 214),
    (235, 104, 52),
    (200, 203, 208),
    (40, 40, 38),
    (107, 107, 102),
    (232, 232, 228),
)
CLASS_COLOURS = [(42, 120, 214), (235, 104, 52), (27, 175, 122), (237, 161, 0)]
SCALE = 2


def _font(size):
    try:
        return ImageFont.load_default(size=size * SCALE)
    except TypeError:
        return ImageFont.load_default()  # Pillow < 10.1: fixed bitmap font


def _bn(value):
    return float(Decimal(str(value))) / 1e9


def _png(img):
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def _nice_max(value):
    if value <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(value))
    return next(
        m * exp for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if m * exp >= value
    )


def ep_chart(report, ylt=None, width=800, height=380):
    """Loss (KES bn) against return period on a log axis: simulated curve and band when available, scenario diamonds always."""
    W, H = width * SCALE, height * SCALE
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    left, right, top, bottom = 64 * SCALE, 40 * SCALE, 34 * SCALE, 52 * SCALE
    base = report["runs"]["baseline"]
    points = [(p["return_period_years"], _bn(p["loss_kes"])) for p in base["ep_curve"]]
    sim = ylt["baseline"]["gross"] if ylt else None
    xmin, xmax = (
        (1, 10000)
        if sim
        else (min(r for r, _ in points) / 2, max(r for r, _ in points) * 2)
    )
    top_value = max(
        [l for _, l in points]
        + ([_bn(p["band_high_kes"]) for p in sim["curve"]] if sim else [])
    )
    ymax = _nice_max(top_value * 1.05)
    X = lambda rp: (
        left
        + (math.log10(rp) - math.log10(xmin))
        / (math.log10(xmax) - math.log10(xmin))
        * (W - left - right)
    )
    Y = lambda v: H - bottom - v / ymax * (H - top - bottom)
    f, small = _font(12), _font(11)
    for i in range(6):
        v = ymax * i / 5
        y = Y(v)
        d.line([(left, y), (W - right, y)], fill=GRID, width=SCALE)
        d.text(
            (left - 8 * SCALE, y),
            f"{v:,.2f}" if ymax < 10 else f"{v:,.0f}",
            fill=MUTED,
            font=small,
            anchor="rm",
        )
    ticks = [
        t
        for t in (1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 10000)
        if xmin <= t <= xmax
    ]
    for t in ticks:
        d.line(
            [(X(t), H - bottom), (X(t), H - bottom + 4 * SCALE)],
            fill=MUTED,
            width=SCALE,
        )
        d.text(
            (X(t), H - bottom + 8 * SCALE),
            f"1-in-{t:,}",
            fill=MUTED,
            font=small,
            anchor="ma",
        )
    d.line([(left, H - bottom), (W - right, H - bottom)], fill=MUTED, width=SCALE)
    d.text(
        (left + (W - left - right) / 2, H - 14 * SCALE),
        "Return period (log scale)",
        fill=INK,
        font=f,
        anchor="mm",
    )
    d.text(
        (left - 8 * SCALE, 10 * SCALE), "Loss (KES bn)", fill=INK, font=f, anchor="la"
    )
    if sim:
        pts = [
            (
                p["return_period_years"],
                _bn(p["band_low_kes"]),
                _bn(p["band_high_kes"]),
                _bn(p["loss_kes"]),
            )
            for p in sim["curve"]
            if xmin <= p["return_period_years"] <= xmax
        ]
        band = [(X(r), Y(h)) for r, _, h, _ in pts] + [
            (X(r), Y(l)) for r, l, _, _ in reversed(pts)
        ]
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(overlay).polygon(band, fill=GREY + (130,))
        img.paste(overlay, (0, 0), overlay)
        d = ImageDraw.Draw(img)
        d.line(
            [(X(r), Y(v)) for r, _, _, v in pts],
            fill=BLUE,
            width=3 * SCALE,
            joint="curve",
        )
        edge = X(sim["rarest_modelled_return_period"])
        for y in range(int(top), int(H - bottom), 10 * SCALE):
            d.line([(edge, y), (edge, y + 5 * SCALE)], fill=MUTED, width=SCALE)
        d.text(
            (edge + 5 * SCALE, top + 4 * SCALE),
            "beyond: damage uncertainty only",
            fill=MUTED,
            font=small,
            anchor="la",
        )
    else:
        d.line([(X(r), Y(v)) for r, v in points], fill=BLUE, width=3 * SCALE)
    r_ = 6 * SCALE
    for rp, v in points:
        x, y = X(rp), Y(v)
        d.polygon(
            [(x, y - r_), (x + r_, y), (x, y + r_), (x - r_, y)],
            fill=BLUE,
            outline="white",
        )
    return _png(img)


def construction_chart(report, width=800, height=200):
    """Horizontal bars: share of the rarest-scenario loss by construction class, labelled with the share and amount."""
    from ..core.constants import CLASSES, TIERS
    from .document import CLASS_LABEL, kes

    items = report["runs"]["baseline"]["breakdowns"][TIERS[-1]]["construction"]
    W, H = width * SCALE, (44 * len(items) + 20) * SCALE
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f = _font(12)
    label_w = 170 * SCALE
    bar_h = 26 * SCALE
    gap = 18 * SCALE
    top_share = max((i["loss_share_pct"] for i in items), default=0) or 1
    for n, i in enumerate(items):
        y = 15 * SCALE + n * (bar_h + gap)
        d.text(
            (label_w - 10 * SCALE, y + bar_h / 2),
            CLASS_LABEL.get(i["id"], i["id"]),
            fill=INK,
            font=f,
            anchor="rm",
        )
        length = (W - label_w - 240 * SCALE) * i["loss_share_pct"] / top_share
        d.rounded_rectangle(
            [label_w, y, label_w + max(length, SCALE), y + bar_h],
            radius=4 * SCALE,
            fill=CLASS_COLOURS[CLASSES.index(i["id"]) % 4 if i["id"] in CLASSES else 0],
        )
        d.text(
            (label_w + length + 8 * SCALE, y + bar_h / 2),
            f"{i['loss_share_pct']:.0f}% · {kes(i['loss_kes'])}",
            fill=MUTED,
            font=f,
            anchor="lm",
        )
    return _png(img)


def render(kind, report, ylt=None):
    return ep_chart(report, ylt) if kind == "ep" else construction_chart(report)
