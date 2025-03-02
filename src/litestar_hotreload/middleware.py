"""Middleware to inject hot reload script into HTML responses."""

import logging
import textwrap
import warnings
from typing import cast

from jinja2 import Environment
from litestar.middleware import ASGIMiddleware
from litestar.types import (
    ASGIApp,
    HTTPScope,
    HTTPSendMessage,
    Receive,
    Scope,
    Send,
    WebSocketScope,
)

logger = logging.getLogger(__name__)


class HotReloadMiddleware(ASGIMiddleware):
    """Middleware to inject hot reload script into HTML responses."""

    def __init__(
        self,
        reconnect_interval: float,
        ws_path: str,
        environment: Environment,
    ):
        self._reconnect_interval = reconnect_interval
        self._ws_path = ws_path
        self.environment = environment

    async def handle(
        self, scope: Scope, receive: Receive, send: Send, next_app: ASGIApp
    ) -> None:
        """Handle asgi messages."""
        if scope["type"] == "websocket":
            logger.debug(f"Handling websocket scope on path: {scope['path']}")
            if scope["path"] != self._ws_path:
                await next_app(cast(WebSocketScope, scope), receive, send)
                return
            logger.debug("Handling websocket scope")
            await next_app(cast(WebSocketScope, scope), receive, send)
        else:
            logger.debug("Handling http scope")
            await self._handle_http(cast(HTTPScope, scope), receive, send, next_app)

    async def _handle_http(
        self, scope: HTTPScope, receive: Receive, send: Send, next_app: ASGIApp
    ) -> None:
        scheme = {
            "http": "ws",
            "https": "wss",
        }[scope["scheme"]]
        if scope["server"] is None:
            raise RuntimeError("Missing 'server' in ASGI scope")  # noqa: TRY003
        host, port = scope["server"]
        path = self._ws_path
        ws_url = f"{scheme}://{host}:{port}{path}"
        template = self.environment.get_template("hotreload.js")
        template_rendered = template.render(
            ws_url=ws_url, reconnect_interval=self._reconnect_interval
        )
        script = f'<script type="text/javascript">{template_rendered}</script>'.encode()
        inject_script = False

        async def wrapped_send(message: HTTPSendMessage) -> None:
            nonlocal inject_script

            if message["type"] == "http.response.start":
                # headers = dict(
                #     MutableScopeHeaders.from_message(message=message).headers
                # )
                headers = dict(message["headers"])
                if headers[b"content-type"].decode().partition(";")[0] != "text/html":
                    # This is not HTML.
                    await send(message)
                    return

                if headers.get(b"transfer-encoding") == b"chunked":
                    # Ignore streaming responses.
                    await send(message)
                    return

                if headers.get(b"content-encoding"):
                    msg = textwrap.dedent(
                        f"""Cannot inject reload script into response encoded as {headers[b"content-encoding"]!r}."""  # noqa: E501
                    )
                    warnings.warn(msg, stacklevel=2)

                    await send(message)
                    return

                inject_script = True

                if b"content-length" in headers:
                    new_length = int(headers[b"content-length"]) + len(script)
                    headers[b"content-length"] = str(new_length).encode()
                    message["headers"] = list(headers.items())

                await send(message)

            else:
                if not inject_script:
                    await send(message)
                    return

                # if message.get("more_body", False):
                #     raise LitestarHotReloadError("Unexpected streaming response")

                body: bytes = message["body"]  # type: ignore[typeddict-item]

                try:
                    start = body.index(b"</body>")
                except ValueError:
                    await send(message)
                    return

                head = body[:start]
                tail = body[start:]

                message["body"] = head + script + tail  # type: ignore[typeddict-unknown-key]
                await send(message)

        await next_app(scope, receive, wrapped_send)  # type: ignore[arg-type]
