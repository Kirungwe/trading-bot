# backtest_focus.py - Clean, no emojis, no testnet

import pandas as pd
import numpy as np
import ccxt
import time
import logging

# Set up logging (no emojis)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s'
)

# Configuration
SYMBOLS = ['BTC/USDT', 'DOGE/USDT']
TIMEFRAMES = {'BTC/USDT': '4h', 'DOGE/USDT': '1h'}
DAYS = 365
FEE = 0.0002 * 2  # 0.02% x2

# Use real Binance (no testnet, no API keys needed for OHLCV)
exchange = ccxt.binance({'enableRateLimit': True})

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

def backtest_symbol(symbol):
    logging.info(f"BACKTESTING {symbol}...")
    tf = TIMEFRAMES[symbol]
    since = exchange.milliseconds() - (DAYS * 24 * 60 * 60 * 1000)
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=tf, since=since)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    except Exception as e:
        logging.error(f"Error fetching {symbol}: {e}")
        return None

    if symbol == 'BTC/USDT':
        df['SMA_s'] = df['close'].rolling(50).mean()
        df['SMA_l'] = df['close'].rolling(200).mean()
        min_adx = 25
        sl, tp = 0.05, 0.10
    else:
        df['SMA_s'] = df['close'].rolling(10).mean()
        df['SMA_l'] = df['close'].rolling(21).mean()
        min_adx = 18
        sl, tp = 0.07, 0.12

    df['ADX'] = calculate_adx(df['high'], df['low'], df['close'])
    df.dropna(inplace=True)

    trades = []
    in_position = False
    entry_price = None

    for i in range(1, len(df)):
        curr = df.iloc[i]
        prev = df.iloc[i-1]

        if not in_position:
            cross = prev['SMA_s'] <= prev['SMA_l'] and curr['SMA_s'] > curr['SMA_l']
            strong = curr['ADX'] > min_adx
            if cross and strong:
                in_position = True
                entry_price = curr['close']

        elif in_position:
            price = curr['close']
            if price >= entry_price * (1 + tp):
                profit = (price / entry_price - 1) * 100 - FEE * 100
                trades.append({'symbol': symbol, 'profit': profit, 'reason': 'TP'})
                in_position = False
            elif price <= entry_price * (1 - sl):
                profit = (price / entry_price - 1) * 100 - FEE * 100
                trades.append({'symbol': symbol, 'profit': profit, 'reason': 'SL'})
                in_position = False

    return trades

# Run backtest
all_trades = []
for symbol in SYMBOLS:
    trades = backtest_symbol(symbol)
    if trades:
        all_trades.extend(trades)
    time.sleep(1)

if all_trades:
    df = pd.DataFrame(all_trades)
    win_rate = (df['profit'] > 0).mean() * 100
    net_return = df['profit'].sum()
    print(f"\n✅ FINAL: {len(df)} trades | Win Rate: {win_rate:.1f}% | Net Return: {net_return:.2f}%")
    print(df.groupby('symbol').agg({'profit': ['count', 'mean', lambda x: (x>0).mean()*100]}))
else:
    print("❌ No trades generated.")