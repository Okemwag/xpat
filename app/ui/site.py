"""Marketing-site building blocks for the public pages (landing, solutions, pricing).

Visual blocks are plain HTML with scoped classes; anything clickable is a Streamlit widget so navigation
stays inside the app. Colours use translucent neutrals and the brand blue so both light and dark themes read.
"""

import html
import streamlit as st

BRAND = "#2a78d6"

CSS = f"""
<style>
.x-eyebrow {{ display:block; font-size:.85rem; font-weight:600; color:{BRAND}; }}
.x-hero h1 {{ font-size:clamp(1.8rem, 3.4vw, 2.5rem); line-height:1.15; margin:.4rem 0 .6rem; font-weight:700; }}
.x-hero p.x-lead {{ font-size:1.08rem; line-height:1.55; opacity:.85; max-width:38rem; margin:0; }}
.x-accent {{ color:inherit; }}
.x-section {{ margin-top:2.8rem; }}
.x-section-head {{ max-width:46rem; margin:0 0 1.2rem; }}
.x-section-head h2 {{ font-size:clamp(1.3rem, 2.2vw, 1.7rem); margin:.3rem 0 .3rem; font-weight:650; }}
.x-section-head p {{ opacity:.78; font-size:1.05rem; margin:0; }}
.x-card {{ border:1px solid rgba(127,127,127,.25); border-radius:8px; padding:1.1rem 1.2rem; height:100%; }}
.x-card h4 {{ margin:0 0 .35rem; font-size:1.02rem; font-weight:650; }}
.x-card p, .x-card li {{ opacity:.82; font-size:.95rem; line-height:1.5; margin:0; }}
.x-card ul {{ padding-left:1.1rem; margin:.4rem 0 0; }}
.x-icon {{ font-weight:700; color:{BRAND}; font-size:.95rem; margin-bottom:.35rem; }}
.x-stat {{ text-align:center; padding:1rem .5rem; }}
.x-stat b {{ display:block; font-size:clamp(1.4rem, 2.4vw, 1.9rem); letter-spacing:-.01em; }}
.x-stat span {{ opacity:.72; font-size:.9rem; }}
.x-band {{ border-radius:8px; padding:1.6rem 1.6rem; border:1px solid rgba(127,127,127,.25); border-left:4px solid {BRAND}; }}
.x-band h2 {{ margin:0 0 .4rem; font-size:clamp(1.4rem, 2.4vw, 1.9rem); }}
.x-band p {{ margin:0; opacity:.82; }}
.x-plan {{ border:1px solid rgba(127,127,127,.25); border-radius:16px; padding:1.5rem 1.4rem; height:100%; }}
.x-plan.x-featured {{ border:2px solid {BRAND}; box-shadow:0 8px 28px rgba(42,120,214,.15); }}
.x-plan .x-tag {{ font-size:.75rem; font-weight:700; color:#fff; background:{BRAND}; border-radius:999px; padding:.15rem .6rem; }}
.x-plan h3 {{ margin:.6rem 0 .2rem; font-size:1.25rem; }}
.x-price {{ font-size:2.1rem; font-weight:750; letter-spacing:-.02em; margin:.5rem 0 0; }}
.x-price small {{ font-size:.9rem; font-weight:500; opacity:.7; }}
.x-plan ul {{ list-style:none; padding:0; margin:1rem 0 0; }}
.x-plan li {{ padding:.28rem 0; font-size:.94rem; opacity:.88; }}
.x-plan li::before {{ content:'✓'; color:{BRAND}; font-weight:700; margin-right:.5rem; }}
.x-footer {{ margin-top:3.5rem; padding-top:1.4rem; border-top:1px solid rgba(127,127,127,.22); font-size:.85rem; opacity:.75; }}
.x-footer b {{ opacity:1; }}
.x-muted {{ opacity:.7; font-size:.85rem; }}
</style>
"""


def css():
    st.html(CSS)


def _e(text):
    return html.escape(str(text))


def hero(eyebrow, title_html, lead):
    """title_html may contain <span class='x-accent'>…</span>; everything else is escaped."""
    st.html(
        f"<div class='x-hero'><span class='x-eyebrow'>{_e(eyebrow)}</span><h1>{title_html}</h1><p class='x-lead'>{_e(lead)}</p></div>"
    )


def section(eyebrow, title, lead=None):
    st.html(
        f"<div class='x-section x-section-head'><span class='x-eyebrow'>{_e(eyebrow)}</span><h2>{_e(title)}</h2>"
        + (f"<p>{_e(lead)}</p>" if lead else "")
        + "</div>"
    )


def card(icon, title, text=None, bullets=()):
    body = f"<p>{_e(text)}</p>" if text else ""
    if bullets:
        body += "<ul>" + "".join(f"<li>{_e(b)}</li>" for b in bullets) + "</ul>"
    st.html(
        f"<div class='x-card'>{f'<div class=x-icon>{_e(icon)}</div>' if icon else ''}<h4>{_e(title)}</h4>{body}</div>"
    )


def cards(items, columns=3):
    """items: (icon, title, text, bullets) tuples laid out in a responsive grid."""
    for start in range(0, len(items), columns):
        cols = st.columns(columns, gap="medium")
        for col, item in zip(cols, items[start : start + columns]):
            with col:
                card(*item)


def stats(items):
    cols = st.columns(len(items))
    for col, (value, label) in zip(cols, items):
        col.html(
            f"<div class='x-stat'><b>{_e(value)}</b><span>{_e(label)}</span></div>"
        )


def band(title, text):
    st.html(
        f"<div class='x-section x-band'><h2>{_e(title)}</h2><p>{_e(text)}</p></div>"
    )


def plan(name, price, period, blurb, features, featured=False, tag=None):
    st.html(
        f"<div class='x-plan{' x-featured' if featured else ''}'>"
        + (f"<span class='x-tag'>{_e(tag)}</span>" if tag else "")
        + f"<h3>{_e(name)}</h3><p class='x-muted' style='margin:0'>{_e(blurb)}</p>"
        + f"<p class='x-price'>{_e(price)} <small>{_e(period)}</small></p>"
        + "<ul>"
        + "".join(f"<li>{_e(f)}</li>" for f in features)
        + "</ul></div>"
    )


def cta_row(primary="Sign in", key="cta"):
    """Standard call-to-action buttons: sign in or create an account (both on the sign-in page)."""
    from . import state
    from .components import link

    row = st.columns([1, 1, 1, 3])
    with row[0]:
        if st.button(
            primary, type="primary", icon=":material/login:", key=f"{key}_start"
        ):
            st.switch_page("views/signin.py")
    if state.guest_allowed():
        with row[1]:
            link("Explore the demo", state.auth_link("/auth/guest"), primary=False)
    from pathlib import Path

    if (Path(__file__).resolve().parents[1] / "views" / "pricing.py").exists():
        with row[2]:
            if st.button("See pricing", icon=":material/sell:", key=f"{key}_pricing"):
                st.switch_page("views/pricing.py")


def footer():
    st.html("""<div class='x-footer'>
      <b>Xpat</b> · Flood risk intelligence for insurers and reinsurers. Results are indicative, not a price or underwriting advice.</div>""")
    row = st.container(horizontal=True, gap="small")
    for page, label in (
        ("views/landing.py", "Home"),
        ("views/solutions.py", "Solutions"),
        ("views/pricing.py", "Pricing"),
        ("views/method.py", "How it works"),
        ("views/signin.py", "Sign in"),
    ):
        try:
            row.page_link(page, label=label)
        except Exception:
            pass
