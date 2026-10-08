"""Which AI model serves a request: organisation rules, member preference, client data kept on the server (ai/llm.choose)."""
import pytest
from floodcat.ai.llm import choose, configured
from floodcat.core.errors import ModelError

@pytest.fixture
def both(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key'); monkeypatch.setenv('OLLAMA_MODEL', 'llama3.2:3b'); monkeypatch.delenv('FLOODCAT_AI_PROVIDER', raising=False)

@pytest.fixture
def cloud_only(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key'); monkeypatch.delenv('OLLAMA_MODEL', raising=False); monkeypatch.delenv('FLOODCAT_AI_PROVIDER', raising=False)

def settings(**kw):
    return {'ai_providers': ['gemini', 'ollama'], 'ai_default_provider': None, 'ai_local_for_client_data': False, 'ai_preferences': {}, **kw}

def test_member_preference_wins_within_what_is_allowed(both):
    assert configured() == ['gemini', 'ollama']
    assert choose(settings(ai_preferences={'u1': 'ollama'}), 'u1') == ('ollama', 'your preference')
    assert choose(settings(ai_preferences={'u1': 'ollama'}, ai_default_provider='gemini'), 'u2') == ('gemini', 'organisation default')
    assert choose(settings(ai_providers=['gemini'], ai_preferences={'u1': 'ollama'}), 'u1')[0] == 'gemini'   # not allowed → ignored

def test_server_default_then_first_allowed(both, monkeypatch):
    monkeypatch.setenv('FLOODCAT_AI_PROVIDER', 'ollama')
    assert choose(settings(), 'u1') == ('ollama', 'server default')
    monkeypatch.delenv('FLOODCAT_AI_PROVIDER')
    assert choose(settings(), 'u1')[0] == 'gemini'

def test_client_data_stays_local_even_against_preference(both):
    rules = settings(ai_local_for_client_data=True, ai_preferences={'u1': 'gemini'}, ai_default_provider='gemini')
    assert choose(rules, 'u1', client_data=True)[0] == 'ollama'
    assert choose(rules, 'u1', client_data=False) == ('gemini', 'your preference')      # public material: the member's choice

def test_client_data_is_refused_rather_than_sent_to_the_cloud(cloud_only):
    with pytest.raises(ModelError, match='nothing was sent'):
        choose(settings(ai_local_for_client_data=True), 'u1', client_data=True)
    assert choose(settings(ai_local_for_client_data=True), 'u1')[0] == 'gemini'

def test_nothing_allowed_or_configured(cloud_only, monkeypatch):
    with pytest.raises(ModelError): choose(settings(ai_providers=['ollama']), 'u1')
    monkeypatch.delenv('GEMINI_API_KEY')
    with pytest.raises(ModelError): choose(settings(), 'u1')
