from __future__ import annotations

import json
import mimetypes
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from socket import timeout as SocketTimeout
from typing import Any
from urllib import error, parse, request

from fishmindos.config import get_config_value


class NavAPIError(RuntimeError):
    """Raised when nav_api cannot return a usable result."""


@dataclass(slots=True)
class NavAPIResult:
    status_code: int
    url: str
    content_type: str
    headers: dict[str, str]
    data: Any


@dataclass
class NavAPIClient:
    base_url: str = "http://127.0.0.1:9002"
    timeout_sec: int = 15
    token: str | None = None
    username: str | None = None
    password: str | None = None

    @classmethod
    def from_env(cls) -> NavAPIClient:
        base_url = cls._resolve_base_url().rstrip("/")
        timeout_raw = get_config_value("nav", "timeout_sec", "FISHMINDOS_NAV_TIMEOUT_SEC", default="15")
        try:
            timeout_sec = max(1, int(timeout_raw))
        except ValueError:
            timeout_sec = 15

        token = (
            get_config_value("nav", "auth_token", "FISHMINDOS_NAV_AUTH_TOKEN")
            or get_config_value("nav", "token", "FISHMINDOS_NAV_TOKEN")
        )
        username = get_config_value("nav", "username", "FISHMINDOS_NAV_USERNAME")
        password = get_config_value("nav", "password", "FISHMINDOS_NAV_PASSWORD")
        return cls(
            base_url=base_url,
            timeout_sec=timeout_sec,
            token=token,
            username=username,
            password=password,
        )

    @classmethod
    def _resolve_base_url(cls) -> str:
        direct_base_url = get_config_value("nav", "base_url", "FISHMINDOS_NAV_BASE_URL", default="")
        host = get_config_value("nav", "host", "FISHMINDOS_NAV_HOST", default="")
        port = get_config_value("nav", "port", "FISHMINDOS_NAV_PORT", default="")
        scheme = str(get_config_value("nav", "scheme", "FISHMINDOS_NAV_SCHEME", default="http")).strip() or "http"

        if host or port:
            normalized_host = str(host).strip() or "127.0.0.1"
            normalized_port = cls._normalize_port(port)
            if normalized_port:
                return f"{scheme}://{normalized_host}:{normalized_port}"
            return f"{scheme}://{normalized_host}"

        if direct_base_url:
            return str(direct_base_url).strip()

        return "http://127.0.0.1:9002"

    @staticmethod
    def _normalize_port(raw_port: Any) -> str:
        if raw_port in (None, ""):
            return ""
        try:
            port = int(raw_port)
        except (TypeError, ValueError):
            raise NavAPIError(f"Invalid nav port: {raw_port}") from None
        if port <= 0:
            raise NavAPIError(f"Invalid nav port: {raw_port}")
        return str(port)

    def login(self, username: str | None = None, password: str | None = None) -> NavAPIResult:
        actual_username = username or self.username
        actual_password = password or self.password
        if not actual_username or not actual_password:
            raise NavAPIError("Nav API login requires username and password.")

        result = self.request_json(
            "POST",
            "/api/nav/login",
            json_body={"username": actual_username, "password": actual_password},
            capture_token=True,
        )
        self.username = actual_username
        self.password = actual_password
        return result

    def ensure_token(self) -> str | None:
        if self.token:
            return self.token
        if self.username and self.password:
            self.login()
            return self.token
        return None

    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        use_auth: bool = False,
        capture_token: bool = False,
        timeout_sec: int | float | None = None,
    ) -> NavAPIResult:
        headers: dict[str, str] = {"Accept": "application/json"}
        data = None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")

        result = self._request(
            method,
            path,
            query=query,
            data=data,
            headers=headers,
            use_auth=use_auth,
            timeout_sec=timeout_sec,
        )
        payload = self._parse_json_payload(result.data)
        parsed_result = NavAPIResult(
            status_code=result.status_code,
            url=result.url,
            content_type=result.content_type,
            headers=result.headers,
            data=payload,
        )
        if capture_token:
            self._capture_token(parsed_result)
        return parsed_result

    def request_text(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        use_auth: bool = False,
        timeout_sec: int | float | None = None,
    ) -> NavAPIResult:
        headers: dict[str, str] = {"Accept": "text/plain, text/event-stream, text/html, application/json"}
        data = None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        result = self._request(
            method,
            path,
            query=query,
            data=data,
            headers=headers,
            use_auth=use_auth,
            timeout_sec=timeout_sec,
        )
        text = result.data.decode("utf-8", errors="replace")
        return NavAPIResult(
            status_code=result.status_code,
            url=result.url,
            content_type=result.content_type,
            headers=result.headers,
            data=text,
        )

    def request_binary(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        use_auth: bool = False,
        timeout_sec: int | float | None = None,
    ) -> NavAPIResult:
        return self._request(
            method,
            path,
            query=query,
            headers={"Accept": "*/*"},
            use_auth=use_auth,
            timeout_sec=timeout_sec,
        )

    def upload_file(
        self,
        method: str,
        path: str,
        *,
        files: dict[str, str],
        fields: dict[str, Any] | None = None,
        use_auth: bool = False,
        timeout_sec: int | float | None = None,
    ) -> NavAPIResult:
        body, content_type = self._encode_multipart(fields=fields or {}, files=files)
        result = self._request(
            method,
            path,
            data=body,
            headers={"Content-Type": content_type, "Accept": "application/json"},
            use_auth=use_auth,
            timeout_sec=timeout_sec,
        )
        payload = self._parse_json_payload(result.data)
        return NavAPIResult(
            status_code=result.status_code,
            url=result.url,
            content_type=result.content_type,
            headers=result.headers,
            data=payload,
        )

    def build_url(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = f"{self.base_url}{path}"
        if not query:
            return url
        encoded = parse.urlencode(self._flatten_query(query), doseq=True)
        return f"{url}?{encoded}" if encoded else url

    def save_binary(self, payload: bytes, save_to: str) -> str:
        target = Path(save_to)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return str(target)

    def save_text(self, payload: str, save_to: str) -> str:
        target = Path(save_to)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
        return str(target)

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        use_auth: bool = False,
        timeout_sec: int | float | None = None,
    ) -> NavAPIResult:
        url = self.build_url(path, query=query)
        resolved_timeout = float(timeout_sec if timeout_sec not in (None, "") else self.timeout_sec)
        request_headers = dict(headers or {})
        if use_auth:
            token = self.ensure_token()
            if not token:
                raise NavAPIError("Nav API requires auth, but no token is available.")
            request_headers["Authorization"] = f"Bearer {token}"

        req = request.Request(url, data=data, headers=request_headers, method=method.upper())
        try:
            with request.urlopen(req, timeout=resolved_timeout) as resp:
                payload = resp.read()
                status_code = getattr(resp, "status", 200)
                response_headers = {key: value for key, value in resp.headers.items()}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise NavAPIError(f"Nav API HTTP {exc.code}: {detail}") from exc
        except (TimeoutError, SocketTimeout) as exc:
            raise NavAPIError(f"Nav API request timed out after {resolved_timeout:g}s: {path}") from exc
        except error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, SocketTimeout)):
                raise NavAPIError(f"Nav API request timed out after {resolved_timeout:g}s: {path}") from exc
            raise NavAPIError(f"Nav API unavailable: {exc.reason}") from exc

        return NavAPIResult(
            status_code=status_code,
            url=url,
            content_type=response_headers.get("Content-Type", ""),
            headers=response_headers,
            data=payload,
        )

    @staticmethod
    def _parse_json_payload(payload: bytes) -> Any:
        if payload in (b"", None):
            return {}
        try:
            return json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise NavAPIError("Nav API returned invalid JSON.") from exc

    def _capture_token(self, result: NavAPIResult) -> None:
        payload = result.data
        if isinstance(payload, dict):
            token = payload.get("token")
            if isinstance(token, str) and token:
                self.token = token
                return

        cookie = result.headers.get("Set-Cookie", "")
        match = re.search(r"auth_token=([^;]+)", cookie)
        if match:
            self.token = match.group(1)

    @staticmethod
    def _flatten_query(query: dict[str, Any]) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for key, value in query.items():
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                for item in value:
                    pairs.append((key, NavAPIClient._stringify_value(item)))
                continue
            pairs.append((key, NavAPIClient._stringify_value(value)))
        return pairs

    @staticmethod
    def _stringify_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    @staticmethod
    def _encode_multipart(fields: dict[str, Any], files: dict[str, str]) -> tuple[bytes, str]:
        boundary = f"----FishMindOS{uuid.uuid4().hex}"
        body = bytearray()

        for name, value in fields.items():
            if value is None:
                continue
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            body.extend(f"{value}\r\n".encode("utf-8"))

        for field_name, file_path in files.items():
            path = Path(file_path)
            if not path.exists():
                raise NavAPIError(f"File not found: {file_path}")
            content = path.read_bytes()
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(
                f'Content-Disposition: form-data; name="{field_name}"; filename="{path.name}"\r\n'.encode("utf-8")
            )
            body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
            body.extend(content)
            body.extend(b"\r\n")

        body.extend(f"--{boundary}--\r\n".encode("utf-8"))
        return bytes(body), f"multipart/form-data; boundary={boundary}"
