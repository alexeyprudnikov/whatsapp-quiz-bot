import logging
import httpx
from typing import Dict, Any
from app.config import settings

logger = logging.getLogger("hubspot_client")

class HubSpotClient:
    BASE_URL = "https://api.hubapi.com/crm/v3/objects/contacts"

    def __init__(self):
        self.access_token = settings.HUBSPOT_ACCESS_TOKEN

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    async def create_or_update_lead(self, phone_number: str, answers: Dict[str, Any]):
        """
        Creates or updates a contact in HubSpot when a lead is qualified.
        """
        if not self.access_token:
            logger.warning("HUBSPOT_ACCESS_TOKEN not set. Skipping HubSpot sync.")
            return

        # Parsing the name (if the full name "Max Mustermann" is passed)
        full_name = answers.get("user_name", "WhatsApp Lead").strip()
        name_parts = full_name.split(" ", 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        contact_phone = answers.get("user_phone", phone_number)

        # We compile a text note from all the funnel responses.
        formatted_answers = "\n".join([f"- {k}: {v}" for k, v in answers.items()])
        note_body = f"WhatsApp Quiz Responses:\n{formatted_answers}"

        # Standard HubSpot contact properties
        properties = {
            "firstname": first_name,
            "lastname": last_name,
            "phone": contact_phone,
            "hs_content_membership_notes": note_body,
            "lifecyclestage": "lead"
        }

        async with httpx.AsyncClient() as client:
            try:
                # 1. We are trying to establish contact.
                response = await client.post(
                    self.BASE_URL,
                    headers=self._get_headers(),
                    json={"properties": properties}
                )

                # 2. If a contact with such a phone number/email already exists (409 Conflict)
                if response.status_code == 409:
                    logger.info(f"Contact already exists in HubSpot for {contact_phone}. Searching...")
                    await self._update_existing_contact(client, contact_phone, properties)
                elif response.status_code in (200, 201):
                    contact_id = response.json().get("id")
                    logger.info(f"Successfully created HubSpot contact ID: {contact_id}")
                else:
                    logger.error(f"HubSpot API error ({response.status_code}): {response.text}")

            except Exception as e:
                logger.error(f"Failed to push lead to HubSpot: {e}", exc_info=True)

    async def _update_existing_contact(self, client: httpx.AsyncClient, phone: str, properties: dict):
        """A helper method for finding and updating an existing contact."""
        search_url = f"{self.BASE_URL}/search"
        search_payload = {
            "filterGroups": [{
                "filters": [{
                    "propertyName": "phone",
                    "operator": "EQ",
                    "value": phone
                }]
            }]
        }

        search_res = await client.post(search_url, headers=self._get_headers(), json=search_payload)
        if search_res.status_code == 200:
            results = search_res.json().get("results", [])
            if results:
                existing_id = results[0]["id"]
                update_url = f"{self.BASE_URL}/{existing_id}"
                await client.patch(update_url, headers=self._get_headers(), json={"properties": properties})
                logger.info(f"Successfully updated HubSpot contact ID: {existing_id}")


hubspot_client = HubSpotClient()