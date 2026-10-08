"""Every page renders for every role, before and after a run (headless). Navigation only offers what a role may use."""
import os
import sys
import pytest
from conftest import DATA

pytest.importorskip('streamlit'); pytest.importorskip('rasterio')
sys.path.insert(0, str(DATA.parent/'tests')); sys.path.insert(0, str(DATA.parent/'app'))
from streamlit.testing.v1 import AppTest
APP = str(DATA.parent/'app'/'streamlit_app.py')
PAGES = ['overview', 'portfolio', 'submissions', 'notifications', 'results', 'map', 'property', 'assumptions', 'evidence', 'honesty', 'method',
         'history', 'account', 'admin', 'admin_teams', 'admin_security', 'admin_settings', 'admin_review', 'admin_audit']
ROLES = ['owner', 'admin', 'head_uw', 'underwriter', 'analyst', 'reviewer', 'viewer', 'auditor']

@pytest.fixture(scope='module')
def store(tmp_path_factory):
    path = tmp_path_factory.mktemp('ui_pages')
    saved = {k: os.environ.get(k) for k in ('FLOODCAT_STORE_DIR', 'FLOODCAT_DATABASE_URL')}
    os.environ['FLOODCAT_STORE_DIR'] = str(path)
    os.environ['FLOODCAT_DATABASE_URL'] = f'sqlite:///{path}/platform.db'   # wins over any .env value
    from ui import state
    state.platform.clear()
    yield path
    for k, v in saved.items():
        if v is None: os.environ.pop(k, None)
        else: os.environ[k] = v
    state.platform.clear()

def app(token):
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state['_test_session_token'] = token
    at.run()
    return at

def visit(at, page):
    try:
        at.switch_page(f'views/{page}.py')
    except ValueError:
        return None                                   # not in this role's navigation
    at.run()
    return [e.value for e in at.exception]

@pytest.mark.parametrize('role', ROLES)
def test_every_visible_page_renders(store, role):
    from ui_helpers import make_session
    token = make_session(store, roles=(role,), org_name=f'Org {role}', email=f'{role}@test.re')
    at = app(token)
    assert not at.exception, at.exception[0].value
    seen = []
    for page in PAGES:
        errors = visit(at, page)
        if errors is None: continue
        seen.append(page)
        assert not errors, f'{role} on {page}: {errors[0][:400]}'
    if role in ('owner', 'admin'): assert {'admin', 'admin_security', 'admin_audit'} <= set(seen)
    if role in ('viewer', 'auditor', 'reviewer'): assert 'portfolio' not in seen and 'admin' not in seen
    if role == 'auditor': assert 'admin_audit' in seen

def test_pages_with_a_run_loaded(store):
    from ui_helpers import make_session
    token = make_session(store, roles=('head_uw',), org_name='Run Re', email='head@run.re')
    at = app(token)
    at.switch_page('views/portfolio.py'); at.run()
    next(b for b in at.button if b.label == 'Run the sample portfolio').click(); at.run()
    assert not at.exception and 'result' in at.session_state
    for page in PAGES:
        errors = visit(at, page)
        if errors is not None: assert not errors, f'{page}: {errors[0][:400]}'

def test_signed_out_sees_public_pages_only(store):
    at = AppTest.from_file(APP, default_timeout=60); at.run()
    assert not at.exception
    with pytest.raises(ValueError): at.switch_page('views/overview.py')
    for page in ('landing', 'solutions', 'signin', 'method'):
        at.switch_page(f'views/{page}.py'); at.run()
        assert not at.exception, page

def test_admin_and_workflow_actions_through_pages(store):
    from ui_helpers import make_session
    from floodcat.platform.email import recent
    from floodcat.platform.service import Platform
    token = make_session(store, roles=('owner', 'head_uw', 'analyst'), org_name='Flow Re', email='boss@flow.re')
    plat = Platform(f'sqlite:///{store}/platform.db')
    at = app(token)
    # Invite a colleague.
    at.switch_page('views/admin.py'); at.run()
    next(t for t in at.text_input if t.label == 'Work e-mail').input('colleague@flow.re')
    next(b for b in at.button if b.label == 'Send invitation').click(); at.run()
    assert not at.exception and any('Invitation sent' in s.value for s in at.success)
    with plat.tx() as c: assert any(m['kind'] == 'invitation' for m in recent(c, 'colleague@flow.re'))
    # Security change needs a fresh password check (session older than 10 minutes).
    from sqlalchemy import update
    from floodcat.platform.db import sessions
    from floodcat.platform.identity import now, timedelta
    with plat.tx() as c: c.execute(update(sessions).values(reauth_at=now()-timedelta(hours=1)))
    at.switch_page('views/admin_security.py'); at.run()
    next(b for b in at.button if b.label == 'Save policy').click(); at.run()
    assert not at.exception and any('confirm your password' in w.value.lower() for w in at.warning)
    # Submission: create, refer.
    at.switch_page('views/submissions.py'); at.run()
    next(t for t in at.text_input if t.label == 'Name').input('Landmark Plaza')
    next(b for b in at.button if b.label == 'Create').click(); at.run()
    assert not at.exception
    from floodcat.platform.db import submissions
    from sqlalchemy import select
    with plat.tx() as c: assert c.execute(select(submissions.c.name)).scalars().all() == ['Landmark Plaza']
    # Assumption proposal from a sandbox change.
    at.switch_page('views/assumptions.py'); at.run()
    at.slider[0].set_value(2.0)
    next(b for b in at.button if b.label == 'Apply to my sandbox and re-run').click(); at.run()
    next(t for t in at.text_area if t.label.startswith('Why should')).input('Survey of 2026 flood depths')
    next(b for b in at.button if b.label == 'Submit proposal').click(); at.run()
    assert not at.exception and any('Proposal submitted' in s.value for s in at.success)
    # The same person cannot approve their own proposal (separation of duties).
    at.run()
    next(b for b in at.button if b.label == 'Approve and make house view').click(); at.run()
    assert any('Someone other than the proposer' in e.value for e in at.error)

def test_briefing_from_overview(store, monkeypatch):
    from ui_helpers import make_session
    token = make_session(store, roles=('underwriter',), org_name='Brief Re', email='uw@brief.re')
    at = app(token)
    at.switch_page('views/portfolio.py'); at.run()
    next(b for b in at.button if b.label == 'Run the sample portfolio').click(); at.run()
    at.switch_page('views/overview.py'); at.run()
    assert not at.exception
    # Inject a fake model through the cached runtime used by the page.
    from ui import state
    class FakeLLM:
        model = 'fake-gemini'
        def generate_json(self, system, prompt, schema):
            return {'headline': 'Loss of KES 1.70 bn at 1-in-100', 'sections': [{'heading': 'What the results say', 'paragraphs': ['KES 1.70 bn; also 4,321.']}],
                    'checks': ['Check the depth assumption.']}
    monkeypatch.setattr(state, 'ai_enabled', lambda kind='extraction': True)
    monkeypatch.setattr(state.runtime(), 'llm', lambda: FakeLLM())
    at.run()
    next(b for b in at.button if b.label == 'Draft briefing').click(); at.run()
    assert not at.exception
    assert any('4321' in w.value for w in at.warning)
