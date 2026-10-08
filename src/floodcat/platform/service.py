"""Process-wide platform handle: one engine, transactions, schema creation for development."""
from contextlib import contextmanager
from functools import lru_cache
from .db import create_schema, make_engine

class Platform:
    def __init__(self, url=None, create=True):
        self.engine = make_engine(url)
        if create and self.engine.dialect.name == 'sqlite': create_schema(self.engine)

    @contextmanager
    def tx(self):
        with self.engine.begin() as conn:
            yield conn

@lru_cache(maxsize=None)
def platform(url=None):
    return Platform(url)
