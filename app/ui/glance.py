"""Glanceable building blocks: answer-first pages with big numbers, formula cards, assumption chips and a details switch.

Every page should open with one plain sentence and a few big numbers, show the formula behind them in large bold italics,
list only the assumptions that matter there as chips, and keep tables and secondary charts behind "Show details".
"""

import html
import streamlit as st

CSS = """<style>
.g-answer{font-size:clamp(1.15rem,2.2vw,1.55rem);line-height:1.45;font-weight:500;margin:.2rem 0 1rem;color:var(--text-color,#1d2733)}
.g-answer b{color:#1f6fd1;font-weight:800;white-space:nowrap}
.g-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:.75rem;margin:.2rem 0 1rem}
.g-tile{border-radius:14px;padding:.85rem 1rem;background:#f4f7fb;border:1px solid #e3e9f1;position:relative;overflow:hidden}
.g-tile .g-ic{font-size:1.25rem;line-height:1}
.g-tile .g-lab{font-size:.78rem;letter-spacing:.02em;text-transform:uppercase;color:#5b6672;font-weight:600;margin-top:.25rem}
.g-tile .g-val{font-size:clamp(1.35rem,2.4vw,1.9rem);font-weight:800;line-height:1.15;margin:.15rem 0;overflow-wrap:anywhere;color:#1d2733}
.g-tile .g-sub{font-size:.8rem;color:#5b6672}
.g-tile.blue{background:#eaf2fd;border-color:#cfe0fa}.g-tile.blue .g-val{color:#1f6fd1}
.g-tile.orange{background:#fdf0e8;border-color:#f6d6c2}.g-tile.orange .g-val{color:#c4511f}
.g-tile.green{background:#e8f7f0;border-color:#c5ebd8}.g-tile.green .g-val{color:#13865b}
.g-tile.red{background:#fdecec;border-color:#f6caca}.g-tile.red .g-val{color:#b42318}
.g-formula{border-left:5px solid #1f6fd1;background:linear-gradient(90deg,#eef4fc,#ffffff);border-radius:10px;padding:.8rem 1.1rem;margin:.4rem 0 1rem}
.g-formula .g-f{font-size:clamp(1.15rem,2.3vw,1.6rem);font-weight:800;font-style:italic;color:#14365f;line-height:1.35}
.g-formula .g-n{font-size:clamp(1rem,1.8vw,1.25rem);font-weight:700;font-style:italic;color:#1f6fd1;margin-top:.2rem}
.g-formula .g-note{font-size:.8rem;color:#5b6672;margin-top:.3rem}
.g-verdict{border-radius:18px;padding:1.1rem 1.3rem;margin:.2rem 0 1rem;color:#fff}
.g-verdict .g-vt{font-size:clamp(1.6rem,3.4vw,2.5rem);font-weight:900;line-height:1.1}
.g-verdict .g-vs{font-size:clamp(1rem,1.8vw,1.2rem);opacity:.95;margin-top:.3rem}
.g-verdict.accept{background:linear-gradient(135deg,#13865b,#1baf7a)}
.g-verdict.share{background:linear-gradient(135deg,#c77700,#eda100)}
.g-verdict.decline{background:linear-gradient(135deg,#a1281f,#d6453a)}
.g-verdict.none{background:linear-gradient(135deg,#5b6672,#8a95a1)}
.g-gauge{margin:.35rem 0 .8rem}
.g-gauge .g-gl{display:flex;justify-content:space-between;font-size:.88rem;font-weight:600;color:#1d2733}
.g-gauge .g-track{height:12px;border-radius:8px;background:#e6ebf1;position:relative;margin-top:.3rem;overflow:hidden}
.g-gauge .g-fill{height:100%;border-radius:8px}
.g-gauge .g-mark{position:absolute;top:-3px;width:3px;height:18px;background:#1d2733;border-radius:2px}
.g-gauge .g-gs{font-size:.78rem;color:#5b6672;margin-top:.2rem}
.g-steps{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:.2rem 0 1rem}
.g-step{border-radius:999px;padding:.35rem .8rem;background:#f1f4f8;font-weight:600;font-size:.88rem;color:#3d4955}
.g-step.on{background:#1f6fd1;color:#fff}
.g-step b{font-size:1.05rem;margin-left:.35rem}
.g-arrow{color:#9aa4ae}
.g-choice{border-radius:16px;border:2px solid #e3e9f1;padding:1rem;height:100%}
.g-choice .g-ci{font-size:2rem}.g-choice h4{margin:.3rem 0 .2rem;font-size:1.1rem}.g-choice p{color:#5b6672;font-size:.9rem;margin:0}
</style>"""


def _e(text):
    return html.escape(str(text))


def style():
    """Inject the styles once per page run (cheap; Streamlit dedupes identical HTML)."""
    st.html(CSS)


def answer(text_html):
    """The page's one-sentence answer. `text_html` may contain <b>…</b> around the key numbers; nothing else is trusted."""
    safe = _e(text_html).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    st.html(f"<div class='g-answer'>{safe}</div>")


def tiles(items):
    """Big numbers that wrap instead of truncating. items: (icon, label, value, sub, tone) with tone blue|orange|green|red|''."""
    cells = []
    for icon, label, value, sub, tone in [i for i in items if i]:
        cells.append(f"<div class='g-tile {tone}'><div class='g-ic'>{_e(icon)}</div><div class='g-lab'>{_e(label)}</div>"
                     f"<div class='g-val'>{_e(value)}</div>" + (f"<div class='g-sub'>{_e(sub)}</div>" if sub else "") + "</div>")
    st.html(f"<div class='g-tiles'>{''.join(cells)}</div>")


def formula(expression, numbers=None, note=None):
    """A formula in large bold italics, optionally with the real numbers plugged in underneath."""
    st.html(f"<div class='g-formula'><div class='g-f'>{_e(expression)}</div>"
            + (f"<div class='g-n'>{_e(numbers)}</div>" if numbers else "")
            + (f"<div class='g-note'>{_e(note)}</div>" if note else "") + "</div>")


def chips(items, key):
    """Only the assumptions that matter on this page, as small chips; each opens a one-line explanation."""
    row = st.container(horizontal=True, gap="small")
    for i, (label, why) in enumerate(items):
        with row.popover(f"⚙ {label}", type="tertiary"):
            st.caption("ASSUMPTION")
            st.write(why)
            st.caption("Change it on Assumptions & governance.")


def details(key, label="Show details"):
    """The page's single switch between the glanceable view and the full detail."""
    return st.toggle(label, key=f"details_{key}", help="Tables, definitions and secondary charts")


def verdict(kind, title, subtitle):
    """A big coloured verdict: accept (green), share (amber), decline (red) or none (grey)."""
    st.html(f"<div class='g-verdict {kind}'><div class='g-vt'>{_e(title)}</div><div class='g-vs'>{_e(subtitle)}</div></div>")


def gauge(label, value_text, fraction, mark=None, colour="#1f6fd1", sub=None):
    """A horizontal gauge filled to `fraction` (0–1) with an optional marker (0–1), e.g. a rule's threshold."""
    f = max(0.0, min(1.0, float(fraction)))
    marker = f"<div class='g-mark' style='left:calc({max(0.0, min(1.0, mark)) * 100:.1f}% - 1px)'></div>" if mark is not None else ""
    st.html(f"<div class='g-gauge'><div class='g-gl'><span>{_e(label)}</span><span>{_e(value_text)}</span></div>"
            f"<div class='g-track'><div class='g-fill' style='width:{f * 100:.1f}%;background:{colour}'></div>{marker}</div>"
            + (f"<div class='g-gs'>{_e(sub)}</div>" if sub else "") + "</div>")


def steps(items, active=None):
    """A step strip, e.g. a pipeline: items are (label, count_or_None)."""
    parts = []
    for i, (label, count) in enumerate(items):
        if i:
            parts.append("<span class='g-arrow'>→</span>")
        parts.append(f"<span class='g-step{' on' if label == active else ''}'>{_e(label)}" + (f"<b>{_e(count)}</b>" if count is not None else "") + "</span>")
    st.html(f"<div class='g-steps'>{''.join(parts)}</div>")


def choice(icon, title, text):
    st.html(f"<div class='g-choice'><div class='g-ci'>{_e(icon)}</div><h4>{_e(title)}</h4><p>{_e(text)}</p></div>")
