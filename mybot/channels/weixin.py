
import json
import base64
import os
import httpx

from pathlib import Path
from loguru import logger
from mybot.bus.queue import MessageBus
from mybot.channels.base import BaseChannel
from mybot.config.path import get_runtime_subdir
from mybot.config.schema import Config, WeixinConfig

class WeixinChannel(BaseChannel):

    name="weixin"
    display_name = "WeChat"

    def __init__(self, config: Config, bus: MessageBus) -> None:
        super().__init__(config, bus)
        
        self.config: WeixinConfig = config.channels.weixin
        self._client: httpx.AsyncClient | None = None
        self._token: str = ""


    async def start(self) -> None:
        self._running = True
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.config.poll_timeout, connect=30), follow_redirects=True)
        
        if not self._load_state():
            return

        return await super().start()

    def _get_account_file(self) -> Path:
        return get_runtime_subdir(self.name) / "account.json"
    
    def _load_state(self) -> bool:
        state_file = self._get_account_file()
        if not state_file.exists():
            return False

        try:
            data = json.loads(state_file.read_text())
            self._token = data.get("token", "")
            return bool(self._token)

        except Exception as e:
            logger.warning("Fail to load weixin state: {}", e)
            return False

    def _random_wechat_uin(self) -> str:
        """X-WECHAT-UIN: random uint32 → decimal string → base64.

        Matches the reference plugin's ``randomWechatUin()`` in api.ts.
        Generated fresh for **every** request (same as reference).
        """
        uint32 = int.from_bytes(os.urandom(4), "big")
        return base64.b64encode(str(uint32).encode()).decode()

    async def _make_headers(self, auth: bool) -> dict[str, str]:
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
        resp = await self._client.get(url, params=params, headers=hrds)
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
                       






