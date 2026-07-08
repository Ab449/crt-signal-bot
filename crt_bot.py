"""
CRT (Candle Range Theory) Free Signal Bot
==========================================
100% rule-based (NO AI / NO paid API). Detects ICT-style CRT liquidity-sweep
setups on XAU/USD across multiple timeframes and sends free Telegram alerts.

CRT logic (per timeframe):
  Candle 1 (base)          -> defines a liquidity range: high1 / low1
  Candle 2 (manipulation)  -> sweeps ONE side of that range (wick beyond
                               high1 or low1) then CLOSES back inside the range
  => Signal confirmed the moment Candle 2 closes back inside the range.
     Bullish CRT: low2 < low1  AND  close2 > low1   (sell-side liquidity swept)
     Bearish CRT: high2 > high1 AND close2 < high1  (buy-side liquidity swept)

Entry idea given: retrace into the 50%-79% of Candle 2's real range (OTE-style),
Stop: beyond the wick of Candle 2, Target: opposite side of Candle 1's range
(nearest untouched liquidity) projected 1:2 minimum.

Data source: TwelveData free API (https://twelvedata.com) - 800 req/day free.
Alerts: Telegram Bot API (free).
State: state.json committed back to the repo so we never send duplicate
alerts for the same candle.
"""

import os
import json
import requests
from datetime import datetime, timezone

# ---------- CONFIG ----------
SYMBOL = "XAU/USD"
TIMEFRAMES = ["4h", "1h", "15min"]   # TwelveData interval strings
CANDLES_TO_FETCH = 20
STATE_FILE = "state.json"

TWELVEDATA_API_KEY = os.environ["TWELVEDATA_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

TWELVEDATA_URL = "https://api.twelvedata.com/time_series"


# ---------- DATA FETCH ----------
def fetch_candles(interval: str):
    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "outputsize": CANDLES_TO_FETCH,
        "apikey": TWELVEDATA_API_KEY,
        "order": "ASC",  # oldest -> newest
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
    return candles  # oldest -> newest


# ---------- CRT DETECTION ----------
def detect_crt(candles):
    """
    Looks at the last CLOSED pair of candles: [-3]=base, [-2]=manipulation.
    (The most recent candle [-1] is still forming, so we don't use it as
    confirmation to avoid false signals mid-candle.)
    Returns a signal dict or None.
    """
    if len(candles) < 3:
        return None

    base = candles[-3]
    manip = candles[-2]

    high1, low1 = base["high"], base["low"]
    high2, low2, close2 = manip["high"], manip["low"], manip["close"]

    # Bullish CRT: sweep sell-side liquidity (low1) then close back inside
    if low2 < low1 and close2 > low1:
        entry_low = low2 + (close2 - low2) * 0.21   # ~79% retrace level
        entry_high = low2 + (close2 - low2) * 0.50  # ~50% retrace level
        stop = low2 * 0.999  # just beyond the sweep wick
        target = high1
        rr = round((target - entry_high) / (entry_high - stop), 2) if entry_high != stop else 0
        return {
            "direction": "BULLISH",
            "base_time": base["datetime"],
            "manip_time": manip["datetime"],
            "base_range": (low1, high1),
            "sweep_low": low2,
            "entry_zone": (round(entry_low, 2), round(entry_high, 2)),
            "stop": round(stop, 2),
            "target": round(target, 2),
            "rr": rr,
        }

    # Bearish CRT: sweep buy-side liquidity (high1) then close back inside
    if high2 > high1 and close2 < high1:
        entry_high = high2 - (high2 - close2) * 0.21
        entry_low = high2 - (high2 - close2) * 0.50
        stop = high2 * 1.001
        target = low1
        rr = round((entry_low - target) / (stop - entry_low), 2) if stop != entry_low else 0
        return {
            "direction": "BEARISH",
            "base_time": base["datetime"],
            "manip_time": manip["datetime"],
            "base_range": (low1, high1),
            "sweep_high": high2,
            "entry_zone": (round(entry_low, 2), round(entry_high, 2)),
            "stop": round(stop, 2),
            "target": round(target, 2),
            "rr": rr,
        }

    return None


# ---------- STATE (avoid duplicate alerts) ----------
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ---------- TELEGRAM ----------
def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    r = requests.post(url, data=payload, timeout=15)
    if r.status_code != 200:
        print(f"[ERROR] Telegram send failed: {r.text}")


def format_message(tf, signal):
    return (
        f"*CRT SIGNAL — XAU/USD ({tf})*\n"
        f"Direction: *{signal['direction']}*\n"
        f"Base candle range: {signal['base_range'][0]} - {signal['base_range'][1]}\n"
        f"Manipulation candle: {signal['manip_time']}\n"
        f"Entry zone (OTE): {signal['entry_zone'][0]} - {signal['entry_zone'][1]}\n"
        f"Stop Loss: {signal['stop']}\n"
        f"Target: {signal['target']}\n"
        f"R:R (approx): {signal['rr']}\n"
        f"_Rule-based CRT detection — always confirm with your own top-down analysis._"
    )


# ---------- MAIN ----------
def main():
    state = load_state()
    utc_now = datetime.now(timezone.utc).isoformat()

    for tf in TIMEFRAMES:
        candles = fetch_candles(tf)
        if not candles:
            continue

        signal = detect_crt(candles)
        if signal is None:
            print(f"[{tf}] No CRT setup right now.")
            continue

        state_key = f"{tf}_{signal['manip_time']}"
        if state.get(state_key):
            print(f"[{tf}] Signal already alerted for {signal['manip_time']}, skipping.")
            continue

        msg = format_message(tf, signal)
        send_telegram(msg)
        print(f"[{tf}] Signal sent:\n{msg}")

        state[state_key] = utc_now

    save_state(state)


if __name__ == "__main__":
    main()
