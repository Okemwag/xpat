"""Organisation platform: tenancy, identity, access control, audit and organisation-scoped data.

Implements docs/ORGANISATION_CHECKLIST.md. One SQLAlchemy schema serves PostgreSQL (production, via
FLOODCAT_DATABASE_URL) and SQLite (development and tests).
"""
