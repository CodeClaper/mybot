import re
import ssl
import http
import json
import hmac
import time
import uuid
import binascii
import base64
import hashlib
import asyncio
import secrets
import shutil
import mimetypes
import email.utils
from pathlib import Path
from typing import Any
from loguru import logger
from mybot.bus.message import OutboundMessage
from mybot.bus.queue import MessageBus
from mybot.channels.base import BaseChannel
from mybot.commands.builtin import BUILTIN_COMMAND_SPECS
from mybot.config.path import get_media_dir
from mybot.config.schema import Config, WebSocketConfig
from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request as WsRequest
from websockets.http11 import Response
from urllib.parse import parse_qs, unquote, urlparse

from mybot.context.session import SessionManager
from mybot.utils.helper import safe_filename
from mybot.utils.media_decode import FileSizeExceeded, save_base64_data_url


_LOCALHOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_WEB_SEARCH_PROVIDER_OPTIONS: tuple[dict[str, str], ...] = (
    {"name": "duckduckgo", "label": "DuckDuckGo", "credential": "none"},
    {"name": "brave", "label": "Brave Search", "credential": "api_key"},
    {"name": "tavily", "label": "Tavily", "credential": "api_key"},
    {"name": "searxng", "label": "SearXNG", "credential": "base_url"},
    {"name": "jina", "label": "Jina", "credential": "api_key"},
    {"name": "kagi", "label": "Kagi", "credential": "api_key"},
    {"name": "olostep", "label": "Olostep", "credential": "api_key"},
)
_WEB_SEARCH_PROVIDER_BY_NAME = {
    provider["name"]: provider for provider in _WEB_SEARCH_PROVIDER_OPTIONS
}

# Matches the legacy chat-id pattern but allows file-system-safe stems too,
# so the API can address sessions whose keys came from non-WebSocket channels.
_API_KEY_RE = re.compile(r"^[A-Za-z0-9_:.-]{1,128}$")

# Allowed MIME types we actually serve from the media endpoint. Anything
# outside this set is degraded to ``application/octet-stream`` so an
# attacker who somehow gets a signed URL for an unexpected file type can't
# trick the browser into sniffing executable content.
_MEDIA_ALLOWED_MIMES: frozenset[str] = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "video/mp4",
    "video/webm",
    "video/quicktime",
})

# Accept UUIDs and short scoped keys like "unified:default". Keeps the capability
# namespace small enough to rule out path traversal / quote injection tricks.
_CHAT_ID_RE = re.compile(r"^[A-Za-z0-9_:-]{1,64}$")

# Per-message media limits. The server-side guard is a touch looser than the
# client's ``Worker`` normalization target (6 MB) — tolerate client slop, but
# still cap total ingress at ``_MAX_IMAGES_PER_MESSAGE * _MAX_IMAGE_BYTES``
# which fits comfortably inside ``max_message_bytes``.
_MAX_IMAGES_PER_MESSAGE = 4
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MAX_VIDEOS_PER_MESSAGE = 1
_MAX_VIDEO_BYTES = 20 * 1024 * 1024

# Image MIME whitelist — matches the Composer's ``accept`` list. SVG is
# explicitly excluded to avoid the XSS surface inside embedded scripts.
_IMAGE_MIME_ALLOWED: frozenset[str] = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
})

_VIDEO_MIME_ALLOWED: frozenset[str] = frozenset({
    "video/mp4",
    "video/webm",
    "video/quicktime",
})


_UPLOAD_MIME_ALLOWED: frozenset[str] = _IMAGE_MIME_ALLOWED | _VIDEO_MIME_ALLOWED

_DATA_URL_MIME_RE = re.compile(r"^data:([^;]+);base64,", re.DOTALL)

class WebSocketChannel(BaseChannel):
    """Read a local webSocket server; forward text/JSON message to the message bus."""

    name = "websocket"
    display_name = "WebSocket"

    _MAX_ISSUED_TOKENS = 10_000

    def __init__(
        self,
        config: Config,
        bus: MessageBus,
        *,
        session_manager: SessionManager | None = None,
        static_dist_path: Path | None = None,
    ):
        super().__init__(config, bus)
        self.config: WebSocketConfig = config.channels.websocket
        self._conn_default: dict[Any, str] = {}
        self._subs: dict[str, set[Any]] = {}
        self._conn_chats: dict[Any, set[str]] = {}
        self._stop_event: asyncio.Event | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._issued_tokens: dict[str, float] = {}
        self._api_tokens: dict[str, float] = {}
        self._session_manager = session_manager
        self._media_secret: bytes = secrets.token_bytes(32)
        self._static_dist_path: Path | None = (
            static_dist_path.resolve() if static_dist_path is not None else None
        )

    async def login(self, force: bool = False) -> bool:
        logger.error("Not support direct login for websocket channel.")
        return False
    
    async def start(self) -> None:
        self._running = True
        self._stop_event = asyncio.Event()

        ssl_context = self._build_ssl_context()
        schema = "wss" if ssl_context else "ws"
        
        logger.info(
            "WebSocket server listening on {}://{}:{}{}",
            schema,
            self.config.host,
            self.config.port,
            self.config.path,
        )

        async def process_request(
            connection: ServerConnection,
            request: WsRequest,
        ) -> Any:
            return await self._dispatch_http(connection, request)

        async def handler(connection: ServerConnection) -> None:
            await self._connection_loop(connection)

        async def runner() -> None:
            async with serve(
                handler,
                self.config.host,
                self.config.port,
                process_request=process_request,
                max_size=self.config.max_message_bytes,
                ping_interval=self.config.ping_interval_s,
                ping_timeout=self.config.ping_timeout_s,
                ssl=ssl_context,
            ):
                assert self._stop_event is not None
                await self._stop_event.wait()
        
        self._sever_task = asyncio.create_task(runner())
        await self._sever_task

    async def send(self, msg: OutboundMessage) -> None:
        if msg.metadata.get("_runtime_model_updated"):
            await self.send_runtime_model_updated(
                model_name=msg.metadata.get("model"),
                model_preset=msg.metadata.get("model_preset"),
            )
            return

        # Snapshot the subscriber set so ConnectionClosed cleanups mid-iteration are safe.
        conns = list(self._subs.get(msg.chat_id, ()))
        if not conns:
            if (
                msg.metadata.get("_progress")
                or msg.metadata.get("_turn_end")
                or msg.metadata.get("_session_updated")
            ):
                logger.debug("no active subscribers for chat_id={}", msg.chat_id)
            else:
                logger.warning("no active subscribers for chat_id={}", msg.chat_id)
            return
        # Signal that the agent has fully finished processing the current turn.
        if msg.metadata.get("_turn_end"):
            await self.send_turn_end(msg.chat_id)
            return
        if msg.metadata.get("_session_updated"):
            await self.send_session_updated(msg.chat_id)
            return
        text = msg.content
        payload: dict[str, Any] = {
            "event": "message",
            "chat_id": msg.chat_id,
            "text": text,
        }
        if msg.media:
            payload["media"] = msg.media
            urls: list[dict[str, str]] = []
            for entry in msg.media:
                signed = self._sign_or_stage_media_path(Path(entry))
                if signed is not None:
                    urls.append(signed)
            if urls:
                payload["media_urls"] = urls
        if msg.reply_to:
            payload["reply_to"] = msg.reply_to
        # Mark intermediate agent breadcrumbs (tool-call hints, generic
        # progress strings) so WS clients can render them as subordinate
        # trace rows rather than conversational replies.
        if msg.metadata.get("_tool_hint"):
            payload["kind"] = "tool_hint"
        elif msg.metadata.get("_progress"):
            payload["kind"] = "progress"
        raw = json.dumps(payload, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" ")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._stop_event:
            self._stop_event.set()
        if self._server_task:
            try:
                await self._server_task
            except Exception as e:
                logger.warning("server task error during shutdown: {}", e)
            self._server_task = None
        self._subs.clear()
        self._conn_chats.clear()
        self._conn_default.clear()
        self._issued_tokens.clear()
        self._api_tokens.clear()


    def _build_ssl_context(self) -> ssl.SSLContext | None:
        cert = self.config.ssl_certfile.strip()
        key = self.config.ssl_keyfile.strip()
        if not cert and not key:
            return None
        if not cert or not key:
            raise ValueError(
                "ssl_certfile and ssl_keyfile must both be set for WSS, or both left empty"
            )
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(certfile=cert, keyfile=key)
        return ctx

    async def _connection_loop(self, connection: ServerConnection) -> None:
        request = connection.request
        path_part = request.path if request else "/"
        _, query = self._parse_request_path(path_part)
        client_id_raw = self._query_first(query, "client_id")
        client_id = client_id_raw.strip() if client_id_raw else ""
        if not client_id:
            client_id = f"anon-{uuid.uuid4().hex[:12]}"
        elif len(client_id) > 128:
            logger.warning("client_id too long ({} chars), truncating", len(client_id))
            client_id = client_id[:128]

        default_chat_id = str(uuid.uuid4())

        try:
            await connection.send(
                json.dumps(
                    {
                        "event": "ready",
                        "chat_id": default_chat_id,
                        "client_id": client_id,
                    },
                    ensure_ascii=False,
                )
            )
            # Register only after ready is successfully sent to avoid out-of-order sends
            self._conn_default[connection] = default_chat_id
            self._attach(connection, default_chat_id)

            async for raw in connection:
                if isinstance(raw, bytes):
                    try:
                        raw = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        logger.warning("ignoring non-utf8 binary frame")
                        continue

                envelope = self._parse_envelope(raw)
                if envelope is not None:
                    await self._dispatch_envelope(connection, client_id, envelope)
                    continue

                content = self._parse_inbound_payload(raw)
                if content is None:
                    continue
                await self._handle_message(
                    sender_id=client_id,
                    chat_id=default_chat_id,
                    content=content,
                    metadata={"remote": getattr(connection, "remote_address", None)},
                )
        except Exception as e:
            logger.error("connection ended: {}", e)
        finally:
            self._cleanup_connection(connection)

    def _parse_inbound_payload(self, raw: str) -> str | None:
        """Parse a client frame into text; return None for empty or unrecognized content."""
        text = raw.strip()
        if not text:
            return None
        if text.startswith("{"):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return text
            if isinstance(data, dict):
                for key in ("content", "text", "message"):
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        return value
                return None
            return None
        return text

            
    def _attach(self, connection: Any, chat_id: str) -> None:
        """Idempotently subscribe *connection* to *chat_id*."""
        self._subs.setdefault(chat_id, set()).add(connection)
        self._conn_chats.setdefault(connection, set()).add(chat_id)

    def _cleanup_connection(self, connection: Any) -> None:
        """Remove *connection* from every subscription set; safe to call multiple times."""
        chat_ids = self._conn_chats.pop(connection, set())
        for cid in chat_ids:
            subs = self._subs.get(cid)
            if subs is None:
                continue
            subs.discard(connection)
            if not subs:
                self._subs.pop(cid, None)
        self._conn_default.pop(connection, None)

    def _parse_envelope(self, raw: str) -> dict[str, Any] | None:
        """Return a typed envelope dict if the frame is a new-style JSON envelope, else None.

        A frame qualifies when it parses as a JSON object with a string ``type`` field.
        Legacy frames (plain text, or ``{"content": ...}`` without ``type``) return None;
        callers should fall back to :func:`_parse_inbound_payload` for those.
        """
        text = raw.strip()
        if not text.startswith("{"):
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        t = data.get("type")
        if not isinstance(t, str):
            return None
        return data

    async def _send_event(self, connection: Any, event: str, **fields: Any) -> None:
        """Send a control event (attached, error, ...) to a single connection."""
        payload: dict[str, Any] = {"event": event}
        payload.update(fields)
        raw = json.dumps(payload, ensure_ascii=False)
        try:
            await connection.send(raw)
        except ConnectionClosed:
            self._cleanup_connection(connection)
        except Exception as e:
            logger.warning("failed to send {} event: {}", event, e)

    async def _dispatch_envelope(
        self,
        connection: Any,
        client_id: str,
        envelope: dict[str, Any],
    ) -> None:
        """Route one typed inbound envelope (``new_chat`` / ``attach`` / ``message``)."""
        t = envelope.get("type")
        if t == "new_chat":
            new_id = str(uuid.uuid4())
            self._attach(connection, new_id)
            await self._send_event(connection, "attached", chat_id=new_id)
            return
        if t == "attach":
            cid = envelope.get("chat_id")
            if not self._is_valid_chat_id(cid):
                await self._send_event(connection, "error", detail="invalid chat_id")
                return
            self._attach(connection, str(cid))
            await self._send_event(connection, "attached", chat_id=cid)
            return
        if t == "message":
            cid = envelope.get("chat_id")
            content = envelope.get("content")
            if not self._is_valid_chat_id(cid):
                await self._send_event(connection, "error", detail="invalid chat_id")
                return
            if not isinstance(content, str):
                await self._send_event(connection, "error", detail="missing content")
                return

            raw_media = envelope.get("media")
            media_paths: list[str] = []
            if raw_media is not None:
                if not isinstance(raw_media, list):
                    await self._send_event(
                        connection, "error",
                        detail="image_rejected", reason="malformed",
                    )
                    return
                media_paths, reason = self._save_envelope_media(raw_media)
                if reason is not None:
                    await self._send_event(
                        connection, "error",
                        detail="image_rejected", reason=reason,
                    )
                    return

            # Allow image-only turns (content may be empty when media is attached).
            if not content.strip() and not media_paths:
                await self._send_event(connection, "error", detail="missing content")
                return

            # Auto-attach on first use so clients can one-shot without a separate attach.
            self._attach(connection, str(cid))
            metadata: dict[str, Any] = {"remote": getattr(connection, "remote_address", None)}
            if envelope.get("webui") is True:
                metadata["webui"] = True
            image_generation = envelope.get("image_generation")
            if isinstance(image_generation, dict) and image_generation.get("enabled") is True:
                aspect_ratio = image_generation.get("aspect_ratio")
                metadata["image_generation"] = {
                    "enabled": True,
                    "aspect_ratio": aspect_ratio if isinstance(aspect_ratio, str) else None,
                }
            await self._handle_message(
                sender_id=client_id,
                chat_id= str(cid),
                content=content,
                media=media_paths or None,
                metadata=metadata,
            )
            return
        await self._send_event(connection, "error", detail=f"unknown type: {t!r}")

    def _save_envelope_media(
        self,
        media: list[Any],
    ) -> tuple[list[str], str | None]:
        """Decode and persist ``media`` items from a ``message`` envelope.

        Returns ``(paths, None)`` on success or ``([], reason)`` on the first
        failure — the caller is expected to surface ``reason`` to the client
        and skip publishing so no half-formed message ever reaches the agent.
        On failure, any files already written to disk earlier in the same
        call are unlinked so partial ingress doesn't leak orphan files.
        ``reason`` is a short, stable token suitable for UI localization.

        Shape: ``list[{"data_url": str, "name"?: str | None}]``.
        """
        image_count = 0
        video_count = 0
        for item in media:
            mime = self._extract_data_url_mime(item.get("data_url", "")) if isinstance(item, dict) else None
            if mime in _VIDEO_MIME_ALLOWED:
                video_count += 1
            elif mime in _IMAGE_MIME_ALLOWED:
                image_count += 1
        if image_count > _MAX_IMAGES_PER_MESSAGE:
            return [], "too_many_images"
        if video_count > _MAX_VIDEOS_PER_MESSAGE:
            return [], "too_many_videos"

        media_dir = get_media_dir("websocket")
        paths: list[str] = []

        def _abort(reason: str) -> tuple[list[str], str]:
            for p in paths:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning(
                        "failed to unlink partial media {}: {}", p, exc
                    )
            return [], reason

        for item in media:
            if not isinstance(item, dict):
                return _abort("malformed")
            data_url = item.get("data_url")
            if not isinstance(data_url, str) or not data_url:
                return _abort("malformed")
            mime = self._extract_data_url_mime(data_url)
            if mime is None:
                return _abort("decode")
            if mime not in _UPLOAD_MIME_ALLOWED:
                return _abort("mime")
            is_video = mime in _VIDEO_MIME_ALLOWED
            max_bytes = _MAX_VIDEO_BYTES if is_video else _MAX_IMAGE_BYTES
            try:
                saved = save_base64_data_url(
                    data_url, media_dir, max_bytes=max_bytes,
                )
            except FileSizeExceeded:
                return _abort("size")
            except Exception as exc:
                logger.warning("media decode failed: {}", exc)
                return _abort("decode")
            if saved is None:
                return _abort("decode")
            paths.append(saved)
        return paths, None


    async def _dispatch_http(self, connection: ServerConnection, request: WsRequest) -> Any:
        """Route an inbound HTTP request to a handler or to the WS upgrade path."""
        got, query = self._parse_request_path(request.path)

        # 1. login
        if got == "/api/login":
            return await self._handle_login(request)

        # 2. WebUI bootstrap: mints tokens for the embedded UI.
        if got == "/webui/bootstrap":
            return await self._handle_webui_bootstrap(request)

        # 3. REST surface for the embedded UI.
        if got == "/api/sessions":
            return await self._handle_sessions_list(request)

        if got == "/api/settings":
            return await self._handle_settings(request)

        if got == "/api/commands":
            return await self._handle_commands(request)

        if got == "/api/settings/update":
            return await self._handle_settings_update(request)

        if got == "/api/settings/provider/update":
            return await self._handle_settings_provider_update(request)

        if got == "/api/settings/web-search/update":
            return await self._handle_settings_web_search_update(request)

        m = re.match(r"^/api/sessions/([^/]+)/messages$", got)
        if m:
            return await self._handle_session_messages(request, m.group(1))

        # NOTE: websockets' HTTP parser only accepts GET, so we cannot expose a
        # true ``DELETE`` verb. The action is folded into the path instead.
        m = re.match(r"^/api/sessions/([^/]+)/delete$", got)
        if m:
            return await self._handle_session_delete(request, m.group(1))

        # Signed media fetch: ``<sig>`` is an HMAC over ``<payload>``; the
        # payload decodes to a path inside :func:`get_media_dir`. See
        # :meth:`_sign_media_path` for the inverse direction used to build
        # these URLs when replaying a session.
        m = re.match(r"^/api/media/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)$", got)
        if m:
            return self._handle_media_fetch(m.group(1), m.group(2))

        # 4. WebSocket upgrade (the channel's primary purpose). Only run the
        # handshake gate on requests that actually ask to upgrade; otherwise
        # a bare ``GET /`` from the browser would be rejected as an
        # unauthorized WS handshake instead of serving the SPA's index.html.
        expected_ws = self._expected_path()
        if got == expected_ws and self._is_websocket_upgrade(request):
            client_id = self._query_first(query, "client_id") or ""
            if len(client_id) > 128:
                client_id = client_id[:128]
            if not self.is_allowed(client_id):
                return connection.respond(403, "Forbidden")
            return self._authorize_websocket_handshake(connection, query)

        # 5. Static SPA serving (only if a build directory was wired in).
        if self._static_dist_path is not None:
            response = self._serve_static(got)
            if response is not None:
                return response

        return connection.respond(404, "Not Found")


    def _parse_request_path(self, path_with_query: str) -> tuple[str, dict[str, list[str]]]:
        """Parse normalized path and query parameters in one pass."""
        parsed = urlparse("ws://x" + path_with_query)
        path = self._strip_trailing_slash(parsed.path or "/")
        return path, parse_qs(parsed.query, keep_blank_values=True)

    def _strip_trailing_slash(self, path: str) -> str:
        if len(path) > 1 and path.endswith("/"):
            return path.rstrip("/")
        return path or "/"

    def _normalize_config_path(self, path: str) -> str:
        return self._strip_trailing_slash(path)
    
    async def _handle_login(self, request: WsRequest) -> Response:
        """Handle login request with username/password, return a bootstrap token."""
        query = self._parse_query(request.path)
        username = self._query_first(query, "username")
        password = self._query_first(query, "password")
        if not username or not password:
            return self._http_error(401, "Unauthorized")
        return self._http_json_response(
            {
                "ws_path": self._expected_path(),
                "model_name": self._read_webui_model_name(),
            }
        )

    async def _handle_webui_bootstrap(self, request: WsRequest) -> Response:
        token = request.headers.get("x-mybot-auth")
        if not token:
            return self._http_error(401, "Unauthorized")
        return self._http_json_response(
            {
                "ws_path": self._expected_path(),
                "model_name": self._read_webui_model_name(),
            }
        )

    async def _handle_sessions_list(self, request: WsRequest) -> Response:
        if self._session_manager is None:
            return self._http_error(503, "session manager unavailable")
        sessions = self._session_manager.list_sessions()
        # The webui is only meaningful for websocket-channel chats — CLI /
        # Slack / Lark / Discord sessions can't be resumed from the browser,
        # so leaking them into the sidebar is just noise. Filter to the
        # ``websocket:`` prefix and strip absolute paths on the way out.
        cleaned = [
            {k: v for k, v in s.items() if k != "path"}
            for s in sessions
            if isinstance(s.get("key"), str) and s["key"].startswith("websocket:")
        ]
        return self._http_json_response({"sessions": cleaned})

    async def _handle_settings(self, request: WsRequest) -> Response:
        return self._http_json_response(self._settings_payload())
    
    async def _handle_commands(self, request: WsRequest) -> Response:
        return self._http_json_response({"commands": self.builtin_command_palette()})

    async def _handle_settings_update(self, request: WsRequest) -> Response:
        from mybot.config.loader import load_config, save_config
        from mybot.providers.registry import find_by_name

        query = self._parse_query(request.path)
        config = load_config()
        defaults = config.agents.defaults
        changed = False

        model = self._query_first(query, "model")
        if model is not None:
            model = model.strip()
            if not model:
                return self._http_error(400, "model is required")
            if defaults.model != model:
                defaults.model = model
                changed = True

        provider = self._query_first(query, "provider")
        if provider is not None:
            provider = provider.strip()
            if not provider:
                return self._http_error(400, "provider is required")
            if find_by_name(provider) is None:
                return self._http_error(400, "unknown provider")
            provider_config = getattr(config.providers, provider, None)
            if provider_config is None or not provider_config.api_key:
                return self._http_error(400, "provider is not configured")
            if defaults.provider != provider:
                defaults.provider = provider
                changed = True

        if changed:
            save_config(config)
        # LLM provider/model changes are hot-reloaded by AgentLoop before each
        # new turn via the provider snapshot loader, so a restart is unnecessary.
        return self._http_json_response(self._settings_payload(requires_restart=False))


    async def _handle_settings_provider_update(self, request: WsRequest) -> Response:
        from mybot.config.loader import load_config, save_config
        from mybot.providers.registry import find_by_name

        query = self._parse_query(request.path)
        provider_name = (self._query_first(query, "provider") or "").strip()
        if not provider_name:
            return self._http_error(400, "provider is required")
        spec = find_by_name(provider_name)
        if spec is None:
            return self._http_error(400, "unknown provider")

        config = load_config()
        provider_config = getattr(config.providers, spec.name, None)
        if provider_config is None:
            return self._http_error(400, "unknown provider")

        changed = False
        if "api_key" in query or "apiKey" in query:
            api_key = self._query_first(query, "api_key")
            if api_key is None:
                api_key = self._query_first(query, "apiKey")
            api_key = (api_key or "").strip() or None
            if provider_config.api_key != api_key:
                provider_config.api_key = api_key
                changed = True

        if "api_base" in query or "apiBase" in query:
            api_base = self._query_first(query, "api_base")
            if api_base is None:
                api_base = self._query_first(query, "apiBase")
            api_base = (api_base or "").strip() or None
            if provider_config.api_base != api_base:
                provider_config.api_base = api_base
                changed = True

        if changed:
            save_config(config)
        # API key/base changes are picked up by the next provider snapshot refresh.
        return self._http_json_response(self._settings_payload(requires_restart=False))

    async def _handle_settings_web_search_update(self, request: WsRequest) -> Response:
        from mybot.config.loader import load_config, save_config

        query = self._parse_query(request.path)
        provider_name = (self._query_first(query, "provider") or "").strip().lower()
        provider_option = _WEB_SEARCH_PROVIDER_BY_NAME.get(provider_name)
        if provider_option is None:
            return self._http_error(400, "unknown web search provider")

        config = load_config()
        search_config = config.tools.web.search
        changed = False

        def set_value(attr: str, value: str | None) -> None:
            nonlocal changed
            if getattr(search_config, attr) != value:
                setattr(search_config, attr, value)
                changed = True

        credential = provider_option["credential"]
        if credential == "none":
            set_value("api_key", "")
            set_value("base_url", "")
        elif credential == "base_url":
            base_url = self._query_first(query, "base_url")
            if base_url is None:
                base_url = self._query_first(query, "baseUrl")
            base_url = base_url.strip() if base_url is not None else None
            if not base_url and search_config.url:
                base_url = search_config.url
            if not base_url:
                return self._http_error(400, "base_url is required")
            set_value("base_url", base_url)
            set_value("api_key", "")
        else:
            api_key = self._query_first(query, "api_key")
            if api_key is None:
                api_key = self._query_first(query, "apiKey")
            api_key = api_key.strip() if api_key is not None else None
            if not api_key and search_config.api_key:
                api_key = search_config.api_key
            if not api_key:
                return self._http_error(400, "api_key is required")
            set_value("api_key", api_key)
            set_value("base_url", "")

        if changed:
            save_config(config)
        return self._http_json_response(self._settings_payload(requires_restart=False))

    async def _handle_session_messages(self, request: WsRequest, key: str) -> Response:
        if self._session_manager is None:
            return self._http_error(503, "session manager unavailable")
        decoded_key = self._decode_api_key(key)
        if decoded_key is None:
            return self._http_error(400, "invalid session key")
        # The embedded webui only understands websocket-channel sessions. Keep
        # its read surface aligned with ``/api/sessions`` instead of letting a
        # caller probe arbitrary CLI / Slack / Lark history by handcrafted URL.
        if not self._is_webui_session_key(decoded_key):
            return self._http_error(404, "session not found")
        data = self._session_manager.read_session_file(decoded_key)
        if data is None:
            return self._http_error(404, "session not found")
        # Decorate persisted user messages with signed media URLs so the
        # client can render previews. The raw on-disk ``media`` paths are
        # stripped on the way out — they leak server filesystem layout and
        # the client never needs them once it has the signed fetch URL.
        self._augment_media_urls(data)
        return self._http_json_response(data)

    async def _handle_session_delete(self, request: WsRequest, key: str) -> Response:
        if self._session_manager is None:
            return self._http_error(503, "session manager unavailable")
        decoded_key = self._decode_api_key(key)
        if decoded_key is None:
            return self._http_error(400, "invalid session key")
        # Same boundary as ``_handle_session_messages``: the webui may only
        # mutate websocket sessions, and deletion really does unlink the local
        # JSONL, so keep the blast radius narrow and explicit.
        if not self._is_webui_session_key(decoded_key):
            return self._http_error(404, "session not found")
        deleted = self._session_manager.delete_session(decoded_key)
        return self._http_json_response({"deleted": bool(deleted)})

    def _handle_media_fetch(self, sig: str, payload: str) -> Response:
        """Serve a single media file previously signed via
        :meth:`_sign_media_path`. Validates the signature, decodes the
        payload to a relative path, and streams the file bytes with a
        long-lived immutable cache header (the URL already encodes the
        file identity, so caches can be aggressive)."""
        try:
            provided_mac = self._b64url_decode(sig)
        except (ValueError, binascii.Error):
            return self._http_error(401, "invalid signature")
        expected_mac = hmac.new(
            self._media_secret, payload.encode("ascii"), hashlib.sha256
        ).digest()[:16]
        if not hmac.compare_digest(expected_mac, provided_mac):
            return self._http_error(401, "invalid signature")
        try:
            rel_bytes = self._b64url_decode(payload)
            rel_str = rel_bytes.decode("utf-8")
        except (ValueError, binascii.Error, UnicodeDecodeError):
            return self._http_error(400, "invalid payload")
        # An attacker who somehow bypassed the HMAC check would still need
        # the resolved path to escape the media root; guard defensively.
        try:
            media_root = get_media_dir().resolve()
            candidate = (media_root / rel_str).resolve()
            candidate.relative_to(media_root)
        except (OSError, ValueError):
            return self._http_error(404, "not found")
        if not candidate.is_file():
            return self._http_error(404, "not found")
        try:
            body = candidate.read_bytes()
        except OSError:
            return self._http_error(500, "read error")
        mime, _ = mimetypes.guess_type(candidate.name)
        if mime not in _MEDIA_ALLOWED_MIMES:
            mime = "application/octet-stream"
        return self._http_response(
            body,
            content_type=mime,
            extra_headers=[
                ("Cache-Control", "private, max-age=31536000, immutable"),
                # Paired with the MIME whitelist above: prevents browsers from
                # MIME-sniffing an octet-stream fallback into executable HTML.
                ("X-Content-Type-Options", "nosniff"),
            ],
        )

    def _authorize_websocket_handshake(self, connection: Any, query: dict[str, list[str]]) -> Any:
        access_token = self._query_first(query, "access_token")
        refresh_token = self._query_first(query, "refresh_token")
        if not access_token or not refresh_token:
            return connection.respond(401, "Unauthorized")

        return None

    def _http_response(
        self,
        body: bytes,
        *,
        status: int = 200,
        content_type: str = "text/plain; charset=utf-8",
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> Response:
        headers = [
            ("Date", email.utils.formatdate(usegmt=True)),
            ("Connection", "close"),
            ("Content-Length", str(len(body))),
            ("Content-Type", content_type),
        ]
        if extra_headers:
            headers.extend(extra_headers)
        reason = http.HTTPStatus(status).phrase
        return Response(status, reason, Headers(headers), body)

    def _http_json_response(self, data: dict[str, Any], *, status: int = 200) -> Response:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers = Headers(
            [
                ("Date", email.utils.formatdate(usegmt=True)),
                ("Connection", "close"),
                ("Content-Length", str(len(body))),
                ("Content-Type", "application/json; charset=utf-8"),
            ]
        )
        reason = http.HTTPStatus(status).phrase
        return Response(status, reason, headers, body)


    def _http_error(self, status: int, message: str | None = None) -> Response:
        body = (message or http.HTTPStatus(status).phrase).encode("utf-8")
        return self._http_response(body, status=status)
    

    def _bearer_token(self, headers: Any) -> str | None:
        """Pull a Bearer token out of standard or query-style headers."""
        auth = headers.get("Authorization") or headers.get("authorization")
        if auth and auth.lower().startswith("bearer "):
            return auth[7:].strip() or None
        return None

    def _is_localhost(self, connection: ServerConnection) -> bool:
        """Return True if *connection* originated from the loopback interface."""
        addr = getattr(connection, "remote_address", None)
        if not addr:
            return False
        host = addr[0] if isinstance(addr, tuple) else addr
        if not isinstance(host, str):
            return False
        # ``::ffff:127.0.0.1`` is loopback in IPv6-mapped form.
        if host.startswith("::ffff:"):
            host = host[7:]
        return host in _LOCALHOSTS

    
    def _issue_route_secret_matches(self, headers: Any, configured_secret: str) -> bool:
        """Return True if the token-issue HTTP request carries credentials matching ``token_issue_secret``."""
        if not configured_secret:
            return True
        authorization = headers.get("Authorization") or headers.get("authorization")
        if authorization and authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
            return hmac.compare_digest(supplied, configured_secret)
        header_token = headers.get("X-mybot-Auth") or headers.get("x-kxbot-auth")
        if not header_token:
            return False
        return hmac.compare_digest(header_token.strip(), configured_secret)

    def _purge_expired_issued_tokens(self) -> None:
        now = time.monotonic()
        for token_key, expiry in list(self._issued_tokens.items()):
            if now > expiry:
                self._issued_tokens.pop(token_key, None)

    def _purge_expired_api_tokens(self) -> None:
        now = time.monotonic()
        for token_key, expiry in list(self._api_tokens.items()):
            if now > expiry:
                self._api_tokens.pop(token_key, None)

    def _expected_path(self) -> str:
        return self._normalize_config_path(self.config.path)


    def _read_webui_model_name(self) -> str | None:
        """Return the resolved startup model for readonly WebUI display."""
        try:
            from mybot.config.loader import load_config

            model = load_config().resolve_preset().model.strip()
            return model or None
        except Exception as e:
            logger.debug("webui bootstrap could not load model name: {}", e)
            return None


    def _parse_query(self, path_with_query: str) -> dict[str, list[str]]:
        return self._parse_request_path(path_with_query)[1]


    def _query_first(self, query: dict[str, list[str]], key: str) -> str | None:
        """Return the first value for *key*, or None."""
        values = query.get(key)
        return values[0] if values else None


    def _settings_payload(self, *, requires_restart: bool = False) -> dict[str, Any]:
        from mybot.config.loader import get_config_path, load_config
        from mybot.providers.registry import PROVIDERS, find_by_name

        config = load_config()
        defaults = config.agents.defaults
        provider_name = config.get_provider_name(defaults.model) or defaults.provider
        provider = config.get_provider(defaults.model)
        selected_provider = provider_name
        if defaults.provider != "auto":
            spec = find_by_name(defaults.provider)
            selected_provider = spec.name if spec else provider_name
        providers = []
        for spec in PROVIDERS:
            provider_config = getattr(config.providers, spec.name, None)
            if provider_config is None:
                continue
            providers.append(
                {
                    "name": spec.name,
                    "label": spec.label,
                    "configured": bool(provider_config.api_key),
                    "api_key_hint": self._mask_secret_hint(provider_config.api_key),
                    "api_base": provider_config.api_base,
                }
            )
        search_config = config.tools.web.search
        return {
            "agent": {
                "model": defaults.model,
                "provider": selected_provider,
                "resolved_provider": provider_name,
                "has_api_key": bool(provider and provider.api_key),
            },
            "providers": providers,
            "web_search": {
                "api_key_hint": self._mask_secret_hint(search_config.api_key),
                "base_url": search_config.url or None,
                "providers": list(_WEB_SEARCH_PROVIDER_OPTIONS),
            },
            "runtime": {
                "config_path": str(get_config_path().expanduser()),
            },
            "requires_restart": requires_restart,
        }


    def _mask_secret_hint(self, secret: str | None) -> str | None:
        if not secret:
            return None
        if len(secret) <= 8:
            return "••••"
        return f"{secret[:4]}••••{secret[-4:]}"


    def builtin_command_palette(self) -> list[dict[str, str]]:
        """Return structured command metadata for UI command palettes."""
        return [spec.as_dict() for spec in BUILTIN_COMMAND_SPECS]


    def _decode_api_key(self, raw_key: str) -> str | None:
        """Decode a percent-encoded API path segment, then validate the result."""
        key = unquote(raw_key)
        if _API_KEY_RE.match(key) is None:
            return None
        return key

    def _is_webui_session_key(self, key: str) -> bool:
        """Return True when *key* belongs to the webui's websocket-only surface."""
        return key.startswith("websocket:")


    def _augment_media_urls(self, payload: dict[str, Any]) -> None:
        """Mutate *payload* in place: each message's ``media`` path list is
        replaced by a parallel ``media_urls`` list of signed fetch URLs.

        Messages without media or with non-string path entries are left
        untouched. Paths that no longer live inside ``media_dir`` (e.g. the
        file was deleted, or the dir was relocated) are silently skipped;
        the client falls back to the historical-replay placeholder tile.
        """
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            media = msg.get("media")
            if not isinstance(media, list) or not media:
                continue
            urls: list[dict[str, str]] = []
            for entry in media:
                if not isinstance(entry, str) or not entry:
                    continue
                signed = self._sign_media_path(Path(entry))
                if signed is None:
                    continue
                urls.append({"url": signed, "name": Path(entry).name})
            if urls:
                msg["media_urls"] = urls
            # Always drop the raw paths from the wire payload.
            msg.pop("media", None)

    def _sign_media_path(self, abs_path: Path) -> str | None:
        """Return a ``/api/media/<sig>/<payload>`` URL for *abs_path*, or
        ``None`` when the path does not resolve inside the media root.

        The URL is self-authenticating: the signature binds the payload to
        this process's ``_media_secret``, so only paths we chose to sign can
        be fetched. The returned path is relative to the server origin; the
        client joins it against the existing webui base.
        """
        try:
            media_root = get_media_dir().resolve()
            rel = abs_path.resolve().relative_to(media_root)
        except (OSError, ValueError):
            return None
        payload = self._b64url_encode(rel.as_posix().encode("utf-8"))
        mac = hmac.new(
            self._media_secret, payload.encode("ascii"), hashlib.sha256
        ).digest()[:16]
        return f"/api/media/{self._b64url_encode(mac)}/{payload}"


    def _b64url_encode(self, data: bytes) -> str:
        """URL-safe base64 without padding — compact + friendly in URL paths."""
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


    def _b64url_decode(self, s: str) -> bytes:
        """Reverse of :func:`_b64url_encode`; caller handles ``ValueError``."""
        pad = "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s + pad)


    def _is_websocket_upgrade(self, request: WsRequest) -> bool:
        """Detect an actual WS upgrade; plain HTTP GETs to the same path should fall through."""
        upgrade = request.headers.get("Upgrade") or request.headers.get("upgrade")
        connection = request.headers.get("Connection") or request.headers.get("connection")
        if not upgrade or "websocket" not in upgrade.lower():
            return False
        if not connection or "upgrade" not in connection.lower():
            return False
        return True

    def _serve_static(self, request_path: str) -> Response | None:
        """Resolve *request_path* against the built SPA directory; SPA fallback to index.html."""
        assert self._static_dist_path is not None
        rel = request_path.lstrip("/")
        if not rel:
            rel = "index.html"
        # Reject path-traversal attempts and absolute targets.
        if ".." in rel.split("/") or rel.startswith("/"):
            return self._http_error(403, "Forbidden")
        candidate = (self._static_dist_path / rel).resolve()
        try:
            candidate.relative_to(self._static_dist_path)
        except ValueError:
            return self._http_error(403, "Forbidden")
        if not candidate.is_file():
            # SPA history-mode fallback: unknown routes serve index.html so the
            # client-side router can render them.
            index = self._static_dist_path / "index.html"
            if index.is_file():
                candidate = index
            else:
                return None
        try:
            body = candidate.read_bytes()
        except OSError as e:
            logger.warning("static: failed to read {}: {}", candidate, e)
            return self._http_error(500, "Internal Server Error")
        ctype, _ = mimetypes.guess_type(candidate.name)
        if ctype is None:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in {"application/javascript", "application/json"}:
            ctype = f"{ctype}; charset=utf-8"
        # Hash-named build assets are cache-friendly; index.html must stay fresh.
        if candidate.name == "index.html":
            cache = "no-cache"
        else:
            cache = "public, max-age=31536000, immutable"
        return self._http_response(
            body,
            status=200,
            content_type=ctype,
            extra_headers=[("Cache-Control", cache)],
        )

    def _take_issued_token_if_valid(self, token_value: str | None) -> bool:
        """Validate and consume one issued token (single use per connection attempt).

        Uses single-step pop to minimize the window between lookup and removal;
        safe under asyncio's single-threaded cooperative model.
        """
        if not token_value:
            return False
        self._purge_expired_issued_tokens()
        expiry = self._issued_tokens.pop(token_value, None)
        if expiry is None:
            return False
        if time.monotonic() > expiry:
            return False
        return True

    def _is_valid_chat_id(self, value: Any) -> bool:
        return isinstance(value, str) and _CHAT_ID_RE.match(value) is not None

    def _extract_data_url_mime(self, url: str) -> str | None:
        """Return the MIME type of a ``data:<mime>;base64,...`` URL, else ``None``."""
        if not isinstance(url, str):
            return None
        m = _DATA_URL_MIME_RE.match(url)
        if not m:
            return None
        return m.group(1).strip().lower() or None


    async def send_turn_end(self, chat_id: str) -> None:
        """Signal that the agent has fully finished processing the current turn."""
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        body: dict[str, Any] = {"event": "turn_end", "chat_id": chat_id}
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" turn_end ")


    async def _safe_send_to(self, connection: Any, raw: str, *, label: str = "") -> None:
        """Send a raw frame to one connection, cleaning up on ConnectionClosed."""
        try:
            await connection.send(raw)
        except ConnectionClosed:
            self._cleanup_connection(connection)
            logger.warning("connection gone{}", label)
        except Exception:
            logger.exception("send failed{}", label)
            raise

    async def send_session_updated(self, chat_id: str) -> None:
        """Notify clients that session metadata changed outside the main turn."""
        conns = list(self._subs.get(chat_id, ()))
        if not conns:
            return
        body: dict[str, Any] = {"event": "session_updated", "chat_id": chat_id}
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" session_updated ")

    async def send_runtime_model_updated(
        self,
        *,
        model_name: Any,
        model_preset: Any = None,
    ) -> None:
        """Broadcast runtime model changes to all active WebUI clients."""
        conns = list(self._conn_chats)
        if not conns or not isinstance(model_name, str) or not model_name.strip():
            return
        body: dict[str, Any] = {
            "event": "runtime_model_updated",
            "model_name": model_name.strip(),
        }
        if isinstance(model_preset, str) and model_preset.strip():
            body["model_preset"] = model_preset.strip()
        raw = json.dumps(body, ensure_ascii=False)
        for connection in conns:
            await self._safe_send_to(connection, raw, label=" runtime_model_updated ")

    def _sign_or_stage_media_path(self, path: Path) -> dict[str, str] | None:
        """Return a signed media URL payload for *path*.

        Persisted inbound media already lives under ``get_media_dir`` and can
        be signed directly. Outbound bot-generated files may live anywhere on
        disk; copy those into the websocket media bucket first so the browser
        can fetch them through the existing signed media route without
        exposing arbitrary filesystem paths.
        """
        signed = self._sign_media_path(path)
        if signed is not None:
            return {"url": signed, "name": path.name}
        try:
            if not path.is_file():
                return None
            media_dir = get_media_dir("websocket")
            safe_name = safe_filename(path.name) or "attachment"
            staged = media_dir / f"{uuid.uuid4().hex[:12]}-{safe_name}"
            shutil.copyfile(path, staged)
        except OSError as exc:
            logger.warning("failed to stage outbound media {}: {}", path, exc)
            return None
        signed = self._sign_media_path(staged)
        if signed is None:
            return None
        return {"url": signed, "name": path.name}
