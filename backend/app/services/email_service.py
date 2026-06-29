"""
Transactional email (verification + password reset).

Sends via SMTP when configured (settings.smtp_host). In development, or whenever
SMTP is not configured, the email is logged to the console instead of being sent
so the flow is fully testable without a mail provider.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


def _smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def send_email(to: str, subject: str, body: str) -> bool:
    """
    Send a plain-text email. Returns True if sent (or logged in dev fallback).

    Never raises to callers — a mail failure must not break registration.
    """
    if not to:
        return False
    if not _smtp_configured():
        # Dev fallback: log the message so links are usable locally.
        logger.warning("[EMAIL:dev-fallback] To=%s | %s\n%s", to, subject, body)
        return True
    try:
        msg = EmailMessage()
        msg["From"] = settings.email_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
            if settings.smtp_use_tls:
                s.starttls()
            s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
        logger.info("Email sent to %s (%s)", to, subject)
        return True
    except Exception as exc:
        logger.error("Email to %s failed: %s", to, exc)
        return False


def send_verification_email(to: str, username: str, token: str) -> bool:
    link = f"{settings.app_base_url.rstrip('/')}/verify-email?token={token}"
    body = (
        f"Hi {username},\n\n"
        "Confirm your NextGen TradeBot email address by opening this link:\n\n"
        f"  {link}\n\n"
        "If you didn't create this account, you can ignore this message.\n"
    )
    return send_email(to, "Verify your NextGen TradeBot account", body)


def send_password_reset_email(to: str, username: str, token: str) -> bool:
    link = f"{settings.app_base_url.rstrip('/')}/reset-password?token={token}"
    body = (
        f"Hi {username},\n\n"
        "We received a request to reset your NextGen TradeBot password.\n"
        "Open this link to choose a new password (valid for 1 hour):\n\n"
        f"  {link}\n\n"
        "If you didn't request this, you can safely ignore this email — your "
        "password will stay the same.\n"
    )
    return send_email(to, "Reset your NextGen TradeBot password", body)
