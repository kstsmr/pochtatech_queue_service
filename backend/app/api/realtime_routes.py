import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.errors import ApiError
from app.core.security import websocket_origin_allowed
from app.db.session import engine
from app.services.tickets import activate_if_due, ticket_response


router = APIRouter(prefix="/api/ws", tags=["Realtime"])
logger = logging.getLogger(__name__)


@router.websocket("/tickets/{ticket_id}")
async def ticket_updates(websocket: WebSocket, ticket_id: UUID) -> None:
    """Stream a private ticket state after an explicit first-message authentication."""
    if not websocket_origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=4403, reason="WebSocket origin is not allowed")
        return
    await websocket.accept()
    try:
        credentials = await asyncio.wait_for(websocket.receive_json(), timeout=5)
        raw_token = credentials.get("session_token") if isinstance(credentials, dict) else None
        if not isinstance(raw_token, str) or len(raw_token) < 20:
            await websocket.close(code=4401, reason="Ticket session is required")
            return

        previous_payload = ""
        while True:
            try:
                async with engine.begin() as connection:
                    await ticket_response(connection, ticket_id, raw_token)
                    await activate_if_due(connection, ticket_id)
                    ticket = await ticket_response(connection, ticket_id, raw_token)
            except ApiError:
                await websocket.close(code=4404, reason="Ticket was not found")
                return

            payload = ticket.model_dump(mode="json")
            serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True)
            if serialized != previous_payload:
                await websocket.send_json({"type": "ticket", "ticket": payload})
                previous_payload = serialized

            if ticket.status in {"served", "no_show", "cancelled"}:
                await websocket.close(code=1000, reason="Ticket is complete")
                return

            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=2)
                if message == "ping":
                    await websocket.send_json({"type": "pong"})
            except TimeoutError:
                continue
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    except Exception:
        logger.exception("ticket_websocket_failed", extra={"ticket_id": str(ticket_id)})
        try:
            await websocket.close(code=1011, reason="Realtime channel failed")
        except RuntimeError:
            pass
