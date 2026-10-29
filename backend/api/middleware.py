"""Request metadata and streaming request-size enforcement."""
import json
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

try:
    from backend.config.settings import settings
except ImportError:  # pragma: no cover - supports running with `--app-dir backend`
    from config.settings import settings


class RequestTooLarge(Exception):
    """Raised when an upload request exceeds its configured byte limit."""


class RequestSecurityMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        is_upload = scope.get("path") == "/api/rag/upload" and scope.get("method") == "POST"
        request_size = 0
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        async def limited_receive() -> Message:
            nonlocal request_size
            message = await receive()
            if is_upload and message["type"] == "http.request":
                request_size += len(message.get("body", b""))
                if request_size > settings.upload_max_request_bytes:
                    raise RequestTooLarge
            return message

        if is_upload:
            content_length = next(
                (value for key, value in scope.get("headers", []) if key.lower() == b"content-length"),
                None,
            )
            if content_length is not None:
                try:
                    too_large = int(content_length) > settings.upload_max_request_bytes
                except ValueError:
                    too_large = True
                if too_large:
                    await self._send_too_large(send_with_request_id)
                    return

        try:
            await self.app(scope, limited_receive, send_with_request_id)
        except RequestTooLarge:
            if not response_started:
                await self._send_too_large(send_with_request_id)

    @staticmethod
    async def _send_too_large(send: Send, request_id: str | None = None) -> None:
        headers = [(b"content-type", b"application/json")]
        if request_id:
            headers.append((b"x-request-id", request_id.encode("ascii")))
        body = json.dumps({"detail": "Upload request exceeds the configured size limit."}).encode("utf-8")
        await send({"type": "http.response.start", "status": 413, "headers": headers})
        await send({"type": "http.response.body", "body": body})
