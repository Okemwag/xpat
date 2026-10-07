"""Local accounts for the demo interface: PBKDF2-SHA256 hashes, roles, and login throttling."""
import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import datetime, timezone
from ..core.errors import ModelError

ROLES = ('analyst', 'reviewer', 'admin')
ROLE_HELP = {'analyst': 'Run portfolios and view results', 'reviewer': 'Also approve AI-extracted flood evidence',
             'admin': 'Also manage users'}
ITERATIONS = 310_000
MAX_FAILURES = 5
LOCKOUT_S = 300
_USERNAME = re.compile(r'^[a-z0-9][a-z0-9_.-]{2,31}$')

def _hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()

def check_password_rules(password):
    if len(password) < 10: raise ModelError('weak_password', 'Use at least 10 characters')
    if password.lower() == password or not any(c.isdigit() for c in password):
        raise ModelError('weak_password', 'Use upper- and lower-case letters and at least one digit')

class Accounts:
    def __init__(self, store):
        self.store = store
        self._failures = {}

    def ensure_admin(self):
        """Create the first admin from FLOODCAT_ADMIN_USER / FLOODCAT_ADMIN_PASSWORD if no users exist."""
        if self.store.get_users(): return
        user, password = os.getenv('FLOODCAT_ADMIN_USER'), os.getenv('FLOODCAT_ADMIN_PASSWORD')
        if user and password: self.register(user, password, 'Administrator', role='admin')

    def register(self, username, password, display_name, role='analyst', organisation=''):
        username = str(username).strip().lower()
        if not _USERNAME.match(username): raise ModelError('invalid_username', 'Username: 3–32 characters, letters, digits, . _ -')
        if role not in ROLES: raise ModelError('invalid_role', 'Unknown role')
        if not str(display_name).strip(): raise ModelError('invalid_name', 'Enter your name')
        check_password_rules(password)
        if username in self.store.get_users(): raise ModelError('username_taken', 'That username is taken')
        salt = secrets.token_hex(16)
        record = {'username': username, 'display_name': str(display_name).strip()[:80], 'organisation': str(organisation).strip()[:120],
                  'role': role, 'salt': salt, 'hash': _hash(password, salt), 'created_at': datetime.now(timezone.utc).isoformat()}
        self.store.put_user(username, record)
        return self.public(record)

    def authenticate(self, username, password):
        username = str(username).strip().lower()
        failures, since = self._failures.get(username, (0, 0.))
        if failures >= MAX_FAILURES and time.monotonic()-since < LOCKOUT_S:
            raise ModelError('locked', 'Too many failed attempts; try again in a few minutes')
        record = self.store.get_users().get(username)
        # Hash even for unknown users so timing does not reveal which usernames exist.
        expected = record['hash'] if record else _hash('x', '00'*16)
        actual = _hash(password, record['salt'] if record else '00'*16)
        if not record or not hmac.compare_digest(expected, actual):
            self._failures[username] = (failures+1, time.monotonic())
            raise ModelError('bad_credentials', 'Username or password is incorrect')
        self._failures.pop(username, None)
        return self.public(record)

    def change_password(self, username, old, new):
        self.authenticate(username, old); check_password_rules(new)
        record = dict(self.store.get_users()[username]); record['salt'] = secrets.token_hex(16)
        record['hash'] = _hash(new, record['salt']); self.store.put_user(username, record)

    def set_role(self, username, role, acting):
        if acting.get('role') != 'admin': raise ModelError('forbidden', 'Only admins can change roles')
        if role not in ROLES: raise ModelError('invalid_role', 'Unknown role')
        users = self.store.get_users()
        if username not in users: raise ModelError('not_found', 'User not found')
        if username == acting['username'] and role != 'admin': raise ModelError('forbidden', 'You cannot remove your own admin role')
        record = dict(users[username]); record['role'] = role; self.store.put_user(username, record)

    def list_users(self):
        return [self.public(r) for r in self.store.get_users().values()]

    @staticmethod
    def public(record):
        return {k: record.get(k) for k in ('username', 'display_name', 'organisation', 'role', 'created_at')}
