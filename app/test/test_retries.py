import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# makes it access the test db instead
os.environ["env"] = "dev"

sys.path.append(os.path.join(os.path.dirname(__file__), "../../"))

import aiohttp
import pytest
import requests

from app.clients import MAX_RETRIES, UpClient


def make_client():
    return UpClient(os.environ["UP_TOKEN"], lookback=7)


def client_response_error(status):
    return aiohttp.ClientResponseError(request_info=MagicMock(), history=(), status=status)


class FakeResponse:
    def __init__(self, json_data=None, exc=None, json_exc=None):
        self._json_data = json_data
        self._exc = exc
        self._json_exc = json_exc

    async def json(self):
        if self._json_exc:
            raise self._json_exc
        return self._json_data

    def raise_for_status(self):
        if self._exc:
            raise self._exc


class FakeGetContextManager:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        return False


class FakeClientSession:
    def __init__(self, responses):
        self.responses = responses
        self.get_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url, headers=None, **extras):
        self.get_calls.append(url)
        return FakeGetContextManager(self.responses.pop(0))


class TestSyncRetries:
    def test_retries_on_transient_failure_then_succeeds(self):
        client = make_client()
        queue = [
            requests.exceptions.ConnectionError("boom"),
            requests.exceptions.ConnectionError("boom"),
            {"ok": True},
        ]

        def fake_get(url, headers=None, **extras):
            result = queue.pop(0)
            if isinstance(result, Exception):
                raise result
            mock_res = MagicMock()
            mock_res.raise_for_status.return_value = None
            mock_res.json.return_value = result
            return mock_res

        with patch("app.clients.requests.get", side_effect=fake_get) as mock_get, \
             patch("app.clients.time.sleep") as mock_sleep:
            result = client._fetch_with_retries("http://fake", {})

        assert result == {"ok": True}
        assert mock_get.call_count == 3
        assert mock_sleep.call_count == 2

    def test_does_not_retry_on_401(self):
        client = make_client()

        def fake_get(url, headers=None, **extras):
            mock_res = MagicMock()
            mock_res.status_code = 401
            mock_res.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_res)
            return mock_res

        with patch("app.clients.requests.get", side_effect=fake_get) as mock_get:
            with pytest.raises(UpClient.UpAuthError):
                client._fetch_with_retries("http://fake", {})

        assert mock_get.call_count == 1

    def test_does_not_retry_on_client_error(self):
        client = make_client()

        def fake_get(url, headers=None, **extras):
            mock_res = MagicMock()
            mock_res.status_code = 400
            mock_res.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_res)
            return mock_res

        with patch("app.clients.requests.get", side_effect=fake_get) as mock_get:
            with pytest.raises(requests.exceptions.HTTPError):
                client._fetch_with_retries("http://fake", {})

        assert mock_get.call_count == 1

    def test_gives_up_after_max_retries(self):
        client = make_client()

        def fake_get(url, headers=None, **extras):
            mock_res = MagicMock()
            mock_res.status_code = 500
            mock_res.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_res)
            return mock_res

        with patch("app.clients.requests.get", side_effect=fake_get) as mock_get, \
             patch("app.clients.time.sleep"):
            with pytest.raises(requests.exceptions.HTTPError):
                client._fetch_with_retries("http://fake", {})

        assert mock_get.call_count == MAX_RETRIES

    def test_raises_on_malformed_json_response(self):
        "a non-JSON body should be treated like any other request failure: retried, then raised"
        client = make_client()

        def fake_get(url, headers=None, **extras):
            mock_res = MagicMock()
            mock_res.raise_for_status.return_value = None
            mock_res.json.side_effect = requests.exceptions.JSONDecodeError("Expecting value", "", 0)
            return mock_res

        with patch("app.clients.requests.get", side_effect=fake_get) as mock_get, \
             patch("app.clients.time.sleep"):
            with pytest.raises(requests.exceptions.JSONDecodeError):
                client._fetch_with_retries("http://fake", {})

        assert mock_get.call_count == MAX_RETRIES


class TestAsyncRetries:
    def test_retries_on_transient_failure_then_succeeds(self):
        client = make_client()
        responses = [
            FakeResponse(exc=client_response_error(500)),
            FakeResponse(exc=client_response_error(500)),
            FakeResponse(json_data={"ok": True}),
        ]
        session = FakeClientSession(responses)

        with patch("app.clients.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = asyncio.run(client._async_fetch_with_retries(session, "http://fake", {}))

        assert result == {"ok": True}
        assert mock_sleep.call_count == 2
        # all 3 attempts reused the same session instead of opening a new one each time
        assert len(session.get_calls) == 3

    def test_does_not_retry_on_401(self):
        client = make_client()
        responses = [FakeResponse(exc=client_response_error(401))]
        session = FakeClientSession(responses)

        with pytest.raises(UpClient.UpAuthError):
            asyncio.run(client._async_fetch_with_retries(session, "http://fake", {}))

    def test_does_not_retry_on_client_error(self):
        client = make_client()
        responses = [FakeResponse(exc=client_response_error(400))]
        session = FakeClientSession(responses)

        with pytest.raises(aiohttp.ClientResponseError):
            asyncio.run(client._async_fetch_with_retries(session, "http://fake", {}))

    def test_gives_up_after_max_retries(self):
        client = make_client()
        responses = [FakeResponse(exc=client_response_error(500)) for _ in range(MAX_RETRIES)]
        session = FakeClientSession(responses)

        with patch("app.clients.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(aiohttp.ClientResponseError):
                asyncio.run(client._async_fetch_with_retries(session, "http://fake", {}))

    def test_raises_on_malformed_json_response(self):
        "a body that fails to parse as JSON isn't an aiohttp.ClientError, so it isn't retried at all"
        client = make_client()
        responses = [FakeResponse(json_exc=json.JSONDecodeError("Expecting value", "", 0))]
        session = FakeClientSession(responses)

        with pytest.raises(json.JSONDecodeError):
            asyncio.run(client._async_fetch_with_retries(session, "http://fake", {}))

        assert len(session.get_calls) == 1


class TestAsyncGetRequestReusesSession:
    def test_pagination_reuses_same_session_across_pages(self):
        client = make_client()
        responses = [
            FakeResponse(json_data={"data": [1], "links": {"next": "http://fake?page=2"}}),
            FakeResponse(json_data={"data": [2], "links": {"next": None}}),
        ]
        session = FakeClientSession(responses)

        async def collect():
            return [res async for res in client.async_get_request(session, url="http://fake")]

        results = asyncio.run(collect())

        assert len(results) == 2
        # both pages were fetched off the one FakeClientSession instance we passed in
        assert len(session.get_calls) == 2
