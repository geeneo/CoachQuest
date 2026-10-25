"""Outgoing email over SMTP, configured on the Admin page (or .env)."""

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

from . import runtime

log = logging.getLogger("coachquest.mail")


class MailError(Exception):
    pass


def configured() -> bool:
    return bool(runtime.get("smtp_host") and runtime.get("smtp_from"))


def _send(to: str, subject: str, text: str) -> None:
    host, port = runtime.get("smtp_host"), int(runtime.get("smtp_port") or 587)
    security = runtime.get("smtp_security") or "starttls"
    msg = EmailMessage()
    msg["From"] = runtime.get("smtp_from")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    context = ssl.create_default_context()
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=20, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=20)
    with server:
        if security == "starttls":
            server.starttls(context=context)
        if runtime.get("smtp_username"):
            server.login(runtime.get("smtp_username"), runtime.get("smtp_password"))
        server.send_message(msg)


async def send(to: str, subject: str, text: str) -> None:
    """Send a plain-text email. Raises MailError with a message an admin can act on."""
    if not configured():
        raise MailError("Email is not set up yet (Admin → Settings → Email).")
    try:
        await asyncio.to_thread(_send, to, subject, text)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError("The mail server rejected the username or password.") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailError(f"The mail server refused the address {to}.") from exc
    except smtplib.SMTPSenderRefused as exc:
        raise MailError("The mail server refused the From address. It usually must match the account.") from exc
    except ssl.SSLError as exc:
        raise MailError("TLS failed. Check the port and security setting (587 + starttls, or 465 + ssl).") from exc
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("Sending mail failed: %r", exc)
        raise MailError(f"Could not send: {exc}") from exc
    log.info("Sent email %r to %s", subject, to)
