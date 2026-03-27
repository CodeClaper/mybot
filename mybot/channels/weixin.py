from logging import error
import uuid
import asyncio
import time
import json
import base64
import os
from typing import Any, OrderedDict
import httpx
import qrcode

from pathlib import Path
from loguru import logger
from mybot.bus.message import OutboundMessage
from mybot.bus.queue import MessageBus
from mybot.channels.base import BaseChannel
from mybot.config.path import ensure_file, get_runtime_subdir
from mybot.config.schema import Config, WeixinConfig
from mybot.utils.helper import split_message

MAX_QR_REFRESH_COUNT = 3
WEIXIN_CHANNEL_VERSION = "1.0.3"
BASE_INFO: dict[str, str] = {"channel_version": WEIXIN_CHANNEL_VERSION}

# MessageItemType
ITEM_TEXT = 1
ITEM_IMAGE = 2
ITEM_VOICE = 3
ITEM_FILE = 4
ITEM_VIDEO = 5

# MessageType  (1 = inbound from user, 2 = outbound from bot)
MESSAGE_TYPE_USER = 1
MESSAGE_TYPE_BOT = 2
# MessageState
MESSAGE_STATE_FINISH = 2

# Session-expired error code
ERRCODE_SESSION_EXPIRED = -14
SESSION_PAUSE_DURATION_S = 60 * 60
DEFAULT_LONG_POLL_TIMEOUT_S = 35

MAX_FAILURES = 3

WEIXIN_MAX_MESSAGE_LEN = 4000

class WeixinChannel(BaseChannel):

    name="weixin"
    display_name = "WeChat"

    def __init__(self, config: Config, bus: MessageBus) -> None:
        super().__init__(config, bus)
        
        self.config: WeixinConfig = config.channels.weixin
        self._client: httpx.AsyncClient | None = None
        self._get_updates_buf: str = ""
        self._token: str = ""
        self._next_poll_timeout_s: int = DEFAULT_LONG_POLL_TIMEOUT_S
        self._session_pause: float = 0.0
        self._processed_ids: OrderedDict[str, None] = OrderedDict()

    #--------------------------------------------------------------------------
    # Basic implement method for BaseChannel.
    #--------------------------------------------------------------------------
    async def login(self, force: bool = False) -> bool:
        """QR code login and save token."""

        if force:
            self._token = ""
            self._get_updates_buf = ""
            state_file = self._get_account_file()
            if state_file.exists():
                state_file.unlink()

        if self._token or self._load_state():
            return True

        self._running = True
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.config.poll_timeout, connect=30), follow_redirects=True)
        try:
            return await self._qr_login()
        finally:
            self._running = False
            if self._client:
                await self._client.aclose()
                self._client = None

    async def start(self) -> None:
        self._running = True
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.config.poll_timeout, connect=30), follow_redirects=True)
        
        if not self._load_state():
            if not await self._qr_login():
                logger.error("WeChat login failed. Run 'mybot channels login weixin' to authenticate.")
                self._running = False
                return

        logger.info("WeChat channel starting with long-poll...")
        failures = 0
        while self._running:
            try:
                await self._poll_once()
            except httpx.TimeoutException:
                continue
            except Exception as e:
                if not self._running:
                    break
                logger.error("WeChat poll error ({}/{}): {}", failures, MAX_FAILURES, e)
    
    async def send(self, msg: OutboundMessage) -> None:
        """
        Send messsage to weixin channel.
        Args:
            msg: message to send.
        """
        if not self._client:
            logger.warning("WeChat client not initialized or not authenticated.")
            return

        try:
            self._assert_session_active()
        except RuntimeError as e:
            logger.warning("WeChat send blocked: {}", e)
            return

        content = msg.content.strip()
        if not content:
            return
        try:
            chunks = split_message(content, WEIXIN_MAX_MESSAGE_LEN)
            for chunk in chunks:
                await self._send_text(msg.chat_id, chunk)
        except Exception as e:
            logger.error("Error sending WeChat message: {}", e)

    async def stop(self) -> None:
        self._running = False
        if self._client:
            await self._client.aclose()
            self._client = None
        self._save_state()
        logger.info("WeChat channel stopped.")


    async def _send_text(self, to_user_id: str, text: str) -> None:
        """Send a text message to WeChat."""

        client_id = f"mybot-{uuid.uuid4().hex[:12]}"
        item_list: list[dict] = []
        if text:
            item_list.append({"type": ITEM_TEXT, "text_item": {"text": text}})
        
        weixin_msg: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": client_id,
            "message_type": MESSAGE_TYPE_BOT,
            "message_state": MESSAGE_STATE_FINISH
        }
        if item_list:
            weixin_msg["item_list"] = item_list
        
        body: dict[str, Any] = {
            "msg": weixin_msg,
            "base_info": BASE_INFO
        }

        data = await self._api_post("ilink/bot/sendmessage", body)
        errcode = data.get("errcode", 0)
        if errcode and errcode != 0:
            logger.warning("WeChat send error (code {}): {}", errcode, data.get("errmsg", ""))

    def _assert_session_active(self) -> None:
        remaining = self._session_pause_remaining_s()
        if remaining > 0:
            remaining_min = max((remaining + 59) // 60, 1)
            raise RuntimeError(
                f"WeChat session paused, {remaining_min} min remaining."
            )

    #--------------------------------------------------------------------
    # The state manager
    #--------------------------------------------------------------------

    def _get_account_file(self) -> Path:
        return get_runtime_subdir(self.name) / "account.json"
    
    def _load_state(self) -> bool:
        state_file = self._get_account_file()
        if not state_file.exists():
            return False

        try:
            data = json.loads(state_file.read_text())
            self._token = data.get("token", "")
            self._get_updates_buf = data.get("get_update_buf", "")
            base_url = data.get("base_url", "")
            if base_url:
                self.config.base_url = base_url
            return bool(self._token)

        except Exception as e:
            logger.warning("Fail to load weixin state: {}", e)
            return False
    
    def _save_state(self) -> None:
        state_file = self._get_account_file()
        ensure_file(state_file)

        try:
            data = {
                "token": self._token,
                "get_update_buf": self._get_updates_buf,
                "base_url": self.config.base_url,
            }
            state_file.write_text(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.warning("Fail to save WeChat state: {}", e)

    #-----------------------------------------------------------------------
    # WeChat API Fetch
    #-----------------------------------------------------------------------
    def _random_wechat_uin(self) -> str:
        """X-WECHAT-UIN: random uint32 → decimal string → base64.

        Matches the reference plugin's ``randomWechatUin()`` in api.ts.
        Generated fresh for **every** request (same as reference).
        """
        uint32 = int.from_bytes(os.urandom(4), "big")
        return base64.b64encode(str(uint32).encode()).decode()

    def _make_headers(self, auth: bool) -> dict[str, str]:
        headers: dict[str, str] = {
            "X-WECHAT-UIN": self._random_wechat_uin(),
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
        }

        if auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        return headers
    
    async def _api_get(
        self,
        endpoint: str,
        params: dict | None = None,
        auth: bool = True,
        extra_headers: dict[str, str] | None = None
    ) -> dict:
        assert self._client is not None
        url = f"{self.config.base_url}/{endpoint}"
        hrds = self._make_headers(auth=auth)
        if extra_headers:
            hrds.update(extra_headers)
        resp = await self._client.get(url=url, params=params, headers=hrds)
        resp.raise_for_status()
        return resp.json()

    async def _api_post(
        self,
        endpoint: str,
        body: dict | None = None,
        auth: bool = True,
        extra_headers: dict[str, str] | None = None
    ) -> dict:
        assert self._client is not None
        url = f"{self.config.base_url}/{endpoint}"
        payload = body or {}
        if "base_info" not in payload:
            payload["base_info"] = BASE_INFO
        hrds = self._make_headers(auth=auth)
        if extra_headers:
            hrds.update(extra_headers)
        resp = await self._client.post(url, json=payload, headers=hrds)
        resp.raise_for_status()
        return resp.json()


    async def _fetch_qr_code(self) -> tuple[str, str]:
        """Fetch a fresh QR code, returns (qrcode_id, scan_url)"""
        data = await self._api_get(
            "ilink/bot/get_bot_qrcode",
            params={"bot_type": 3},
            auth=False
        )

        qrcode_img_content = data.get("qrcode_img_content", "")
        qrcode_id = data.get("qrcode", "")
        if not qrcode_id:
            raise RuntimeError(f"Failed to get QR code from WeChat API: {data}")
        return qrcode_id, (qrcode_img_content or qrcode_id)

    async def _qr_login(self) -> bool:
        """QR code login, return True if success."""
        try:
            logger.info("Start WeChat QR code login...")
            qrcode_id, scan_url = await self._fetch_qr_code()
            self._print_qr_code(scan_url)
            
            refresh_count = 0
            logger.info("Waiting for QR code scan...")
            while self._running:
                try:
                    status_data = await self._api_get(
                        "ilink/bot/get_qrcode_status",
                        params={"qrcode": qrcode_id},
                        auth=False,
                        extra_headers={"iLink-App-ClientVersion": "1"}
                    )
                except httpx.TimeoutException:
                    continue

                status = status_data.get("status", "")
                if status == "confirmed":
                    token = status_data.get("bot_token", "")
                    bot_id = status_data.get("ilink_bot_id", "")
                    base_url = status_data.get("baseurl", "")
                    user_id = status_data.get("ilink_user_id", "")
                    if token:
                        self._token = token
                        if base_url:
                            self.config.base_url = base_url
                        self._save_state()
                        logger.info("Wechat login successful! bot_id={}, user_id={}", bot_id, user_id)
                        return True
                    else:
                        logger.error("Login confirmed but not bot_token in reponse")
                        return False
                elif status == "scanned":
                    logger.info("QR code scanned, waiting for comfirmation...")
                elif status == "expired":
                    refresh_count += 1
                    if refresh_count > MAX_QR_REFRESH_COUNT:
                        logger.error("QR code expired too many times: {}/{}", refresh_count - 1, MAX_QR_REFRESH_COUNT)
                        return False
                    logger.warning("QR code expired, refreshing: {}/{}", refresh_count, MAX_QR_REFRESH_COUNT);
                    qrcode_id, scan_url = await self._fetch_qr_code()
                    continue
                
                await asyncio.sleep(1)
        except Exception as e:
            logger.error("WeChat QR login failed: {}", e)
        return False

    @staticmethod
    def _print_qr_code(url: str) -> None:
        try:
            qr = qrcode.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except ImportError:
            logger.info("QR code URL (install 'qrcode' for terminal display): {}", url)
            print(f"\nLogin URL: {url}\n")

    #--------------------------------------------------------------------------------------
    #Polling (matches monitor.ts monitorWeixinProvider)
    #--------------------------------------------------------------------------------------
    def _pause_session(self, duration_s: int = SESSION_PAUSE_DURATION_S) -> None:
        self._session_pause = time.time() + duration_s

    def _session_pause_remaining_s(self) -> int:
        remaining = int(self._session_pause - time.time())
        if remaining <= 0:
            self._session_pause = 0.0
            return 0
        return remaining
    
    async def _poll_once(self) -> None:
        remaining = self._session_pause_remaining_s()
        if remaining > 0:
            logger.warning("WeChat session paused, waiting {} min before next poll.", max((remaining + 59) // 60, 1))
            await asyncio.sleep(remaining)
            return

        body: dict[str, Any] = {
            "get_update_buf": self._get_updates_buf,
            "base_info": BASE_INFO
        }

        assert self._client is not None
        self._client.timeout = httpx.Timeout(self._next_poll_timeout_s + 10, connect=30)

        data = await self._api_post("ilink/bot/getupdates", body=body)
        ret = data.get("ret", 0)
        errcode = data.get("errcode", 0)
        errmsg = data.get("errmsgf", "")
        is_err = (ret is not None and ret != 0) or (errcode is not None and errcode != 0)
        if is_err:
            if errcode == ERRCODE_SESSION_EXPIRED or ret == ERRCODE_SESSION_EXPIRED:
                self._pause_session()
                remaining = self._session_pause_remaining_s()
                logger.warning("WeChat session expired (errcode: {]}), pause {} min", errcode, max((remaining + 59) // 60, 1))
                return
            raise RuntimeError(f"getupdates failed: ret={ret} errcode={errcode} errmsg={errmsg}")

        new_buf = data.get("get_update_buf", "")
        if new_buf:
            self._get_updates_buf = new_buf
            self._save_state()

        msgs:list[dict] = data.get("msgs", []) or []
        for msg in msgs:
            try:
                await self._process_message(msg)
            except Exception as e:
                logger.error("Error processiong WeChat message: {}", e)
    
    #-------------------------------------------------------------------------------
    # Inbound messge processing.
    #-------------------------------------------------------------------------------
    
    async def _process_message(self, msg: dict) -> None:
        """ Process a single Weixin Message from getupdates. """
        # Skip bot's message.
        if msg.get("message_type") == MESSAGE_TYPE_BOT:
            return
        
        msg_id = str(msg.get("message_id", "") or msg.get("seq", ""))
        if not msg_id:
            msg_id = f"{msg.get('from_user_id', '')}_{msg.get('create_time_ms', '')}"
        if msg_id in self._processed_ids:
            return
        self._processed_ids[msg_id] = None
        while len(self._processed_ids) > 1000:
            self._processed_ids.popitem(last=False)
        
        from_user_id = msg.get("from_user_id", "") or ""
        if not from_user_id:
            return

        item_list: list[dict] = msg.get("item_list") or []
        content_parts: list[str] = []
        media_paths: list[str] = []

        for item in item_list:
            item_type = item.get("type", 0)
            if item_type == ITEM_TEXT:
                text = (item.get("text_item") or {}).get("text", "")
                if text:
                    ref = item.get("ref_msg")
                    if ref:
                        ref_item = ref.get("message_item")
                        if ref_item and ref_item.get("type", 0) in (ITEM_IMAGE, ITEM_VOICE, ITEM_FILE, ITEM_VIDEO):
                            content_parts.append(text)
                        else:
                            parts: list[str] = []
                            if ref.get("title"):
                                parts.append(ref["title"])
                            if ref_item:
                                ref_text = (ref_item.get("text_item") or {}).get("text", "")
                                if ref_text:
                                    parts.append(ref_text)
                            if parts:
                                content_parts.append(f"[引用: {'|'.join(parts)}]\n{text}")
                    else:
                        content_parts.append(text)

        content = "\n".join(content_parts)
        if not content:
            return

        logger.info(
            "WeChat inbound: from={} items={} bodylen={}",
            from_user_id,
            ",".join(str(i.get("type", 0)) for i in item_list),
            len(content)
        )

        await self._handle_message(
            sender_id=from_user_id,
            chat_id=from_user_id,
            content=content,
            media=media_paths or None,
            metadata={"message_id": msg_id}
        )


