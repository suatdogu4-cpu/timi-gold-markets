import asyncio
import time

import httpx
import pytest

from freqtrade_client import FreqtradeClient, FreqtradeError
import main as app_module
from main import Market, nowms
from starlette.requests import Request


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


def test_concurrent_candle_requests_share_one_upstream_fetch():
    market = Market()
    key = ("XAUUSDT", "1m")
    calls = []

    async def upstream(*args, **kwargs):
        calls.append(True)
        await asyncio.sleep(0.03)
        bars = [
            {"t": int(time.time()) - 99 + i, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}
            for i in range(100)
        ]
        market.candles[key] = bars
        market.candle_updated[key] = nowms()
        return bars

    market.fetch_bitget_candles = upstream

    async def run():
        return await asyncio.gather(*[
            market.get_candles("XAUUSDT", "1m", 100) for _ in range(8)
        ])

    results = asyncio.run(run())
    assert len(calls) == 1
    assert all(result == results[0] for result in results)


def test_unconfigured_freqtrade_connection_is_unavailable():
    result = asyncio.run(FreqtradeClient("", "", "").overview())
    assert result["configured"] is False
    assert result["mode"] == "UNAVAILABLE"
    assert result["orders_enabled"] is False


def test_freqtrade_session_cookie_is_signed_and_expires(monkeypatch):
    monkeypatch.setattr(app_module, "FREQTRADE_UI_PASSWORD", "a-strong-local-test-password")
    valid_token = app_module._freqtrade_session_value(int(time.time()) + 60)
    scope = {
        "type": "http",
        "headers": [(b"cookie", f"freqtrade_session={valid_token}".encode())],
    }
    assert app_module._freqtrade_session_valid(Request(scope))

    expired_token = app_module._freqtrade_session_value(int(time.time()) - 1)
    expired_scope = {
        "type": "http",
        "headers": [(b"cookie", f"freqtrade_session={expired_token}".encode())],
    }
    assert not app_module._freqtrade_session_valid(Request(expired_scope))
    tampered_scope = {
        "type": "http",
        "headers": [(b"cookie", b"freqtrade_session=9999999999.invalid")],
    }
    assert not app_module._freqtrade_session_valid(Request(tampered_scope))


def test_freqtrade_data_and_controls_use_authenticated_server_side_api():
    calls = []

    def handler(request):
        authorization = request.headers.get("authorization")
        calls.append((request.method, request.url.path, authorization))
        if request.url.path.endswith("/token/login"):
            assert authorization and authorization.startswith("Basic ")
            return httpx.Response(200, json={"access_token": "private-token"})
        if authorization != "Bearer private-token":
            return httpx.Response(401)
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json=[{
                "pair": "XAU/USDT",
                "open_rate": 2500,
                "current_rate": 2502,
                "current_profit": 0.002,
                "api_key": "must-not-leak",
            }])
        if request.url.path.endswith("/show_config"):
            return httpx.Response(200, json={
                "dry_run": True,
                "strategy": "SampleStrategy",
                "timeframe": "5m",
                "exchange": {"name": "example", "key": "must-not-leak"},
                "api_server": {"password": "must-not-leak"},
            })
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
        if request.url.path.endswith("/whitelist"):
            return httpx.Response(200, json={"whitelist": ["XAU/USDT"]})
        if request.url.path.endswith("/strategies"):
            return httpx.Response(200, json={"strategies": [{"name": "SampleStrategy"}]})
        if request.url.path.endswith("/available_pairs"):
            return httpx.Response(200, json={"pairs": ["XAU/USDT"]})
        if request.url.path.endswith("/pair_candles"):
            return httpx.Response(200, json={"data": [{
                "date": "2026-01-01T00:00:00Z", "open": 2500, "high": 2502,
                "low": 2499, "close": 2501, "volume": 3, "private_key": "must-not-leak",
            }]})
        if request.url.path.endswith("/pair_history"):
            return httpx.Response(200, json={"data": [{
                "date": "2026-01-01T00:00:00Z", "open": 2500, "high": 2502,
                "low": 2499, "close": 2501, "enter_long": 1, "exit_short": 1,
            }]})
        if request.url.path.endswith("/start") and request.method == "POST":
            return httpx.Response(200, json={"status": "starting"})
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
    assert result["mode"] == "DRY_RUN"
    assert result["version"]["version"] == "2026.1"
    assert result["open_trades"][0]["pair"] == "XAU/USDT"
    assert "api_key" not in result["open_trades"][0]
    assert result["config"]["strategy"] == "SampleStrategy"
    assert "exchange" not in result["config"]
    assert "private_value" not in result["profit"]
    assert any(auth == "Bearer private-token" for _, _, auth in calls)

    market = asyncio.run(client.market_data("XAU/USDT", "5m", 100))
    assert market["count"] == 1
    assert market["candles"][0]["close"] == 2501
    assert "private_key" not in market["candles"][0]

    analysis = asyncio.run(client.strategy_analysis("XAU/USDT", "5m", "SampleStrategy", None, 100))
    assert analysis["signals"]["enter_long"] == 1
    assert analysis["signals"]["exit_short"] == 1
    assert asyncio.run(client.control("start")) == {"ok": True, "action": "start"}
    with pytest.raises(FreqtradeError, match="Desteklenmeyen"):
        asyncio.run(client.control("forceenter"))


def test_freqtrade_rejects_non_tls_remote_api():
    client = FreqtradeClient("http://freqtrade.example", "user", "password")
    with pytest.raises(FreqtradeError, match="HTTPS"):
        asyncio.run(client.overview())
