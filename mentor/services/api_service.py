"""Read-only external API connectors for AI-Agent."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"
DEFAULT_ALPACA_FEED = "iex"

def _env_value(*names):
    """
    Read the first configured environment variable from the supplied names.

    The aliases keep the demo compatible with the existing .env naming
    without requiring credentials to be renamed.
    """
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    raise ValueError(
        "Required Alpaca credential is not configured. Checked: "
        + ", ".join(names)
    )

def _http_error_detail(exc):
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        return payload.get("message") or payload.get("error") or str(payload)
    except Exception:
        return str(exc)

def get_alpaca_latest_trade(symbol):
    """Get one latest available stock trade from Alpaca Market Data."""
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("Stock symbol is required.")
    if not symbol.replace(".", "").replace("-", "").isalnum():
        raise ValueError("Stock symbol contains unsupported characters.")

    key = _env_value("ALPACA_API_KEY", "API_KEY", "AP_KEY")
    secret = _env_value(
        "ALPACA_SECRET_KEY",
        "ALPACA_API_SECRET",
        "API_SECRET",
        "API_Secret",
        "AP_SECRET",
    )
    feed = (os.getenv("ALPACA_DATA_FEED") or DEFAULT_ALPACA_FEED).strip().lower()

    url = (
        f"{ALPACA_DATA_BASE_URL}/v2/stocks/{quote(symbol, safe='')}"
        f"/trades/latest?feed={quote(feed, safe='')}"
    )
    req = Request(url, method="GET", headers={
        "Accept": "application/json",
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "User-Agent": "AI-Agent/1.0",
    })
    try:
        with urlopen(req, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(
            f"Alpaca API returned HTTP {exc.code}: {_http_error_detail(exc)}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to reach Alpaca API: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("Alpaca API request timed out.") from exc

    trade = payload.get("trade") or {}
    if trade.get("p") is None:
        raise RuntimeError(f"Alpaca returned no latest trade price for {symbol}.")

    return {
        "provider": "ALPACA",
        "source_type": "LIVE_API",
        "data_type": "LATEST_TRADE",
        "symbol": payload.get("symbol") or symbol,
        "price": trade.get("p"),
        "currency": "USD",
        "timestamp": trade.get("t"),
        "exchange": trade.get("x"),
        "size": trade.get("s"),
        "feed": feed,
        "live_api_used": True,
        "database_searched": False,
        "generic_knowledge_used": False,
        "openai_used": False,
        "automatically_stored": False,
    }


def get_alpaca_recent_bars(symbol, limit=36):
    """Return recent 5-minute Alpaca bars for a compact demo price chart."""
    from datetime import datetime, timedelta, timezone

    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("Stock symbol is required.")

    key = _env_value("ALPACA_API_KEY", "API_KEY", "AP_KEY")
    secret = _env_value(
        "ALPACA_SECRET_KEY", "ALPACA_API_SECRET",
        "API_SECRET", "API_Secret", "AP_SECRET",
    )
    feed = (os.getenv("ALPACA_DATA_FEED") or DEFAULT_ALPACA_FEED).strip().lower()

    start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = (
        f"{ALPACA_DATA_BASE_URL}/v2/stocks/{quote(symbol, safe='')}/bars"
        f"?timeframe=5Min&start={quote(start, safe=':-TZ')}"
        f"&limit=1000&adjustment=raw&feed={quote(feed, safe='')}"
    )
    req = Request(url, method="GET", headers={
        "Accept": "application/json",
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "User-Agent": "AI-Agent/1.0",
    })
    try:
        with urlopen(req, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(
            f"Alpaca bars API returned HTTP {exc.code}: {_http_error_detail(exc)}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to reach Alpaca bars API: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("Alpaca bars API request timed out.") from exc

    bars = payload.get("bars") or []
    bars = bars[-max(2, int(limit)):]
    return [
        {
            "timestamp": bar.get("t"),
            "open": bar.get("o"),
            "high": bar.get("h"),
            "low": bar.get("l"),
            "close": bar.get("c"),
            "volume": bar.get("v"),
        }
        for bar in bars
        if bar.get("c") is not None
    ]
