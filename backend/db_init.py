from __future__ import annotations

from datetime import date, timedelta
import os
import secrets
import string
import sys

from sqlalchemy import select

import db
import models
from auth import hash_password


def _seed_minimal_data() -> None:
    """Bootstrap only the admin account.

    Real-data-only mode: do not seed demo stocks/prices/portfolio/watchlist/recommendations.
    """

    admin_email_env = os.getenv("ADMIN_EMAIL")
    admin_password_env = os.getenv("ADMIN_PASSWORD")
    force_password = (os.getenv("ADMIN_PASSWORD_FORCE", "0") or "0").strip() in {"1", "true", "True", "YES", "yes"}

    admin_email = (admin_email_env or "").strip()
    if not admin_email:
        admin_email = "administrator"

    generated_password: str | None = None
    did_set_password = False

    if force_password and not (admin_password_env or "").strip():
        raise RuntimeError("ADMIN_PASSWORD_FORCE=1 requires ADMIN_PASSWORD to be explicitly set")

    def ensure_password() -> str:
        nonlocal generated_password
        raw = (admin_password_env or "").strip()
        if raw:
            return raw
        # Generate only when we actually need to set a password.
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*_-"
        raw = "".join(secrets.choice(alphabet) for _ in range(20))
        generated_password = raw
        return raw

    with db.session_scope() as session:
        # Default user (id=1) used until JWT/login is implemented.
        user = session.execute(select(models.User).where(models.User.id == 1)).scalar_one_or_none()
        if user is None:
            # Prevent accidental email collisions (unique constraint).
            existing_email = session.execute(select(models.User).where(models.User.email == admin_email)).scalar_one_or_none()
            if existing_email is not None:
                raise RuntimeError(
                    "ADMIN_EMAIL is already used by an existing user. "
                    "Choose a different ADMIN_EMAIL or clean the DB before seeding."
                )

            admin_password_raw = ensure_password()
            session.add(
                models.User(
                    id=1,
                    email=admin_email,
                    nickname=admin_email,
                    password_hash=hash_password(admin_password_raw),
                    role="admin",
                    is_active=True,
                )
            )
            did_set_password = True
        else:
            # Keep user id=1 as the admin seed account.
            user.role = "admin"
            user.is_active = True

            # Only update email if the env var is explicitly set.
            if admin_email_env is not None:
                if user.email != admin_email:
                    existing_email = session.execute(select(models.User).where(models.User.email == admin_email)).scalar_one_or_none()
                    if existing_email is not None and int(existing_email.id) != 1:
                        raise RuntimeError(
                            "ADMIN_EMAIL is already used by another user. "
                            "Choose a different ADMIN_EMAIL or update the conflicting user in DB."
                        )
                    user.email = admin_email
                if (user.nickname or "").strip() == "":
                    user.nickname = admin_email

            # Password behavior:
            # - default: do NOT overwrite a real password
            # - overwrite only when ADMIN_PASSWORD_FORCE=1
            if force_password:
                user.password_hash = hash_password(ensure_password())
                did_set_password = True
            else:
                # Upgrade placeholder password to a real hash (idempotent) but do NOT overwrite a real password.
                if (user.password_hash or "").strip() in {"", "!", "*"}:
                    user.password_hash = hash_password(ensure_password())
                    did_set_password = True

        # If we generated a password and actually set it on this run, print it once for local dev.
        # Note: this prints to console only (not via API); set ADMIN_PASSWORD to avoid generation.
        if generated_password is not None and did_set_password:
            print(
                "[db-init] ADMIN_PASSWORD was not set. "
                f"Seeded/updated admin login '{admin_email}' with GENERATED password: {generated_password}"
            )

        # No demo data seeded.
        return


def main() -> int:
    try:
        engine = db.get_engine()
    except Exception as exc:
        print(f"[db-init] configuration error: {exc}")
        return 2

    try:
        models.Base.metadata.create_all(bind=engine)
        _seed_minimal_data()
        print("[db-init] OK: tables are created/verified")
        return 0
    except Exception as exc:
        print(f"[db-init] FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
