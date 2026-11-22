"""Read-only, server-side client for the official Freqtrade REST API."""
from __future__ import annotations

import asyncio
import os
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


class FreqtradeClient:
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

    async def overview(self):
        if not self.configured:
            return {
                "configured": False,
                "mode": "READ_ONLY",
                "orders_enabled": False,
                "message": "Freqtrade bağlantı bilgileri yapılandırılmamış.",
            }
        self._validate_url()
        timeout = httpx.Timeout(8.0, connect=5.0)
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, transport=self.transport
        ) as client:
            try:
                token_response = await client.post(
                    self.base_url + "/api/v1/token/login",
                    auth=httpx.BasicAuth(self.username, self.password),
                )
                token_response.raise_for_status()
                token_data = token_response.json()
                access_token = token_data.get("access_token")
                if not access_token:
                    raise FreqtradeError("Freqtrade kimlik doğrulaması token döndürmedi.")
            except FreqtradeError:
                raise
            except httpx.HTTPStatusError as ex:
                code = ex.response.status_code
                message = "Freqtrade kullanıcı adı/şifresi reddedildi." if code in (401, 403) else f"Freqtrade token HTTP {code} döndürdü."
                raise FreqtradeError(message, 502) from ex
            except (httpx.HTTPError, ValueError) as ex:
                raise FreqtradeError(f"Freqtrade bağlantısı kurulamadı: {type(ex).__name__}.") from ex

            headers = {"Authorization": "Bearer " + access_token}

            async def get_json(path):
                response = await client.get(self.base_url + path, headers=headers)
                response.raise_for_status()
                return response.json()

            paths = {
                "status": "/api/v1/status",
                "profit": "/api/v1/profit",
                "count": "/api/v1/count",
                "version": "/api/v1/version",
            }
            results = await asyncio.gather(
                *(get_json(path) for path in paths.values()), return_exceptions=True
            )
        data = dict(zip(paths, results))
        errors = {
            key: f"{type(value).__name__}: {str(value)[:160]}"
            for key, value in data.items()
            if isinstance(value, Exception)
        }
        status_data = data["status"]
        trades = status_data if isinstance(status_data, list) else []
        safe_trades = [
            _pick(
                trade,
                (
                    "trade_id", "pair", "is_open", "open_date", "open_rate",
                    "current_rate", "current_profit", "current_profit_pct",
                    "stake_amount", "amount", "close_date", "close_rate",
                    "profit_abs", "profit_ratio", "exit_reason", "enter_tag",
                ),
            )
            for trade in trades
            if isinstance(trade, dict)
        ]
        profit = data["profit"]
        count = data["count"]
        version = data["version"]
        return {
            "configured": True,
            "mode": "READ_ONLY",
            "orders_enabled": False,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "version": _pick(version, ("version",)) if isinstance(version, dict) else {},
            "count": _pick(count, ("current", "max", "total_stake")) if isinstance(count, dict) else {},
            "profit": _pick(
                profit,
                (
                    "profit_closed_coin", "profit_closed_percent", "profit_closed_fiat",
                    "profit_all_coin", "profit_all_percent", "profit_all_fiat",
                    "trade_count", "closed_trade_count", "winning_trades",
                    "losing_trades", "profit_factor", "avg_duration",
                    "best_pair", "stake_currency", "starting_balance", "dry_run",
                ),
            ) if isinstance(profit, dict) else {},
            "trades": safe_trades,
            "errors": errors,
        }
