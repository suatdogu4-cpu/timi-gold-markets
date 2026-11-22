import asyncio
import time

import httpx
import pytest

from freqtrade_client import FreqtradeClient, FreqtradeError
from main import Market


def test_stale_candle_cache_is_not_returned_when_upstream_fails():
    market = Market()
    key = ("XAUUSDT", "1m")
    market.candles[key] = [{"t": 1, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]
    market.candle_updated[key] = int((time.time() - 60) * 1000)

    async def upstream_error(*args, **kwargs):
        raise RuntimeError("market data unavailable")

    market.fetch_bitget_candles = upstream_error
    with pytest.raises(RuntimeError, match="market data unavailable"):
        asyncio.run(market.get_candles("XAUUSDT", "1m", 100))


def test_unconfigured_freqtrade_connection_is_read_only():
    result = asyncio.run(FreqtradeClient("", "", "").overview())
    assert result["configured"] is False
    assert result["mode"] == "READ_ONLY"
    assert result["orders_enabled"] is False


def test_freqtrade_overview_uses_authenticated_read_only_endpoints():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path.endswith("/token/login"):
            assert request.headers.get("authorization", "").startswith("Basic ")
            return httpx.Response(200, json={"access_token": "private-token"})
        if request.headers.get("authorization") != "Bearer private-token":
            return httpx.Response(401)
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json=[{
                "pair": "XAU/USDT",
                "open_rate": 2500,
                "current_rate": 2502,
                "current_profit": 0.002,
                "api_key": "must-not-leak",
            }])
        if request.url.path.endswith("/profit"):
            return httpx.Response(200, json={
                "trade_count": 4,
                "profit_all_coin": 0.15,
                "private_value": "must-not-leak",
            })
        if request.url.path.endswith("/count"):
            return httpx.Response(200, json={"current": 1, "max": 3, "total_stake": 50})
        if request.url.path.endswith("/version"):
            return httpx.Response(200, json={"version": "2026.1"})
        return httpx.Response(404)

    client = FreqtradeClient(
        "https://freqtrade.example",
        "api-user",
        "api-password",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(client.overview())

    assert result["configured"] is True
    assert result["orders_enabled"] is False
    assert result["version"]["version"] == "2026.1"
    assert result["trades"][0]["pair"] == "XAU/USDT"
    assert "api_key" not in result["trades"][0]
    assert "private_value" not in result["profit"]
    assert all(method == "GET" or path.endswith("/token/login") for method, path, _ in calls)
    assert any(auth == "Bearer private-token" for _, _, auth in calls)


def test_freqtrade_rejects_non_tls_remote_api():
    client = FreqtradeClient("http://freqtrade.example", "user", "password")
    with pytest.raises(FreqtradeError, match="HTTPS"):
        asyncio.run(client.overview())
