"""Marketing-site building blocks for the public pages (landing, solutions, pricing).

Visual blocks are plain HTML with scoped classes; anything clickable is a Streamlit widget so navigation
stays inside the app. Colours use translucent neutrals and the brand blue so both light and dark themes read.
"""
import html
import streamlit as st

BRAND = '#2a78d6'

CSS = f"""
<style>
.x-eyebrow {{ display:inline-block; font-size:.78rem; font-weight:600; letter-spacing:.08em; text-transform:uppercase;
  color:{BRAND}; background:rgba(42,120,214,.10); border:1px solid rgba(42,120,214,.25); border-radius:999px; padding:.25rem .75rem; }}
.x-hero h1 {{ font-size:clamp(2rem, 4.2vw, 3.2rem); line-height:1.08; letter-spacing:-.02em; margin:.8rem 0 .6rem; font-weight:750; }}
.x-hero p.x-lead {{ font-size:1.15rem; line-height:1.55; opacity:.82; max-width:40rem; margin:0; }}
.x-accent {{ color:{BRAND}; }}
.x-section {{ margin-top:3.2rem; }}
.x-section-head {{ text-align:center; max-width:46rem; margin:0 auto 1.6rem; }}
.x-section-head h2 {{ font-size:clamp(1.5rem, 2.6vw, 2.1rem); letter-spacing:-.01em; margin:.5rem 0 .4rem; font-weight:700; }}
.x-section-head p {{ opacity:.78; font-size:1.05rem; margin:0; }}
.x-card {{ border:1px solid rgba(127,127,127,.22); border-radius:14px; padding:1.25rem 1.3rem; height:100%;
  background:rgba(127,127,127,.04); }}
.x-card h4 {{ margin:.55rem 0 .35rem; font-size:1.05rem; font-weight:650; }}
.x-card p, .x-card li {{ opacity:.82; font-size:.95rem; line-height:1.5; margin:0; }}
.x-card ul {{ padding-left:1.1rem; margin:.4rem 0 0; }}
.x-icon {{ width:2.3rem; height:2.3rem; border-radius:10px; display:flex; align-items:center; justify-content:center;
  background:rgba(42,120,214,.12); color:{BRAND}; font-size:1.25rem; }}
.x-stat {{ text-align:center; padding:1rem .5rem; }}
.x-stat b {{ display:block; font-size:clamp(1.4rem, 2.4vw, 1.9rem); letter-spacing:-.01em; }}
.x-stat span {{ opacity:.72; font-size:.9rem; }}
.x-band {{ border-radius:18px; padding:2.2rem 2rem; text-align:center;
  background:linear-gradient(135deg, rgba(42,120,214,.16), rgba(27,175,122,.10)); border:1px solid rgba(42,120,214,.22); }}
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
    st.html(f"<div class='x-hero'><span class='x-eyebrow'>{_e(eyebrow)}</span><h1>{title_html}</h1><p class='x-lead'>{_e(lead)}</p></div>")

def section(eyebrow, title, lead=None):
    st.html(f"<div class='x-section x-section-head'><span class='x-eyebrow'>{_e(eyebrow)}</span><h2>{_e(title)}</h2>"
            + (f'<p>{_e(lead)}</p>' if lead else '') + '</div>')

def card(icon, title, text=None, bullets=()):
    body = f'<p>{_e(text)}</p>' if text else ''
    if bullets: body += '<ul>' + ''.join(f'<li>{_e(b)}</li>' for b in bullets) + '</ul>'
    st.html(f"<div class='x-card'><div class='x-icon'>{icon}</div><h4>{_e(title)}</h4>{body}</div>")

def cards(items, columns=3):
    """items: (icon, title, text, bullets) tuples laid out in a responsive grid."""
    for start in range(0, len(items), columns):
        cols = st.columns(columns, gap='medium')
        for col, item in zip(cols, items[start:start+columns]):
            with col: card(*item)

def stats(items):
    cols = st.columns(len(items))
    for col, (value, label) in zip(cols, items):
        col.html(f"<div class='x-stat'><b>{_e(value)}</b><span>{_e(label)}</span></div>")

def band(title, text):
    st.html(f"<div class='x-section x-band'><h2>{_e(title)}</h2><p>{_e(text)}</p></div>")

def plan(name, price, period, blurb, features, featured=False, tag=None):
    st.html(f"<div class='x-plan{' x-featured' if featured else ''}'>" + (f"<span class='x-tag'>{_e(tag)}</span>" if tag else '')
            + f"<h3>{_e(name)}</h3><p class='x-muted' style='margin:0'>{_e(blurb)}</p>"
            + f"<p class='x-price'>{_e(price)} <small>{_e(period)}</small></p>"
            + '<ul>' + ''.join(f'<li>{_e(f)}</li>' for f in features) + '</ul></div>')

def cta_row(primary='Sign in', key='cta'):
    """Standard call-to-action buttons. Accounts are by invitation, so the primary action is signing in."""
    from . import state
    from .components import link
    row = st.columns([1, 1, 1, 3])
    with row[0]:
        if st.button(primary, type='primary', icon=':material/login:', key=f'{key}_start'): st.switch_page('views/signin.py')
    if state.guest_allowed():
        with row[1]: link('Explore the demo', state.auth_link('/auth/guest'), primary=False)
    from pathlib import Path
    if (Path(__file__).resolve().parents[1]/'views'/'pricing.py').exists():
        with row[2]:
            if st.button('See pricing', icon=':material/sell:', key=f'{key}_pricing'): st.switch_page('views/pricing.py')

def footer():
    st.html("""<div class='x-footer'>
      <b>Xpat</b> · Flood risk intelligence for insurers and reinsurers. Results are indicative, not a price or underwriting advice.</div>""")
    row = st.container(horizontal=True, gap='small')
    for page, label in (('views/landing.py', 'Home'), ('views/solutions.py', 'Solutions'), ('views/pricing.py', 'Pricing'),
                        ('views/method.py', 'How it works'), ('views/signin.py', 'Sign in')):
        try: row.page_link(page, label=label)
        except Exception: pass
