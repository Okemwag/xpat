"""Session state, shared runtime and formatting for the Streamlit app."""
import os
import secrets
from decimal import Decimal
import streamlit as st
from floodcat.core.errors import ModelError
from floodcat.services.accounts import Accounts
from floodcat.services.runtime import Runtime

@st.cache_resource(show_spinner='Loading hazard maps…')
def runtime():
    return Runtime()

@st.cache_resource
def accounts():
    a = Accounts(runtime().local_store)
    a.ensure_admin()
    return a

def ai_available():
    from floodcat.ai.gemini import available
    return available()

def guest_allowed():
    return os.getenv('FLOODCAT_ALLOW_GUEST', '1') != '0'

# Session -----------------------------------------------------------------
def user():
    return st.session_state.get('user')

def sign_in(record):
    st.session_state.clear()
    st.session_state['user'] = record

def sign_in_guest():
    role = os.getenv('FLOODCAT_GUEST_ROLE', 'reviewer')
    sign_in({'username': f'guest-{secrets.token_hex(3)}', 'display_name': 'Guest', 'organisation': '', 'role': role, 'guest': True})

def sign_out():
    st.session_state.clear()

def can_review():
    u = user()
    return bool(u) and u['role'] in ('reviewer', 'admin')

def is_admin():
    u = user()
    return bool(u) and u['role'] == 'admin'

def result():
    return st.session_state.get('result')

def set_result(report, rows, label, settings=None):
    st.session_state['result'] = report
    st.session_state['rows'] = rows
    st.session_state['run_label'] = label
    st.session_state['run_settings'] = settings or {}
    st.session_state.pop('ai_result', None)

def config():
    """The config the user is working with (base config + their applied overrides)."""
    overrides = st.session_state.get('config_overrides') or {}
    return runtime().config.replace(**overrides) if overrides else runtime().config

def execute(rows, label, *, settings=None, save=True, **options):
    """Run the model and store the result in the session. Returns (report, error)."""
    settings = dict(settings or {})
    if not rows:
        return None, ModelError('no_input', 'This saved run was opened from history and has no input records; load the portfolio again to re-run it')
    try:
        report = runtime().run(rows, config=config(), **settings, **options)
    except ModelError as exc:
        return None, exc
    if save:
        try: runtime().store.save_analysis(report, owner=user()['username'], label=label)
        except Exception: st.toast('Run completed but could not be saved to history', icon='⚠️')
    set_result(report, rows, label, settings)
    return report, None

# Formatting -----------------------------------------------------------------
def kes(value, compact=True):
    v = Decimal(str(value))
    if not compact: return f'KES {v:,.0f}'
    a = abs(v)
    if a >= 10**9: return f'KES {v/10**9:,.2f} bn'
    if a >= 10**6: return f'KES {v/10**6:,.1f} m'
    if a >= 10**3: return f'KES {v/10**3:,.0f} k'
    return f'KES {v:,.0f}'

def pct(value, digits=2):
    return '—' if value is None else f'{value:.{digits}f}%'

def rp_label(years):
    return f'1-in-{years:g}'

def class_label(name):
    return {'informal_iron_sheet': 'Informal (iron sheet)', 'semi_permanent': 'Semi-permanent',
            'permanent_masonry': 'Permanent masonry', 'concrete_rcc': 'Reinforced concrete'}.get(name, name)

def tier_for_rp(cfg, years):
    return next(t for t, rp in cfg.return_periods.items() if rp == years)
