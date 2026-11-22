"""Server-side client for the official Freqtrade REST API."""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx


class FreqtradeError(Exception):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


def _pick(source, fields):
    if not isinstance(source, dict):
        return {}
    return {key: source[key] for key in fields if key in source}


def _rows(source):
    if isinstance(source, list):
        return source
    if not isinstance(source, dict):
        return []
    data = source.get("data") or source.get("trades") or source.get("rows")
    columns = source.get("columns")
    if isinstance(data, list) and data and isinstance(data[0], list) and isinstance(columns, list):
        return [dict(zip(columns, row)) for row in data if isinstance(row, list)]
    return data if isinstance(data, list) else []


def _api_error(error):
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    if isinstance(error, httpx.TimeoutException):
        return "Zaman aşımı"
    if isinstance(error, httpx.HTTPError):
        return "Bağlantı hatası"
    if isinstance(error, ValueError):
        return "Geçersiz JSON yanıtı"
    return type(error).__name__


class FreqtradeClient:
    TRADE_FIELDS = (
        "trade_id", "id", "pair", "is_open", "open_date", "open_rate",
        "current_rate", "current_profit", "current_profit_pct", "stake_amount",
        "amount", "close_date", "close_rate", "profit_abs", "profit_ratio",
        "exit_reason", "enter_tag", "exit_tag", "leverage", "stop_loss_abs",
    )
    CANDLE_FIELDS = (
        "date", "open", "high", "low", "close", "volume", "enter_long",
        "exit_long", "enter_short", "exit_short", "enter_tag", "exit_tag",
        "rsi", "ema_10", "ema_20", "ema_50", "ema_200", "macd", "adx", "atr",
    )
    CONTROL_ACTIONS = frozenset({"start", "pause", "stop", "stopbuy", "reload_config"})
    TIMEFRAMES = frozenset({"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"})

    def __init__(self, base_url: str, username: str, password: str, transport=None):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.transport = transport

    @classmethod
    def from_environment(cls):
        return cls(
            os.getenv("FREQTRADE_API_URL", "").strip(),
            os.getenv("FREQTRADE_API_USERNAME", "").strip(),
            os.getenv("FREQTRADE_API_PASSWORD", ""),
        )

    @property
    def configured(self):
        return bool(self.base_url and self.username and self.password)

    def _validate_url(self):
        parsed = urlsplit(self.base_url)
        local_http = parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
        if (parsed.scheme != "https" and not local_http) or not parsed.hostname or parsed.username or parsed.password:
            raise FreqtradeError("Freqtrade API adresi HTTPS olmalı; yalnızca yerel testte HTTP kabul edilir.", 503)
        if parsed.query or parsed.fragment:
            raise FreqtradeError("Freqtrade API adresinde query veya fragment kullanmayın.", 503)

    async def _login(self, client):
        try:
            response = await client.post(
                self.base_url + "/api/v1/token/login",
                auth=httpx.BasicAuth(self.username, self.password),
            )
            response.raise_for_status()
            token = response.json().get("access_token")
            if not token:
                raise FreqtradeError("Freqtrade kimlik doğrulaması token döndürmedi.", 502)
            return {"Authorization": f"Bearer {token}"}
        except FreqtradeError:
            raise
        except httpx.HTTPStatusError as ex:
            code = ex.response.status_code
            message = "Freqtrade kullanıcı adı/şifresi reddedildi." if code in (401, 403) else f"Freqtrade token HTTP {code} döndürdü."
            raise FreqtradeError(message, 502) from ex
        except httpx.TimeoutException as ex:
            raise FreqtradeError("Freqtrade kimlik doğrulaması zaman aşımına uğradı.", 504) from ex
        except (httpx.HTTPError, ValueError) as ex:
            raise FreqtradeError(f"Freqtrade bağlantısı kurulamadı: {_api_error(ex)}.", 502) from ex

    async def _api_json(self, client, headers, path, params=None, method="GET"):
        try:
            response = await client.request(method, self.base_url + path, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as ex:
            raise FreqtradeError("Freqtrade API zaman aşımına uğradı.", 504) from ex
        except httpx.HTTPStatusError as ex:
            raise FreqtradeError(f"Freqtrade API HTTP {ex.response.status_code} döndürdü.", 502) from ex
        except (httpx.HTTPError, ValueError) as ex:
            raise FreqtradeError(f"Freqtrade API yanıtı alınamadı: {_api_error(ex)}.", 502) from ex

    async def _session(self):
        self._validate_url()
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=5.0),
            follow_redirects=False,
            transport=self.transport,
        )
        try:
            return client, await self._login(client)
        except Exception:
            await client.aclose()
            raise

    async def overview(self):
        if not self.configured:
            return {
                "configured": False,
                "mode": "UNAVAILABLE",
                "orders_enabled": False,
                "message": "Freqtrade API bağlantısı yapılandırılmamış.",
            }
        client, headers = await self._session()
        endpoints = {
            "status": ("/api/v1/status", None),
            "profit": ("/api/v1/profit", None),
            "count": ("/api/v1/count", None),
            "version": ("/api/v1/version", None),
            "config": ("/api/v1/show_config", None),
            "whitelist": ("/api/v1/whitelist", None),
            "balance": ("/api/v1/balance", None),
            "performance": ("/api/v1/performance", None),
            "stats": ("/api/v1/stats", None),
            "daily": ("/api/v1/daily", {"timescale": 30}),
            "weekly": ("/api/v1/weekly", {"timescale": 12}),
            "monthly": ("/api/v1/monthly", {"timescale": 12}),
            "trades": ("/api/v1/trades", {"limit": 100}),
            "strategies": ("/api/v1/strategies", None),
            "available_pairs": ("/api/v1/available_pairs", None),
            "health": ("/api/v1/health", None),
        }
        try:
            results = await asyncio.gather(
                *(self._api_json(client, headers, path, params) for path, params in endpoints.values()),
                return_exceptions=True,
            )
        finally:
            await client.aclose()
        data = dict(zip(endpoints, results))
        errors = {key: _api_error(value) for key, value in data.items() if isinstance(value, Exception)}
        status_data = data.get("status")
        open_trades = _rows(status_data)
        history_data = data.get("trades")
        history = _rows(history_data)
        config = data.get("config")
        strategy_data = data.get("strategies")
        pair_data = data.get("available_pairs")
        whitelist_data = data.get("whitelist")
        return {
            "configured": True,
            "mode": "LIVE" if isinstance(config, dict) and config.get("dry_run") is False else "DRY_RUN" if isinstance(config, dict) and config.get("dry_run") is True else "UNKNOWN",
            "orders_enabled": False,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "version": _pick(data.get("version"), ("version",)),
            "count": _pick(data.get("count"), ("current", "max", "total_stake")),
            "profit": _pick(
                data.get("profit"),
                (
                    "profit_closed_coin", "profit_closed_percent", "profit_closed_fiat",
                    "profit_all_coin", "profit_all_percent", "profit_all_fiat",
                    "trade_count", "closed_trade_count", "winning_trades",
                    "losing_trades", "profit_factor", "avg_duration",
                    "best_pair", "stake_currency", "starting_balance", "dry_run",
                ),
            ),
            "config": _pick(config, ("strategy", "timeframe", "max_open_trades", "stake_currency", "dry_run", "trading_mode", "runmode")),
            "health": _pick(data.get("health"), ("last_process", "status")),
            "balance": _pick(data.get("balance"), ("total", "free", "used", "stake", "stake_currency", "starting_capital")),
            "stats": _pick(data.get("stats"), ("total_trades", "current_wallets", "winning", "losing", "draws", "profit_closed_coin", "profit_all_coin")),
            "whitelist": whitelist_data.get("whitelist", []) if isinstance(whitelist_data, dict) else whitelist_data if isinstance(whitelist_data, list) else [],
            "strategies": self._strategy_names(strategy_data),
            "available_pairs": self._available_pairs(pair_data),
            "performance": self._pick_rows(data.get("performance"), ("pair", "profit", "profit_abs", "profit_ratio", "count", "trade_count")),
            "daily": self._pick_rows(data.get("daily"), ("date", "profit_abs", "profit_ratio", "abs_profit", "rel_profit", "trade_count", "wins", "draws", "losses")),
            "weekly": self._pick_rows(data.get("weekly"), ("date", "profit_abs", "profit_ratio", "abs_profit", "rel_profit", "trade_count", "wins", "draws", "losses")),
            "monthly": self._pick_rows(data.get("monthly"), ("date", "profit_abs", "profit_ratio", "abs_profit", "rel_profit", "trade_count", "wins", "draws", "losses")),
            "open_trades": [_pick(x, self.TRADE_FIELDS) for x in open_trades if isinstance(x, dict)],
            "trades": [_pick(x, self.TRADE_FIELDS) for x in history if isinstance(x, dict)],
            "errors": errors,
        }

    @staticmethod
    def _pick_rows(data, fields):
        return [_pick(row, fields) for row in _rows(data) if isinstance(row, dict)]

    @staticmethod
    def _strategy_names(data):
        if isinstance(data, dict):
            strategies = data.get("strategies") or []
            if isinstance(strategies, dict):
                return [{"name": str(name)[:81]} for name in strategies]
        else:
            strategies = data if isinstance(data, list) else []
        return [
            _pick(item, ("name", "strategy", "class_name"))
            if isinstance(item, dict) else {"name": str(item)[:81]}
            for item in strategies
        ]

    @staticmethod
    def _available_pairs(data):
        if not isinstance(data, dict):
            return []
        pairs = data.get("pairs") or data.get("pairlist") or data.get("data") or []
        if not isinstance(pairs, list):
            return []
        result = []
        for item in pairs:
            pair = item.get("pair") if isinstance(item, dict) else item
            if isinstance(pair, str) and pair not in result:
                result.append(pair)
        return result[:500]

    async def market_data(self, pair, timeframe, limit):
        if not self.configured:
            raise FreqtradeError("Freqtrade API bağlantısı yapılandırılmamış.")
        if timeframe not in self.TIMEFRAMES or not re.fullmatch(r"[A-Za-z0-9._:/-]{3,48}", pair):
            raise FreqtradeError("Geçersiz parite veya zaman dilimi.", 400)
        client, headers = await self._session()
        try:
            result = await self._api_json(
                client, headers, "/api/v1/pair_candles",
                {"pair": pair, "timeframe": timeframe},
            )
        finally:
            await client.aclose()
        candles = self._pick_rows(result, self.CANDLE_FIELDS)[-limit:]
        return {
            "pair": pair,
            "timeframe": timeframe,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "candles": candles,
            "count": len(candles),
        }

    async def strategy_analysis(self, pair, timeframe, strategy, timerange, limit):
        if not self.configured:
            raise FreqtradeError("Freqtrade API bağlantısı yapılandırılmamış.")
        if timeframe not in self.TIMEFRAMES or not re.fullmatch(r"[A-Za-z0-9._:/-]{3,48}", pair):
            raise FreqtradeError("Geçersiz parite veya zaman dilimi.", 400)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,80}", strategy):
            raise FreqtradeError("Geçersiz strateji adı.", 400)
        params = {"pair": pair, "timeframe": timeframe, "strategy": strategy}
        if timerange:
            params["timerange"] = timerange
        client, headers = await self._session()
        try:
            result = await self._api_json(client, headers, "/api/v1/pair_history", params)
        finally:
            await client.aclose()
        rows = self._pick_rows(result, self.CANDLE_FIELDS)[-limit:]
        counts = {
            key: sum(1 for row in rows if row.get(key) not in (None, 0, False, ""))
            for key in ("enter_long", "exit_long", "enter_short", "exit_short")
        }
        return {
            "pair": pair,
            "timeframe": timeframe,
            "strategy": strategy,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "candles": rows,
            "count": len(rows),
            "signals": counts,
        }

    async def control(self, action):
        if action not in self.CONTROL_ACTIONS:
            raise FreqtradeError("Desteklenmeyen Freqtrade kontrolü.", 400)
        if not self.configured:
            raise FreqtradeError("Freqtrade API bağlantısı yapılandırılmamış.")
        client, headers = await self._session()
        try:
            await self._api_json(client, headers, f"/api/v1/{action}", method="POST")
        finally:
            await client.aclose()
        return {"ok": True, "action": action}
