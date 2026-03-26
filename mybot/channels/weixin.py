
import asyncio
import json
import base64
import os
import httpx
import qrcode

from pathlib import Path
from loguru import logger
from mybot.bus.message import OutboundMessage
from mybot.bus.queue import MessageBus
from mybot.channels.base import BaseChannel
from mybot.config.path import get_runtime_subdir
from mybot.config.schema import Config, WeixinConfig

MAX_QR_REFRESH_COUNT = 3

class WeixinChannel(BaseChannel):

    name="weixin"
    display_name = "WeChat"

    def __init__(self, config: Config, bus: MessageBus) -> None:
        super().__init__(config, bus)
        
        self.config: WeixinConfig = config.channels.weixin
        self._client: httpx.AsyncClient | None = None
        self._token: str = ""

    async def login(self) -> bool:
        """QR code login and save token."""
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
            return
        elif not self._load_state():
            if not await self._qr_login():
                logger.error("WeChat login failed. Run 'mybot channels login weixin' to authenticate.")
                self._running = False
                return

        return await super().start()

    async def send(self, msg: OutboundMessage) -> None:
        return await super().send(msg)

    async def stop(self) -> None:
        return await super().stop()


    def _get_account_file(self) -> Path:
        return get_runtime_subdir(self.name) / "account.json"
    
    def _load_state(self) -> bool:
        state_file = self._get_account_file()
        if not state_file.exists():
            return False

        try:
            data = json.loads(state_file.read_text())
            self._token = data.get("token", "")
            base_url = data.get("base_url", "")
            if base_url:
                self.config.base_url = base_url
            return bool(self._token)

        except Exception as e:
            logger.warning("Fail to load weixin state: {}", e)
            return False
    
    def _save_state(self) -> None:
        state_file = self._get_account_file()
        assert state_file.exists()

        try:
            data = {
                "token": self._token,
                "base_url": self.config.base_url,
            }
            state_file.write_text(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.warning("Fail to save WeChat state: {}", e)

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




