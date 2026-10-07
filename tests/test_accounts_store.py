import pytest
from floodcat.core.errors import ModelError
from floodcat.services.accounts import Accounts
from floodcat.storage.local import LocalStore

@pytest.fixture
def accounts(tmp_path):
    return Accounts(LocalStore(tmp_path))

def test_register_and_login(accounts):
    accounts.register('Alice', 'Correct-horse-9', 'Alice A')
    user = accounts.authenticate('alice', 'Correct-horse-9')
    assert user['role'] == 'analyst' and 'hash' not in user

@pytest.mark.parametrize('password', ['short1A', 'alllowercase1', 'NoDigitsHere!'])
def test_weak_passwords_rejected(accounts, password):
    with pytest.raises(ModelError): accounts.register('bob', password, 'Bob')

def test_duplicate_and_invalid_usernames(accounts):
    accounts.register('carol', 'Correct-horse-9', 'Carol')
    with pytest.raises(ModelError): accounts.register('Carol', 'Correct-horse-9', 'Carol 2')
    with pytest.raises(ModelError): accounts.register('../x', 'Correct-horse-9', 'X')

def test_lockout_after_repeated_failures(accounts):
    accounts.register('dave', 'Correct-horse-9', 'Dave')
    for _ in range(5):
        with pytest.raises(ModelError): accounts.authenticate('dave', 'wrong')
    with pytest.raises(ModelError) as exc: accounts.authenticate('dave', 'Correct-horse-9')
    assert exc.value.code == 'locked'

def test_only_admin_changes_roles_and_cannot_demote_self(accounts):
    admin = accounts.register('root', 'Correct-horse-9', 'Root', role='admin')
    user = accounts.register('erin', 'Correct-horse-9', 'Erin')
    with pytest.raises(ModelError): accounts.set_role('root', 'analyst', user)
    accounts.set_role('erin', 'reviewer', admin)
    assert {u['username']: u['role'] for u in accounts.list_users()}['erin'] == 'reviewer'
    with pytest.raises(ModelError): accounts.set_role('root', 'analyst', admin)

def test_store_rejects_path_traversal_ids(tmp_path):
    store = LocalStore(tmp_path)
    with pytest.raises(ModelError): store.get_analysis('../../etc/passwd')
