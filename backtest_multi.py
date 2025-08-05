# bot.py - FINAL: Focused on BTC & DOGE
# Only trade high-edge signals
# BTC: 4h Golden Cross | DOGE: 1h Momentum

import ccxt
import pandas as pd
import numpy as np
import time
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv
import os

# -------------------------------
# Load Environment Variables
# -------------------------------
load_dotenv()

# -------------------------------
# Configuration
# -------------------------------
SYMBOLS = ['BTC/USDT', 'DOGE/USDT']
TIMEFRAMES = {
    'BTC/USDT': '4h',
    'DOGE/USDT': '1h'
}
STOP_LOSS_PCT = {
    'BTC/USDT': 5.0,
    'DOGE/USDT': 7.0
}
TAKE_PROFIT_PCT = {
    'BTC/USDT': 10.0,
    'DOGE/USDT': 12.0
}
ORDER_SIZE_USD = 100  # Risk $100 per trade
DRY_RUN = True  # Set to False after testnet testing

# Telegram Alert
def send_telegram(message):
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        logging.warning("Telegram not configured")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        logging.error(f"Telegram failed: {e}")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.FileHandler('bot.log'), logging.StreamHandler()]
)

# -------------------------------
# Initialize Binance (Testnet)
# -------------------------------
exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_API_SECRET'),
    'enableRateLimit': True,
    'urls': {
        'api': {
            'public': 'https://testnet.binance.vision/api',
            'private': 'https://testnet.binance.vision/api',
        },
    },
})

# Track positions
positions = {symbol: False for symbol in SYMBOLS}
entry_prices = {symbol: None for symbol in SYMBOLS}

# -------------------------------
# ADX Indicator
# -------------------------------
def calculate_adx(high, low, close, period=14):
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0
    minus_dm = abs(minus_dm)
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period).mean()
    plus_di = (plus_dm.ewm(alpha=1/period).mean() / atr) * 100
    minus_di = (minus_dm.ewm(alpha=1/period).mean() / atr) * 100
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.ewm(alpha=1/period).mean()
    return adx

# -------------------------------
# Fetch Data
# -------------------------------
def fetch_data(symbol):
    tf = TIMEFRAMES[symbol]
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=500)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        logging.error(f"Error fetching {symbol}: {e}")
        return None

# -------------------------------
# Get Current Price
# -------------------------------
def get_price(symbol):
    try:
        return exchange.fetch_ticker(symbol)['last']
    except Exception as e:
        logging.error(f"Error: {e}")
        return None

# -------------------------------
# Place Order
# -------------------------------
def place_order(symbol, order_type):
    global positions, entry_prices
    price = get_price(symbol)
    if not price:
        return
    amount = ORDER_SIZE_USD / price

    if DRY_RUN:
        msg = f"🎯 DRY RUN: {order_type.upper()} {amount:.4f} {symbol} at ${price:.6f}"
        logging.info(msg)
        send_telegram(msg)
    else:
        try:
            exchange.create_market_order(symbol, order_type, amount)
            msg = f"✅ LIVE: {order_type.upper()} {symbol} at ${price:.6f}"
            logging.info(msg)
            send_telegram(msg)
            if order_type == 'buy':
                entry_prices[symbol] = price
        except Exception as e:
            logging.error(f"Order failed: {e}")
            send_telegram(f"❌ Order failed: {e}")
            return
    positions[symbol] = (order_type == 'buy')

# -------------------------------
# Check Exit
# -------------------------------
def check_exit(symbol):
    global positions, entry_prices
    if not positions[symbol] or entry_prices[symbol] is None:
        return
    price = get_price(symbol)
    if not price:
        return
    entry = entry_prices[symbol]
    sl = entry * (1 - STOP_LOSS_PCT[symbol] / 100)
    tp = entry * (1 + TAKE_PROFIT_PCT[symbol] / 100)

    if price >= tp:
        msg = f"🎉 TAKE-PROFIT HIT 🎉\n{symbol} → ${price:.6f}"
        logging.info(msg)
        send_telegram(msg)
        place_order(symbol, 'sell')
    elif price <= sl:
        msg = f"🚨 STOP-LOSS TRIGGERED 🚨\n{symbol} → ${price:.6f}"
        logging.warning(msg)
        send_telegram(msg)
        place_order(symbol, 'sell')

# -------------------------------
# Run Strategy
# -------------------------------
def run_strategy(symbol):
    logging.info(f"🔍 Checking {symbol}...")

    if positions[symbol]:
        check_exit(symbol)
        return

    df = fetch_data(symbol)
    if df is None or len(df) < 200:
        return

    tf = TIMEFRAMES[symbol]
    if symbol == 'BTC/USDT':
        df['SMA_s'] = df['close'].rolling(50).mean()
        df['SMA_l'] = df['close'].rolling(200).mean()
        min_adx = 25
    else:  # DOGE
        df['SMA_s'] = df['close'].rolling(10).mean()
        df['SMA_l'] = df['close'].rolling(21).mean()
        min_adx = 18

    df['ADX'] = calculate_adx(df['high'], df['low'], df['close'])
    df.dropna(inplace=True)

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    sma_cross = prev['SMA_s'] <= prev['SMA_l'] and curr['SMA_s'] > curr['SMA_l']
    strong_trend = curr['ADX'] > min_adx

    if sma_cross and strong_trend:
        msg = f"🔥 STRONG SIGNAL on {symbol}!\nADX: {curr['ADX']:.1f} | Price: ${curr['close']:.6f}"
        logging.info(msg)
        send_telegram(msg)
        place_order(symbol, 'buy')

# -------------------------------
# Main Loop
# -------------------------------
if __name__ == '__main__':
    logging.info("🚀 FINAL BOT: FOCUSED ON BTC & DOGE")
    logging.info("Using Binance Testnet (paper trading)")
    logging.info("Only trade Golden Cross (BTC) and Momentum (DOGE)")

    # Run now
    for symbol in SYMBOLS:
        run_strategy(symbol)

    # Check every hour
    while True:
        time.sleep(3600)  # 1 hour
        for symbol in SYMBOLS:
            run_strategy(symbol)