"""
Donchian Channel Breakout Bot (Quantitative Trend-Following)
==============================================================
100% rule-based, pure numerical logic - NO price-action reading, NO ICT/SMC
concepts. Based on the classic "Turtle Trading" breakout system.

Rules:
  Entry Long:  current close > highest high of the prior N_ENTRY candles
  Entry Short: current close < lowest low of the prior N_ENTRY candles
  Exit signal: price reverts to the opposite N_EXIT extreme (shorter lookback)
               - used here as a secondary "trend weakening" flag, not an
                 actual position tracker (this bot only sends directional
                 breakout alerts, it does not manage open trades).

Default: N_ENTRY = 20, N_EXIT = 10 (classic Turtle System 1 parameters).

Data: TwelveData free API (Daily candles). Alerts: Telegram (free).
State: donchian_state.json avoids duplicate alerts for the same breakout.
"""

import os
import json
import requests

SYMBOL = "XAU/USD"
INTERVAL = "1day"
N_ENTRY = 20   # breakout lookback
N_EXIT = 10    # opposite-extreme exit lookback (informational only)
OUTPUT_SIZE = N_ENTRY + 5
STATE_FILE = "donchian_state.json"

TWELVEDATA_API_KEY = os.environ["TWELVEDATA_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

TWELVEDATA_URL = "https://api.twelvedata.com/time_series"


def fetch_candles():
    params = {
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "outputsize": OUTPUT_SIZE,
        "apikey": TWELVEDATA_API_KEY,
        "order": "ASC",
        "timezone": "UTC",
    }
    resp = requests.get(TWELVEDATA_URL, params=params, timeout=20)
    data = resp.json()
    if "values" not in data:
        print(f"[WARN] No data: {data}")
        return []
    candles = []
    for row in data["values"]:
        candles.append({
            "datetime": row["datetime"],
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        })
    return candles


def check_breakout(candles):
    """
    Uses the last CLOSED candle as the signal candle, and the N candles
    strictly before it as the lookback window (excludes the signal candle
    itself, matching classic Donchian rules).
    Returns a signal dict or None.
    """
    closed = candles[:-1]  # drop still-forming candle
    if len(closed) < N_ENTRY + 1:
        return None

    signal_candle = closed[-1]
    lookback_entry = closed[-1 - N_ENTRY:-1]
    lookback_exit = closed[-1 - N_EXIT:-1]

    highest_high = max(c["high"] for c in lookback_entry)
    lowest_low = min(c["low"] for c in lookback_entry)
    exit_high = max(c["high"] for c in lookback_exit)
    exit_low = min(c["low"] for c in lookback_exit)

    close = signal_candle["close"]

    if close > highest_high:
        return {
            "direction": "LONG BREAKOUT",
            "datetime": signal_candle["datetime"],
            "close": close,
            "level_broken": highest_high,
            "trend_exit_ref": exit_low,
            "lookback": N_ENTRY,
        }
    if close < lowest_low:
        return {
            "direction": "SHORT BREAKOUT",
            "datetime": signal_candle["datetime"],
            "close": close,
            "level_broken": lowest_low,
            "trend_exit_ref": exit_high,
            "lookback": N_ENTRY,
        }
    return None


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    r = requests.post(url, data=payload, timeout=15)
    if r.status_code != 200:
        print(f"[ERROR] Telegram send failed: {r.text}")


def format_message(signal):
    return (
        f"*DONCHIAN BREAKOUT — XAU/USD (Daily)*\n\n"
        f"*Signal:* {signal['direction']}\n"
        f"*Date:* {signal['datetime']} UTC\n"
        f"*Close:* {signal['close']}\n"
        f"*{signal['lookback']}-day level broken:* {signal['level_broken']}\n"
        f"*{N_EXIT}-day opposite extreme (trend-weakening reference):* {signal['trend_exit_ref']}\n\n"
        f"_Pure quantitative trend-following signal (Donchian/Turtle rules) — "
        f"not price-action based. Confirm your own risk management before acting._"
    )


def main():
    candles = fetch_candles()
    if not candles:
        print("[ERROR] No candle data, aborting.")
        return

    signal = check_breakout(candles)
    if not signal:
        print("No Donchian breakout right now.")
        return

    state = load_state()
    key = signal["datetime"]
    if state.get(key):
        print(f"Already alerted for {key}, skipping.")
        return

    msg = format_message(signal)
    send_telegram(msg)
    print(msg)

    state[key] = True
    save_state(state)


if __name__ == "__main__":
    main()
