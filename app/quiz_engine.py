import json
import logging
import re
import redis.asyncio as aioredis
from app.config import settings
from app.whatsapp_client import whatsapp_client
from app.email_client import email_client
from app.hubspot_client import hubspot_client

logger = logging.getLogger("quiz_engine")

# Initialize asynchronous Redis client
redis_client = aioredis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    decode_responses=True
)


class InputValidator:
    @staticmethod
    def validate_phone_de(phone_str: str) -> bool:
        """
        Checks the format of a German phone number (+49..., 0170...).
        """
        cleaned = re.sub(r"[\s\-\(\)\/]", "", phone_str)
        pattern = r"^(\+49|0)[1-9][0-9]{8,11}$"
        return bool(re.match(pattern, cleaned))


class QuizEngine:
    def __init__(self, schema_path: str = "quiz_schema.json"):
        self.schema_path = schema_path
        self._load_schema()

    def _load_schema(self):
        """Internal method for loading the JSON schema."""
        with open(self.schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)
        self.start_node_id = self.schema["start_node"]
        self.nodes = self.schema["nodes"]

    def reload_schema(self):
        """Reloads the schema from disk into memory."""
        self._load_schema()
        logger.info("Quiz schema has been successfully reloaded in-memory.")

    async def _get_user_state(self, phone_number: str) -> dict:
        """Fetch user FSM state from Redis or return initial state."""
        data = await redis_client.get(f"state:{phone_number}")
        if data:
            return json.loads(data)

        # Default state for new users
        return {
            "current_node": self.start_node_id,
            "answers": {}
        }

    async def _save_user_state(self, phone_number: str, state: dict, ttl: int = 86400):
        """Save user state to Redis with a 24-hour TTL (matches Meta window)."""
        await redis_client.set(
            f"state:{phone_number}",
            json.dumps(state, ensure_ascii=False),
            ex=ttl
        )

    async def _clear_user_state(self, phone_number: str):
        """Remove user state from Redis upon quiz completion."""
        await redis_client.delete(f"state:{phone_number}")

    async def process_message(self, phone_number: str, user_input: str, is_button_click: bool = False):
        """Core message processing logic."""
        state = await self._get_user_state(phone_number)
        current_node_id = state["current_node"]
        current_node = self.nodes.get(current_node_id)

        if not current_node:
            logger.error(f"Node '{current_node_id}' not found in schema. Clearing state.")
            await self._clear_user_state(phone_number)
            return

        next_node_id = None
        node_type = current_node.get("type")

        # 1. Handle interactive button clicks or lists
        if node_type in ("buttons", "list"):
            if is_button_click:
                for option in current_node.get("options", []):
                    if option["id"] == user_input:
                        # Save user choice
                        state["answers"][current_node_id] = option["title"]
                        next_node_id = option["next_node"]
                        break

            # Fallback if user sent text instead of clicking a button
            if not next_node_id:
                fallback_message = "Bitte wählen Sie eine Option aus dem Menü unten:"
                await whatsapp_client.send_text(to=phone_number, text=fallback_message)
                await self._send_node(phone_number, current_node, state["answers"])
                return

        # 2. Handle text inputs (Name, Phone, etc.)
        elif node_type == "text_input":
            variable_name = current_node.get("variable", current_node_id)
            validation_rule = current_node.get("validation")

            # Validate German phone format if required
            if validation_rule == "phone_de":
                if not InputValidator.validate_phone_de(user_input):
                    invalid_phone_msg = (
                        "Ungültiges Telefonnummernformat. Bitte geben Sie eine gültige "
                        "Telefonnummer ein (z.B. +491701234567 oder 01701234567):"
                    )
                    await whatsapp_client.send_text(to=phone_number, text=invalid_phone_msg)
                    return

            # Save collected text variable
            user_text = user_input.strip()
            state["answers"][variable_name] = user_text
            next_node_id = current_node.get("next_node")

        # 3. Direct or fallback transition
        if not next_node_id:
            next_node_id = current_node.get("next_node", self.start_node_id)

        # Update state with the next node
        next_node = self.nodes.get(next_node_id)
        state["current_node"] = next_node_id
        await self._save_user_state(phone_number, state)

        # 4. Handle final node (lead qualified or offer declined)
        if next_node.get("type") == "final":
            await self._send_node(phone_number, next_node, state["answers"])

            # Log collected lead data
            logger.info(f"=== LEAD PROCESS COMPLETED: {phone_number} ===")
            logger.info(f"Collected payload: {json.dumps(state['answers'], ensure_ascii=False)}")

            # 1. Dispatch email notification (if enabled)
            if settings.ENABLE_EMAIL_NOTIFICATIONS:
                await email_client.send_lead_notification(
                    phone_number=phone_number,
                    answers=state["answers"]
                )
            else:
                logger.info("Email notifications are disabled in config. Skipping.")

            # 2. Sync lead to HubSpot CRM (if enabled)
            if settings.ENABLE_HUBSPOT_SYNC:
                await hubspot_client.create_or_update_lead(
                    phone_number=phone_number,
                    answers=state["answers"]
                )
            else:
                logger.info("HubSpot integration is disabled in config. Skipping.")

            await self._clear_user_state(phone_number)
        else:
            # Send next node to user
            await self._send_node(phone_number, next_node, state["answers"])

    async def _send_node(self, phone_number: str, node: dict, context_data: dict = None):
        """Dispatch visual components with template variable formatting."""
        node_type = node.get("type")
        text = node.get("text", "")

        # Format variables like {user_name} or {user_phone} if context exists
        if context_data and "{" in text:
            try:
                text = text.format(**context_data)
            except KeyError as e:
                logger.warning(f"Missing template key {e} in node text formatting.")

        if node_type == "buttons":
            await whatsapp_client.send_interactive_buttons(
                to=phone_number,
                body_text=text,
                buttons=node.get("options", [])
            )
        elif node_type == "list":
            # Creating a section for the drop-down list
            options = node.get("options", [])
            rows = [
                {
                    "id": opt["id"],
                    "title": opt["title"],
                    "description": opt.get("description", "")
                }
                for opt in options
            ]
            sections = [{"title": node.get("section_title", "Auswahl"), "rows": rows}]

            await whatsapp_client.send_interactive_list(
                to=phone_number,
                body_text=text,
                button_text=node.get("button_text", "Optionen anzeigen"),
                sections=sections
            )
        else:
            await whatsapp_client.send_text(to=phone_number, text=text)


quiz_engine = QuizEngine()