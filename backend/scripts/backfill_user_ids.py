#!/usr/bin/env python3
"""Assign legacy rows without user_id to the admin user."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal, User, PaperSession, Backtest, Job


def main():
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            print("No admin user found — skip backfill")
            return

        uid = admin.id
        for model in (PaperSession, Backtest, Job):
            rows = db.query(model).filter(model.user_id.is_(None)).all()
            for row in rows:
                row.user_id = uid
            print(f"{model.__tablename__}: backfilled {len(rows)} rows → admin")
        db.commit()
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
