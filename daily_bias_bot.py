"""
Daily Bias Bot (ICT-style, rule-based, free)
=============================================
Analyzes XAU/USD Weekly + Daily candles to produce a directional bias each
day before the London session. 100% rule-based - no AI, no paid API.

Logic per timeframe (Weekly, Daily):
  Compare the last CLOSED candle against the one before it:
    - BOS (Break of Structure):
        close > prior_high  -> BULLISH (structure broken up)
        close < prior_low   -> BEARISH (structure broken down)
    - Liquidity sweep (if no clean BOS):
        low < prior_low AND close > prior_low   -> BULLISH (sell-side swept)
        high > prior_high AND close < prior_high -> BEARISH (buy-side swept)
    - Otherwise: NEUTRAL (inside bar / no clear signal)

Draw on liquidity: nearest untouched swing high (above price) and swing low
(below price) from the last 10 daily candles - the levels price is being
"drawn" toward.

Overall bias: Weekly + Daily agreement -> HIGH PROBABILITY.
              Disagreement -> MIXED / CAUTION.

Data: TwelveData free API. Alerts: Telegram Bot API (free).
"""

import os
import requests

SYMBOL = "XAU/USD"
TWELVEDATA_API_KEY = os.environ["TWELVEDATA_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

TWELVEDATA_URL = "https://api.twelvedata.com/time_series"


def fetch_candles(interval: str, outputsize: int = 15):
    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVEDATA_API_KEY,
        "order": "ASC",
        "timezone": "UTC",
    }
    resp = requests.get(TWELVEDATA_URL, params=params, timeout=20)
    data = resp.json()
    if "values" not in data:
        print(f"[WARN] No data for {interval}: {data}")
        return []
    candles = []
    for row in data["values"]:
        candles.append({
            "datetime": row["datetime"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        })
    return candles


def structure_bias(candles):
    """
    Returns ('BULLISH'|'BEARISH'|'NEUTRAL', reason_str) based on the last
    two CLOSED candles. Excludes the currently-forming candle.
    """
    closed = candles[:-1]  # drop still-forming candle
    if len(closed) < 2:
        return "NEUTRAL", "Not enough data"

    prior = closed[-2]
    last = closed[-1]

    if last["close"] > prior["high"]:
        return "BULLISH", f"BOS up: closed {last['close']} above prior high {prior['high']}"
    if last["close"] < prior["low"]:
        return "BEARISH", f"BOS down: closed {last['close']} below prior low {prior['low']}"
    if last["low"] < prior["low"] and last["close"] > prior["low"]:
        return "BULLISH", f"Sell-side liquidity swept ({prior['low']}), closed back above"
    if last["high"] > prior["high"] and last["close"] < prior["high"]:
        return "BEARISH", f"Buy-side liquidity swept ({prior['high']}), closed back below"
    return "NEUTRAL", "Inside bar / no clear structure break"


def draw_on_liquidity(daily_candles, current_price):
    """
    Nearest untouched swing high above current price, and swing low below
    current price, from the last 10 closed daily candles.
    """
    closed = daily_candles[:-1][-10:]
    if not closed:
        return None, None

    highs_above = [c["high"] for c in closed if c["high"] > current_price]
    lows_below = [c["low"] for c in closed if c["low"] < current_price]

    nearest_high = min(highs_above) if highs_above else None
    nearest_low = max(lows_below) if lows_below else None
    return nearest_high, nearest_low


def format_message(weekly_bias, weekly_reason, daily_bias, daily_reason,
                    current_price, liquidity_high, liquidity_low, overall):
    return (
        f"*DAILY BIAS — XAU/USD*\n\n"
        f"*Weekly:* {weekly_bias}\n_{weekly_reason}_\n\n"
        f"*Daily:* {daily_bias}\n_{daily_reason}_\n\n"
        f"*Current Price:* {current_price}\n"
        f"*Draw on liquidity (up):* {liquidity_high}\n"
        f"*Draw on liquidity (down):* {liquidity_low}\n\n"
        f"*Overall Bias:* {overall}\n"
        f"_Rule-based structure analysis — always confirm with your own top-down process._"
    )


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    r = requests.post(url, data=payload, timeout=15)
    if r.status_code != 200:
        print(f"[ERROR] Telegram send failed: {r.text}")


def main():
    weekly_candles = fetch_candles("1week", outputsize=10)
    daily_candles = fetch_candles("1day", outputsize=15)

    if not weekly_candles or not daily_candles:
        print("[ERROR] Missing candle data, aborting.")
        return

    weekly_bias, weekly_reason = structure_bias(weekly_candles)
    daily_bias, daily_reason = structure_bias(daily_candles)

    current_price = daily_candles[-1]["close"]  # last known price (forming candle's latest close)
    liquidity_high, liquidity_low = draw_on_liquidity(daily_candles, current_price)

    if weekly_bias == daily_bias and weekly_bias != "NEUTRAL":
        overall = f"{weekly_bias} (HIGH PROBABILITY — Weekly + Daily aligned)"
    elif "NEUTRAL" in (weekly_bias, daily_bias):
        overall = "MIXED — one timeframe unclear, trade with caution"
    else:
        overall = "MIXED / CONFLICT — Weekly and Daily disagree, no clean bias"

    msg = format_message(
        weekly_bias, weekly_reason, daily_bias, daily_reason,
        current_price, liquidity_high, liquidity_low, overall
    )
    send_telegram(msg)
    print(msg)


if __name__ == "__main__":
    main()
