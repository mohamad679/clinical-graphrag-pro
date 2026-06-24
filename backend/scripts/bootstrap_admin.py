#!/usr/bin/env python3
"""
Create the very first admin account for a fresh deployment.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.auth import auth_service
from app.core.database import async_session_factory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap the initial admin account.")
    parser.add_argument("--email", default=os.getenv("BOOTSTRAP_ADMIN_EMAIL", ""), help="Admin email")
    parser.add_argument("--name", default=os.getenv("BOOTSTRAP_ADMIN_NAME", "Administrator"), help="Display name")
    parser.add_argument("--password", default=os.getenv("BOOTSTRAP_ADMIN_PASSWORD", ""), help="Admin password")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    email = args.email.strip().lower()
    name = args.name.strip() or "Administrator"
    password = args.password or getpass.getpass("Bootstrap admin password: ")

    if not email:
        print("Admin email is required. Pass --email or set BOOTSTRAP_ADMIN_EMAIL.", file=sys.stderr)
        return 1
    if not password:
        print("Admin password is required.", file=sys.stderr)
        return 1

    async with async_session_factory() as session:
        try:
            user = await auth_service.bootstrap_admin_async(
                session,
                email=email,
                password=password,
                name=name,
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            print(f"Bootstrap failed: {exc}", file=sys.stderr)
            return 1

    print(f"Created initial admin: {user.email} ({user.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
