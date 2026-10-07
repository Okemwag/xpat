"""Drive the real Portfolio page's upload path. AppTest cannot upload files, so st.file_uploader is stubbed."""
import pytest
from conftest import DATA

pytest.importorskip('streamlit')
pytest.importorskip('rasterio')
from streamlit.testing.v1 import AppTest

APP_DIR = DATA.parent/'app'

def page(store_dir, csv_bytes, name='upload.csv'):
    def script(app_dir, store_dir, csv_bytes, name):
        import os, sys
        os.environ['FLOODCAT_STORE_DIR'] = store_dir
        if app_dir not in sys.path: sys.path.insert(0, app_dir)
        import streamlit as st
        class Uploaded:
            def __init__(self, data, name): self._data, self.name = data, name
            def getvalue(self): return self._data
        st.file_uploader = lambda *a, **k: Uploaded(csv_bytes, name)
        st.switch_page = lambda *a, **k: st.session_state.__setitem__('switched_to', a[0])
        st.session_state.setdefault('user', {'username': 'tester', 'display_name': 'Tester', 'organisation': '', 'role': 'analyst'})
        exec(compile(open(f'{app_dir}/views/portfolio.py').read(), 'portfolio.py', 'exec'), {'__name__': '__main__'})
    return AppTest.from_function(script, args=(str(APP_DIR), str(store_dir), csv_bytes, name), default_timeout=60)

def run_button(at):
    return next(b for b in at.button if b.label == 'Run analysis')

def test_clean_upload_runs(tmp_path):
    at = page(tmp_path, (DATA/'exposure_nairobi_synthetic.csv').read_bytes()); at.run()
    assert not at.exception
    assert run_button(at).disabled is False
    run_button(at).click(); at.run()
    assert not at.exception and at.session_state['result']['modelled_count'] == 600

def test_upload_with_errors_needs_explicit_partial(tmp_path):
    csv = (b'loc_id,lat,lon,housing_class,tiv_kes,synthetic,source\n'
           b'A,-1.28,36.82,concrete,1m,True,x\nB,36.82,-1.28,concrete,1m,True,x\n')
    at = page(tmp_path, csv); at.run()
    assert not at.exception and run_button(at).disabled is True
    next(c for c in at.checkbox if c.label.startswith('Run on the valid records only')).check(); at.run()
    run_button(at).click(); at.run()
    assert not at.exception and at.session_state['result']['modelled_count'] == 1

def test_upload_without_synthetic_columns_needs_declaration(tmp_path):
    csv = b'id,latitude,longitude,construction,tiv\nA,-1.2576,36.8962,semi-permanent,"3,300,000"\n'
    at = page(tmp_path, csv); at.run()
    assert not at.exception and not [b for b in at.button if b.label == 'Run analysis']
    assert any('synthetic' in e.value for e in at.error)
    next(c for c in at.checkbox if c.label.startswith('I confirm this portfolio is synthetic')).check(); at.run()
    assert run_button(at).disabled is False
    run_button(at).click(); at.run()
    assert not at.exception and at.session_state['result']['modelled_count'] == 1

def test_unreadable_file_shows_error_not_crash(tmp_path):
    at = page(tmp_path, b'\x00\x01\x02 not a csv'); at.run()
    assert not at.exception
