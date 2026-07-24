import httpx
import logging
from app.config import settings

logger = logging.getLogger("whatsapp_client")

class WhatsAppClient:
    def __init__(self):
        self.url = f"https://graph.facebook.com/v19.0/{settings.PHONE_NUMBER_ID}/messages"
        self.headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        }

    async def send_text(self, to: str, text: str) -> bool:
        """Sending a standard text message"""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": text}
        }
        return await self._post(payload)

    async def send_interactive_buttons(self, to: str, body_text: str, buttons: list[dict]) -> bool:
        """
        Sending a message with interactive buttons (up to 3).
        buttons: [{"id": "btn_1", "title": "Button text"}]
        """
        formatted_buttons = [
            {
                "type": "reply",
                "reply": {
                    "id": btn["id"],
                    "title": btn["title"][:20]  # WhatsApp limit: 20 characters per button title.
                }
            }
            for btn in buttons
        ]

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {"buttons": formatted_buttons}
            }
        }
        return await self._post(payload)

    async def send_interactive_list(
        self,
        to: str,
        body_text: str,
        button_text: str,
        sections: list[dict],
        header_text: str | None = None
    ) -> bool:
        """
        Sends an Interactive List message (up to 10 rows).
        sections: [
            {
                "title": "Section Title",  # max 24 chars
                "rows": [
                    {"id": "opt_1", "title": "Row Title", "description": "Optional desc"}
                ]
            }
        ]
        """
        formatted_sections = []
        total_rows = 0

        for section in sections:
            formatted_rows = []
            for row in section.get("rows", []):
                if total_rows >= 10:
                    logger.warning("WhatsApp Interactive List exceeded 10 rows limit. Truncating extra items.")
                    break

                formatted_row = {
                    "id": str(row["id"]),
                    "title": str(row["title"])[:24]  # Meta limit: 24 chars
                }
                if row.get("description"):
                    formatted_row["description"] = str(row["description"])[:72]  # Meta limit: 72 chars

                formatted_rows.append(formatted_row)
                total_rows += 1

            if formatted_rows:
                formatted_sections.append({
                    "title": str(section.get("title", "Auswahl"))[:24],
                    "rows": formatted_rows
                })

            if total_rows >= 10:
                break

        interactive_payload = {
            "type": "list",
            "body": {"text": body_text},
            "action": {
                "button": button_text[:20],  # Meta limit: 20 chars
                "sections": formatted_sections
            }
        }

        if header_text:
            interactive_payload["header"] = {
                "type": "text",
                "text": header_text[:60]  # Meta limit: 60 chars for header
            }

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": interactive_payload
        }

        return await self._post(payload)

    async def _post(self, payload: dict) -> bool:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.url, json=payload, headers=self.headers, timeout=10.0)
                if response.status_code >= 400:
                    logger.error(f"WhatsApp API Error [{response.status_code}]: {response.text}")
                    return False
                return True
            except Exception as e:
                logger.error(f"Failed to send WhatsApp message: {e}")
                return False

whatsapp_client = WhatsAppClient()