import asyncio
import logging
from email.message import EmailMessage
import smtplib
from app.config import settings

logger = logging.getLogger("email_client")

class EmailClient:
    def __init__(self):
        self.host = settings.SMTP_HOST
        self.port = settings.SMTP_PORT
        self.user = settings.SMTP_USER
        self.password = settings.SMTP_PASSWORD
        self.recipient = settings.NOTIFICATION_EMAIL

    def _send_sync_email(self, subject: str, body_text: str):
        """Synchronous helper method executed in a separate thread."""
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.user
        msg["To"] = self.recipient
        msg.set_content(body_text)

        with smtplib.SMTP(self.host, self.port) as server:
            server.starttls()
            server.login(self.user, self.password)
            server.send_message(msg)

    async def send_lead_notification(self, phone_number: str, answers: dict) -> bool:
        """Asynchronously dispatches lead email notifications."""
        if not self.user or not self.recipient:
            logger.warning("Email settings not configured. Skipping email dispatch.")
            return False

        subject = f"🔥 New Lead Received: {phone_number}"

        # Format human-readable answers summary
        formatted_answers = "\n".join(
            [f"- {node_id}: {answer}" for node_id, answer in answers.items()]
        )
        body = (
            f"A new qualified lead has completed the WhatsApp quiz!\n\n"
            f"Phone Number: {phone_number}\n"
            f"Collected Responses:\n{formatted_answers}\n\n"
            f"---\n"
            f"WhatsApp Quiz Bot System Notification"
        )

        try:
            # Offload blocking SMTP I/O to an asyncio thread pool worker
            await asyncio.to_thread(self._send_sync_email, subject, body)
            logger.info(f"Lead email notification successfully sent for {phone_number}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email notification for {phone_number}: {e}")
            return False

email_client = EmailClient()