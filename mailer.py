# mailer.py -- simple SMTP mail sender using stdlib only
# Reads SMTP settings from environment variables: SIRESET_SMTP_HOST, PORT, USER, PASS, FROM_EMAIL

from __future__ import annotations
import os
import smtplib
from email.message import EmailMessage
from typing import Iterable, Optional, Tuple


def _get_cfg() -> Tuple[str, int, str, str, str]:
    host = os.getenv("SIRESET_SMTP_HOST", "").strip()
    port_str = os.getenv("SIRESET_SMTP_PORT", "0").strip()
    try:
        port = int(port_str)
    except Exception:
        port = 0
    user = os.getenv("SIRESET_SMTP_USER", "").strip()
    pwd = os.getenv("SIRESET_SMTP_PASS", "").strip()
    from_addr = os.getenv("SIRESET_FROM_EMAIL", user).strip()
    return host, port, user, pwd, from_addr


def enabled() -> bool:
    host, port, user, pwd, _ = _get_cfg()
    return bool(host and port and user and pwd)


def send_mail(
    to: Iterable[str] | str,
    subject: str,
    html: str,
    *,
    plain: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Sends an email (HTML plus optional plain text).
    Returns (ok, error_message_if_any).
    """
    host, port, user, pwd, from_addr = _get_cfg()
    if not enabled():
        return False, "SMTP not configured (SIRESET_SMTP_* env vars missing)."

    to_list = [to] if isinstance(to, str) else list(to)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_list)
    if reply_to:
        msg["Reply-To"] = reply_to

    if plain:
        msg.set_content(plain)
        msg.add_alternative(html, subtype="html")
    else:
        # crude plain text fallback
        stripped = (
            html.replace("<br>", "\n")
                .replace("<br/>", "\n")
                .replace("<br />", "\n")
                .replace("<p>", "\n")
                .replace("</p>", "\n")
        )
        msg.set_content(stripped)
        msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            # try STARTTLS (typical for port 587)
            try:
                smtp.starttls()
            except smtplib.SMTPException:
                pass
            smtp.login(user, pwd)
            smtp.send_message(msg)
        return True, ""
    except Exception as e:
        return False, str(e)
