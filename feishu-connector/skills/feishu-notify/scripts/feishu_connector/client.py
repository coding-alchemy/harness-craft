import http.client
import json
import logging
import socket
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Mapping


LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())


@dataclass(frozen=True)
class JsonResponse:
    status: int
    payload: Mapping[str, object]


class NetworkFailure(Exception):
    pass


class ConnectorError(Exception):
    def __init__(self, category, message, retryable=False, code=None):
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.code = code


def _decode_response(raw):
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConnectorError("protocol", "Feishu returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise ConnectorError("protocol", "Feishu returned a non-object JSON response")
    return decoded


def post_json(url, headers, payload, timeout):
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request_headers = {"Content-Type": "application/json; charset=utf-8"}
    request_headers.update(headers)
    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return JsonResponse(response.status, _decode_response(response.read()))
    except urllib.error.HTTPError as exc:
        try:
            response_payload = _decode_response(exc.read())
        except (ConnectorError, http.client.HTTPException, OSError):
            return JsonResponse(exc.code, {})
        return JsonResponse(exc.code, response_payload)
    except (
        urllib.error.URLError,
        socket.timeout,
        TimeoutError,
        OSError,
        http.client.HTTPException,
    ) as exc:
        raise NetworkFailure("Feishu request failed") from exc


class FeishuClient:
    TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    MESSAGE_URL = (
        "https://open.feishu.cn/open-apis/im/v1/messages"
        "?receive_id_type=open_id"
    )
    RATE_LIMIT_CODES = {230020}

    def __init__(
        self,
        config,
        transport=post_json,
        sleep=time.sleep,
        timeout=10.0,
        max_retries=2,
        uuid_factory=uuid.uuid4,
    ):
        self.config = config
        self.transport = transport
        self.sleep = sleep
        self.timeout = timeout
        self.max_retries = max_retries
        self.uuid_factory = uuid_factory

    def _classify_response(self, response):
        code = response.payload.get("code")
        try:
            numeric_code = int(code) if code is not None else None
        except (TypeError, ValueError):
            numeric_code = None
        if response.status == 429 or numeric_code in self.RATE_LIMIT_CODES:
            raise ConnectorError(
                "rate_limit",
                "Feishu rate limit",
                retryable=True,
                code=numeric_code,
            )
        if response.status >= 500:
            raise ConnectorError(
                "server",
                "Feishu server error (HTTP %d)" % response.status,
                retryable=True,
                code=numeric_code,
            )
        if not 200 <= response.status < 300:
            raise ConnectorError(
                "api",
                "Feishu request rejected (HTTP %d)" % response.status,
                code=numeric_code,
            )
        if numeric_code != 0:
            raise ConnectorError(
                "api",
                "Feishu business error",
                code=numeric_code,
            )
        return response.payload

    def _attempt(self, operation):
        for attempt in range(self.max_retries + 1):
            try:
                return operation()
            except NetworkFailure as exc:
                error = ConnectorError(
                    "network",
                    "Feishu network request failed",
                    retryable=True,
                )
                error.__cause__ = exc
            except ConnectorError as exc:
                error = exc
            if not error.retryable:
                raise error
            if attempt == self.max_retries:
                raise ConnectorError(
                    error.category,
                    "%s after %d attempts" % (str(error), attempt + 1),
                    retryable=True,
                    code=error.code,
                ) from error
            LOGGER.warning(
                "Feishu retry [%s] attempt %d/%d",
                error.category,
                attempt + 1,
                self.max_retries + 1,
            )
            self.sleep(min(2.0 ** attempt, 4.0))
        raise AssertionError("unreachable")

    def _post(self, url, headers, payload):
        response = self.transport(url, headers, payload, self.timeout)
        return self._classify_response(response)

    def fetch_tenant_access_token(self):
        payload = self._attempt(
            lambda: self._post(
                self.TOKEN_URL,
                {},
                {
                    "app_id": self.config.app_id,
                    "app_secret": self.config.app_secret,
                },
            )
        )
        token = payload.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise ConnectorError(
                "auth",
                "Feishu authentication response missing tenant_access_token",
            )
        return token

    def _send_message(self, msg_type, content):
        token = self.fetch_tenant_access_token()
        payload = {
            "receive_id": self.config.receive_open_id,
            "msg_type": msg_type,
            "content": json.dumps(
                content,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "uuid": str(self.uuid_factory()),
        }
        return self._attempt(
            lambda: self._post(
                self.MESSAGE_URL,
                {"Authorization": "Bearer %s" % token},
                payload,
            )
        )

    def send_text(self, message):
        return self._send_message("text", {"text": message})

    def send_card(self, card):
        return self._send_message("interactive", card)
