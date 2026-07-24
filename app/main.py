import logging
from fastapi import FastAPI, Header, Request, Response, BackgroundTasks, HTTPException, status
from app.config import settings
from app.quiz_engine import quiz_engine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("main")

app = FastAPI(title=settings.APP_NAME)


@app.get("/")
async def root_healthcheck():
    """Healthcheck endpoint for monitoring."""
    return {"status": "ok", "app": settings.APP_NAME}


# ------------------------------------------------------------------------------
# 1. Webhook Verification Endpoint (Meta Handshake)
# ------------------------------------------------------------------------------
@app.get("/webhook")
async def verify_webhook(request: Request):
    """
    Meta Cloud API verifies the webhook by sending a GET request with challenge parameters.
    Must return hub.challenge if the verify_token matches.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == settings.VERIFY_TOKEN:
        logger.info("Webhook successfully verified by Meta.")
        return Response(content=challenge, media_type="text/plain", status_code=status.HTTP_200_OK)

    logger.warning("Webhook verification failed. Invalid verify token.")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification token mismatch")


# ------------------------------------------------------------------------------
# 2. Incoming Messages Webhook Endpoint
# ------------------------------------------------------------------------------
@app.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives incoming events from Meta Cloud API (messages, button replies, delivery statuses).
    Processes messages asynchronously in the background to avoid Meta timeout retries.
    """
    try:
        data = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse JSON payload: {e}")
        return {"status": "invalid_json"}

    # Process payload safely
    try:
        entries = data.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})

                # Filter out system notifications (delivery receipts, read status, etc.)
                if "messages" not in value:
                    continue

                for message_data in value["messages"]:
                    phone_number = message_data.get("from")
                    if not phone_number:
                        continue

                    # Delegate processing to background task to keep webhook response < 200ms
                    background_tasks.add_task(parse_and_process_message, phone_number, message_data)

    except Exception as e:
        logger.error(f"Unexpected error while parsing Meta webhook structure: {e}")

    # Always return 200 OK immediately to acknowledge receipt
    return {"status": "ok"}


# ------------------------------------------------------------------------------
# 3. Message Parsing Worker
# ------------------------------------------------------------------------------
async def parse_and_process_message(phone_number: str, message: dict):
    """
    Extracts text body or button payload from WhatsApp payload
    and passes it to QuizEngine.
    """
    msg_type = message.get("type")
    user_input = ""
    is_button_click = False

    if msg_type == "text":
        user_input = message.get("text", {}).get("body", "").strip()

    elif msg_type == "interactive":
        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type")

        # Quick Reply Button Click
        if interactive_type == "button_reply":
            user_input = interactive.get("button_reply", {}).get("id", "")
            is_button_click = True

        # List Selection (Fallback if list components are added later)
        elif interactive_type == "list_reply":
            user_input = interactive.get("list_reply", {}).get("id", "")
            is_button_click = True

    if not user_input:
        logger.info(f"Ignored unsupported message type '{msg_type}' from {phone_number}")
        return

    logger.info(f"Processing message from {phone_number} | Type: {msg_type} | Input: {user_input}")

    # Dispatch to Quiz Engine
    await quiz_engine.process_message(
        phone_number=phone_number,
        user_input=user_input,
        is_button_click=is_button_click
    )

@app.post("/api/v1/admin/reload-schema", status_code=status.HTTP_200_OK)
async def reload_quiz_schema(x_admin_key: str = Header(...)):
    # Protecting the endpoint with a secret key
    if x_admin_key != settings.SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Admin Secret Key"
        )

    try:
        quiz_engine.reload_schema()
        return {"status": "success", "message": "Quiz schema successfully reloaded"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reload schema: {str(e)}"
        )