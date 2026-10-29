import asyncio

from backend.api.middleware import RequestSecurityMiddleware
from backend.config.settings import settings


def test_streaming_upload_limit_applies_without_content_length(monkeypatch):
    monkeypatch.setattr(settings, "upload_max_request_bytes", 8)
    incoming = iter([
        {"type": "http.request", "body": b"12345", "more_body": True},
        {"type": "http.request", "body": b"67890", "more_body": False},
    ])
    outgoing = []

    async def receive():
        return next(incoming)

    async def send(message):
        outgoing.append(message)

    async def consume_body(scope, body_receive, body_send):
        await body_receive()
        await body_receive()

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/rag/upload",
        "headers": [],
        "state": {},
    }

    asyncio.run(RequestSecurityMiddleware(consume_body)(scope, receive, send))

    assert outgoing[0]["status"] == 413
    assert any(key == b"x-request-id" for key, _ in outgoing[0]["headers"])
