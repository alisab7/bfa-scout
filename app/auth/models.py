import os
import psycopg2.extras
from flask_login import UserMixin
from app.db import _get_pool


class User(UserMixin):
    """Lightweight wrapper around a row from the users table."""

    def __init__(self, row):
        self.id          = row['id']
        self.email       = row['email']
        self.full_name   = row['full_name']
        self.full_name_ar = row.get('full_name_ar')
        self.role        = row['role']
        self.phone       = row.get('phone')
        self._is_active  = row['is_active']
        self.last_login_at = row.get('last_login_at')

    # ── Flask-Login interface ──────────────────────────────────────

    @property
    def is_active(self):
        return self._is_active

    def get_id(self):
        return str(self.id)

    # ── Convenience helpers ───────────────────────────────────────

    def has_role(self, *roles):
        return self.role in roles

    # ── Class-level DB queries ────────────────────────────────────

    @classmethod
    def _query_one(cls, sql, params=()):
        conn = _get_pool().getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
            return cls(row) if row else None
        finally:
            _get_pool().putconn(conn)

    @classmethod
    def get_by_id(cls, user_id):
        return cls._query_one(
            'SELECT * FROM users WHERE id = %s',
            (user_id,)
        )

    @classmethod
    def get_by_email(cls, email):
        return cls._query_one(
            'SELECT * FROM users WHERE email = %s',
            (email,)
        )
