"""Alert email delivery via aiosmtplib. Kept deliberately separate from
services/alerts.py's scan/dedup logic so tests can mock exactly this one
network-touching function — see docs/CONTRACT_CLM_BUILD_PLAN.md §12 Phase 7
("Tests: mock SMTP").
"""

from email.message import EmailMessage

import aiosmtplib

from app.core.config import get_settings
from app.db.models import Obligation


class EmailSendError(Exception):
    """SMTP isn't configured, or the send itself failed."""


def _render_alert_email(obligation: Obligation) -> tuple[str, str, str]:
    category_label = obligation.category.value.replace("_", " ").title()
    contract_title = obligation.contract.title
    due = obligation.trigger_date.isoformat() if obligation.trigger_date else "no fixed date"

    subject = f"[ObliTrack] {category_label} due {due} — {contract_title}"
    text_body = (
        f'An obligation on "{contract_title}" needs your attention.\n\n'
        f"Category: {category_label}\n"
        f"Description: {obligation.description}\n"
        f"Trigger date: {due}\n"
        f"Status: {obligation.status.value.replace('_', ' ').title()}\n\n"
        "Review it in ObliTrack's Review Queue."
    )
    html_body = (
        f"<p>An obligation on <strong>{contract_title}</strong> needs your attention.</p>"
        "<ul>"
        f"<li><strong>Category:</strong> {category_label}</li>"
        f"<li><strong>Description:</strong> {obligation.description}</li>"
        f"<li><strong>Trigger date:</strong> {due}</li>"
        f"<li><strong>Status:</strong> {obligation.status.value.replace('_', ' ').title()}</li>"
        "</ul>"
        "<p>Review it in ObliTrack's Review Queue.</p>"
    )
    return subject, text_body, html_body


async def send_alert_email(*, recipient_email: str, obligation: Obligation) -> None:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_from_address:
        raise EmailSendError("SMTP is not configured (SMTP_HOST / SMTP_FROM_ADDRESS unset).")

    subject, text_body, html_body = _render_alert_email(obligation)

    message = EmailMessage()
    message["From"] = settings.smtp_from_address
    message["To"] = recipient_email
    message["Subject"] = subject
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username or None,
            password=settings.smtp_password or None,
            start_tls=True,
        )
    except (aiosmtplib.SMTPException, OSError) as exc:
        raise EmailSendError(f"SMTP send failed: {exc}") from exc
