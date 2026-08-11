import io
import http.client
import json
import sys
import urllib.error
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

CONNECTOR_ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = CONNECTOR_ROOT / "skills" / "feishu-notify" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from feishu_connector.client import (  # noqa: E402
    ConnectorError,
    FeishuClient,
    JsonResponse,
    NetworkFailure,
    post_json,
)


def make_config():
    return SimpleNamespace(
        app_id="cli_test",
        app_secret="secret-value",
        receive_open_id="ou_target1234",
        auto_notify=False,
    )


class FakeTransport:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, dict(headers), dict(payload), timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeUrlopenResponse:
    def __init__(self, status, body):
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def close(self):
        pass

    def read(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class PostJsonTests(unittest.TestCase):
    def test_uses_post_json_utf8_request(self):
        response = FakeUrlopenResponse(200, b'{"code":0}')
        with patch("feishu_connector.client.urllib.request.urlopen", return_value=response) as urlopen:
            result = post_json(
                "https://example.test/messages",
                {"Authorization": "Bearer test-token"},
                {"text": "\u4e2d\u6587"},
                3.5,
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(200, result.status)
        self.assertEqual({"code": 0}, result.payload)
        self.assertEqual("POST", request.get_method())
        self.assertEqual(
            "application/json; charset=utf-8",
            request.get_header("Content-type"),
        )
        self.assertEqual(b'{"text":"\xe4\xb8\xad\xe6\x96\x87"}', request.data)
        self.assertEqual("Bearer test-token", request.get_header("Authorization"))
        self.assertEqual(3.5, urlopen.call_args.kwargs["timeout"])

    def test_converts_url_error_to_network_failure(self):
        url_error = urllib.error.URLError("offline")
        with patch("feishu_connector.client.urllib.request.urlopen", side_effect=url_error):
            with self.assertRaises(NetworkFailure) as caught:
                post_json("https://example.test/messages", {}, {"text": "hello"}, 1.0)

        self.assertIs(caught.exception.__cause__, url_error)

    def test_converts_incomplete_successful_response_to_network_failure(self):
        incomplete_read = http.client.IncompleteRead(b"partial body", 100)
        response = FakeUrlopenResponse(200, incomplete_read)
        with patch("feishu_connector.client.urllib.request.urlopen", return_value=response):
            with self.assertRaises(NetworkFailure) as caught:
                post_json("https://example.test/messages", {}, {"text": "hello"}, 1.0)

        self.assertEqual("Feishu request failed", str(caught.exception))
        self.assertNotIn("partial body", str(caught.exception))
        self.assertIs(caught.exception.__cause__, incomplete_read)

    def test_malformed_successful_response_remains_protocol_error(self):
        response = FakeUrlopenResponse(200, b"not json")
        with patch("feishu_connector.client.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(ConnectorError, "invalid JSON") as caught:
                post_json("https://example.test/messages", {}, {"text": "hello"}, 1.0)

        self.assertEqual("protocol", caught.exception.category)

    def test_empty_http_429_body_remains_retryable_rate_limit_error(self):
        http_error = urllib.error.HTTPError(
            "https://example.test/token",
            429,
            "Too Many Requests",
            None,
            io.BytesIO(b""),
        )
        client = FeishuClient(
            make_config(),
            transport=post_json,
            sleep=lambda _: None,
        )
        with patch(
            "feishu_connector.client.urllib.request.urlopen", side_effect=[http_error] * 3
        ):
            with self.assertRaisesRegex(ConnectorError, "after 3 attempts") as caught:
                client.fetch_tenant_access_token()

        self.assertEqual("rate_limit", caught.exception.category)
        self.assertTrue(caught.exception.retryable)

    def test_non_json_http_503_body_remains_retryable_server_error(self):
        def unavailable_error():
            return urllib.error.HTTPError(
                "https://example.test/token",
                503,
                "Service Unavailable",
                None,
                io.BytesIO(b"temporarily unavailable"),
            )

        client = FeishuClient(
            make_config(),
            transport=post_json,
            sleep=lambda _: None,
        )
        with patch(
            "feishu_connector.client.urllib.request.urlopen",
            side_effect=[unavailable_error() for _ in range(3)],
        ):
            with self.assertRaisesRegex(ConnectorError, "after 3 attempts") as caught:
                client.fetch_tenant_access_token()

        self.assertEqual("server", caught.exception.category)
        self.assertTrue(caught.exception.retryable)

    def test_invalid_json_http_auth_errors_are_non_retryable_api_errors(self):
        for status in (401, 403):
            with self.subTest(status=status):
                http_error = urllib.error.HTTPError(
                    "https://example.test/token",
                    status,
                    "Unauthorized",
                    None,
                    io.BytesIO(b"not json"),
                )
                client = FeishuClient(
                    make_config(),
                    transport=post_json,
                    sleep=lambda _: None,
                )
                with patch(
                    "feishu_connector.client.urllib.request.urlopen", side_effect=http_error
                ):
                    with self.assertRaisesRegex(
                        ConnectorError, "HTTP %d" % status
                    ) as caught:
                        client.fetch_tenant_access_token()

                self.assertEqual("api", caught.exception.category)
                self.assertFalse(caught.exception.retryable)

    def test_line_too_long_in_http_error_body_returns_http_status_code(self):
        error = urllib.error.HTTPError(
            "https://example.test/token",
            400,
            "Bad Request",
            None,
            io.BytesIO(b"x" * 70000),
        )
        with patch("feishu_connector.client.urllib.request.urlopen", side_effect=error):
            result = post_json(
                "https://example.test/token", {}, {"text": "hello"}, 1.0
            )
        self.assertEqual(400, result.status)
        self.assertEqual({}, result.payload)

    def test_bad_status_line_from_urlopen_raises_network_failure(self):
        bad_status = http.client.BadStatusLine("HTTP/1.1 200 OK")
        with patch("feishu_connector.client.urllib.request.urlopen", side_effect=bad_status):
            with self.assertRaises(NetworkFailure) as caught:
                post_json(
                    "https://example.test/token", {}, {"text": "hello"}, 1.0
                )
        self.assertEqual("Feishu request failed", str(caught.exception))


class ClientTests(unittest.TestCase):
    def config(self):
        return make_config()

    def test_fetches_token_then_sends_double_encoded_plain_text(self):
        transport = FakeTransport(
            [
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
                JsonResponse(200, {"code": 0, "msg": "success", "data": {}}),
            ]
        )
        client = FeishuClient(self.config(), transport=transport, sleep=lambda _: None)
        client.send_text('\u4e2d\u6587 "quoted"\nnext line')

        token_call, message_call = transport.calls
        self.assertTrue(token_call[0].endswith("/auth/v3/tenant_access_token/internal"))
        self.assertEqual(
            {"app_id": "cli_test", "app_secret": "secret-value"},
            token_call[2],
        )
        self.assertIn("receive_id_type=open_id", message_call[0])
        self.assertEqual("Bearer token-value", message_call[1]["Authorization"])
        self.assertEqual("ou_target1234", message_call[2]["receive_id"])
        self.assertEqual("text", message_call[2]["msg_type"])
        self.assertEqual(
            {"text": '\u4e2d\u6587 "quoted"\nnext line'},
            json.loads(message_call[2]["content"]),
        )

    def test_retries_network_failure_with_exponential_backoff(self):
        delays = []
        transport = FakeTransport(
            [
                NetworkFailure("temporary"),
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
                JsonResponse(200, {"code": 0, "msg": "success"}),
            ]
        )
        client = FeishuClient(self.config(), transport=transport, sleep=delays.append)
        client.send_text("hello")
        self.assertEqual([1.0], delays)

    def test_message_retry_reuses_one_idempotency_uuid(self):
        transport = FakeTransport(
            [
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
                NetworkFailure("response lost after possible delivery"),
                JsonResponse(200, {"code": 0, "msg": "success"}),
            ]
        )
        client = FeishuClient(
            self.config(),
            transport=transport,
            sleep=lambda _: None,
            uuid_factory=lambda: "logical-send-uuid",
        )

        client.send_text("hello")

        message_calls = [call for call in transport.calls if "/messages?" in call[0]]
        self.assertEqual(2, len(message_calls))
        self.assertEqual("logical-send-uuid", message_calls[0][2]["uuid"])
        self.assertEqual("logical-send-uuid", message_calls[1][2]["uuid"])

    def test_separate_logical_sends_use_different_uuids(self):
        identifiers = iter(("first-send-uuid", "second-send-uuid"))
        transport = FakeTransport(
            [
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-one"}),
                JsonResponse(200, {"code": 0, "msg": "success"}),
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-two"}),
                JsonResponse(200, {"code": 0, "msg": "success"}),
            ]
        )
        client = FeishuClient(
            self.config(),
            transport=transport,
            sleep=lambda _: None,
            uuid_factory=lambda: next(identifiers),
        )

        client.send_text("first")
        client.send_text("second")

        message_calls = [call for call in transport.calls if "/messages?" in call[0]]
        self.assertEqual(
            ["first-send-uuid", "second-send-uuid"],
            [call[2]["uuid"] for call in message_calls],
        )

    def test_retry_records_error_category_and_attempt_count(self):
        transport = FakeTransport(
            [
                NetworkFailure("temporary"),
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
            ]
        )
        client = FeishuClient(self.config(), transport=transport, sleep=lambda _: None)
        with self.assertLogs("feishu_connector.client", level="WARNING") as captured:
            client.fetch_tenant_access_token()
        self.assertIn("network", captured.output[0])
        self.assertIn("attempt 1/3", captured.output[0])

    def test_retries_http_429_and_5xx_at_most_twice(self):
        delays = []
        transport = FakeTransport(
            [
                JsonResponse(429, {"code": 230020, "msg": "rate limited"}),
                JsonResponse(503, {"code": -1, "msg": "unavailable"}),
                JsonResponse(503, {"code": -1, "msg": "unavailable"}),
            ]
        )
        client = FeishuClient(self.config(), transport=transport, sleep=delays.append)
        with self.assertLogs("feishu_connector.client", level="WARNING") as captured:
            with self.assertRaisesRegex(ConnectorError, "after 3 attempts") as caught:
                client.fetch_tenant_access_token()
        self.assertTrue(caught.exception.retryable)
        self.assertEqual([1.0, 2.0], delays)
        self.assertEqual(3, len(transport.calls))
        self.assertIn("rate_limit", captured.output[0])
        self.assertIn("attempt 1/3", captured.output[0])
        self.assertIn("server", captured.output[1])
        self.assertIn("attempt 2/3", captured.output[1])

    def test_retries_feishu_rate_limit_business_code(self):
        delays = []
        transport = FakeTransport(
            [
                JsonResponse(200, {"code": 230020, "msg": "rate limited"}),
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
            ]
        )
        client = FeishuClient(self.config(), transport=transport, sleep=delays.append)
        self.assertEqual("token-value", client.fetch_tenant_access_token())
        self.assertEqual([1.0], delays)

    def test_does_not_retry_permission_or_recipient_error(self):
        delays = []
        transport = FakeTransport(
            [
                JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
                JsonResponse(400, {"code": 230013, "msg": "no availability"}),
            ]
        )
        client = FeishuClient(self.config(), transport=transport, sleep=delays.append)
        with self.assertRaises(ConnectorError) as caught:
            client.send_text("hello")
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(230013, caught.exception.code)
        self.assertEqual([], delays)
        self.assertEqual(2, len(transport.calls))

    def test_empty_token_is_authentication_error(self):
        transport = FakeTransport([JsonResponse(200, {"code": 0})])
        client = FeishuClient(self.config(), transport=transport, sleep=lambda _: None)
        with self.assertRaisesRegex(ConnectorError, "missing tenant_access_token"):
            client.fetch_tenant_access_token()


if __name__ == "__main__":
    unittest.main()
