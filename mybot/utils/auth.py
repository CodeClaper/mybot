import base64
from typing import Any
import httpx
from gmssl import sm3
from loguru import logger
from mybot.config.schema import Config, ServiceConfig

class AuthManager:
    """Handle the auth."""
    def __init__(self, config: Config) -> None:
        self._serivce: ServiceConfig = config.service
    

    async def login(self, username: str, password: str) -> dict[str, Any] | None:
        """Auth login and try to get token. """
        if not username or not password:
            raise Exception("Error: username and password must support.")
        try:
            form_data = {"username": (None, username), "password": (None, self._get_salt_encrypted(password)), "grant_type": (None, "password"), "userTypeCode": (None, str(10))}
            async with httpx.AsyncClient(verify=False) as client:
                r = await client.post(
                    self._get_login_url(),
                    files=form_data,
                    headers={"Authorization": self._get_request_basic()},
                    timeout=100,
                )
                r.raise_for_status()
                
            body = r.json()
            success: bool = body.get("success") or True
            logger.debug(f"body: {body}")
            if not success:
                raise Exception(f"Error: {body.get('msg') or 'UnAuthorization'}")
            return body
        except httpx.ProtocolError as e:
            logger.error(f"Web search proxy error: {e}")
        except Exception as e:
            logger.error(f"Web search error: {e}")

    async def check_access_token(self, access_token: str) -> bool:
        """Check the access token"""
        if not access_token:
            raise Exception("Error: not refresh_token, please login frist.")

        try:
            async with httpx.AsyncClient(verify=False) as client:
                r = await client.get(
                    self._get_user_me_url(),
                    headers={"Authorization": self._get_request_bearer(access_token=access_token)},
                    timeout=100
                )
                r.raise_for_status()

            body = r.json()
            if not body:
                return False
            authenticated = body.get("authenticated") or False
            return authenticated
        except httpx.ProtocolError as e:
            logger.error(f"Web search proxy error: {e}")
            return False
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return False


    async def refresh_token(self, refresh_token: str) -> dict[str, Any] | None:
        """Refresh token"""
        if not refresh_token:
            raise Exception("Error: not refresh_token, please login frist.")

        try:
            async with httpx.AsyncClient(verify=False) as client:
                r = await client.post(
                    self._get_refresh_url(refresh_token=refresh_token),
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": self._get_request_basic()},
                    timeout=100
                )
                r.raise_for_status()

            body = r.json()
            success: bool = body.get("success") or True
            logger.debug(f"body: {body}")
            if not success:
                raise Exception(f"Error: {body.get('msg') or 'UnAuthorization'}")
            return body
        except httpx.ProtocolError as e:
            logger.error(f"Web search proxy error: {e}")
        except Exception as e:
            logger.error(f"Web search error: {e}")
    
    async def get_about_me(self, access_token) -> dict[str, Any] | None:
        """Get about me."""
        if not access_token:
            raise Exception("Error: not refresh_token, please login frist.")

        try:
            async with httpx.AsyncClient(verify=False) as client:
                r = await client.get(
                    self._get_user_me_url(),
                    headers={"Authorization": self._get_request_bearer(access_token=access_token)},
                    timeout=100
                )
                r.raise_for_status()

            body = r.json()
            return body
        except httpx.ProtocolError as e:
            logger.error(f"Web search proxy error: {e}")
        except Exception as e:
            logger.error(f"Web search error: {e}")


    async def get_roles(self, user_id: str, access_token: str) -> Any:
        """Get bsp roles by user id."""
        if not user_id:
            raise Exception("Error: not user id, please login frist.")

        try:
            async with httpx.AsyncClient(verify=False) as client:
                r = await client.get(
                    self._get_user_roles_url(user_id),
                    headers={"Authorization": self._get_request_bearer(access_token=access_token)},
                    timeout=100
                )
                r.raise_for_status()

            body = r.json()
            logger.debug(f"body: {body}")
            return body
        except httpx.ProtocolError as e:
            logger.error(f"Web search proxy error: {e}")
        except Exception as e:
            logger.error(f"Web search error: {e}")


    def _get_login_url(self) -> str:
        return f"{self._get_request_protocol()}://{self._serivce.ip}:7082/do-api/bsp-api/loushang/oauth/token"

    def _get_refresh_url(self, refresh_token) -> str:
        return f"{self._get_request_protocol()}://{self._serivce.ip}:7082/do-api/bsp-api/loushang/oauth/token?grant_type=refresh_token&refresh_token={refresh_token}"

    def _get_user_me_url(self) -> str:
        return f"{self._get_request_protocol()}://{self._serivce.ip}:7082/do-api/bsp-api/loushang/user/me"

    def _get_user_roles_url(self, user_id: str) -> str:
        return f"{self._get_request_protocol()}://{self._serivce.ip}:7082/do-api/bsp-api/bsp/users/{user_id}/roles"

    def _get_request_basic(self) -> str:
        encoded = base64.b64encode(self._serivce.md5solot.encode('utf-8')).decode('utf-8')
        return f"Basic {encoded}"

    def _get_request_bearer(self, access_token: str) -> str:
        if access_token.lower().startswith("bearer"):
            return access_token
        return f"Bearer {access_token}"

    def _get_request_protocol(self) -> str:
        return self._serivce.protol if self._serivce.protol else "http"

    def _get_salt_encrypted(self, password) -> str:
        raw_string = password + "{" + self._serivce.salt + "}"
        return sm3.sm3_hash(bytearray(raw_string.encode("utf-8")))

