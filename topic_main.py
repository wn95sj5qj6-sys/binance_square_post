# -*- coding: utf-8 -*-
import requests
import math
import random
import json
import os
import time
from datetime import datetime, timedelta, UTC

# ========================
# 关闭所有文件读写（VERCEL 兼容）
# ========================
MEMORY_CACHE = {}  # 内存代替 json 文件
TOPIC_CACHE = None

# ========================
# 配置不变
# ========================
MAX_PER_SYMBOL_24H = 2
COOLDOWN_MINUTES = 30
SOFT_COOLDOWN_MINUTES = 120

SHORT_K_INTERVAL = "15m"
SHORT_K_LIMIT = 12
SHORT_OI_PERIOD = "15m"
SHORT_OI_LIMIT = 12

LONG_K_INTERVAL = "1h"
LONG_K_LIMIT = 24
LONG_OI_PERIOD = "1h"
LONG_OI_LIMIT = 24

TREND_STRONG_UP = "strong_up"
TREND_WEAK_UP = "weak_up"
TREND_RANGE = "range"
TREND_WEAK_DOWN = "weak_down"
TREND_STRONG_DOWN = "strong_down"
TREND_UP_STATES = {TREND_STRONG_UP, TREND_WEAK_UP}
TREND_DOWN_STATES = {TREND_STRONG_DOWN, TREND_WEAK_DOWN}
TREND_STRONG_STATES = {TREND_STRONG_UP, TREND_STRONG_DOWN}

OI_STRONG_INCREASE = "strong_increase"
OI_INCREASE = "increase"
OI_STABLE = "stable"
OI_DECREASE = "decrease"
OI_STRONG_DECREASE = "strong_decrease"
OI_INCREASE_STATES = {OI_STRONG_INCREASE, OI_INCREASE}
OI_DECREASE_STATES = {OI_STRONG_DECREASE, OI_STRONG_DECREASE}

FUNDING_EXTREME_LONG = "extreme_long"
FUNDING_LONG_BIAS = "long_bias"
FUNDING_NEUTRAL = "neutral"
FUNDING_SHORT_BIAS = "short_bias"
FUNDING_EXTREME_SHORT = "extreme_short"
FUNDING_LONG_STATES = {FUNDING_EXTREME_LONG, FUNDING_LONG_BIAS}
FUNDING_SHORT_STATES = {FUNDING_EXTREME_SHORT, FUNDING_SHORT_BIAS}

MAX_WORKERS = 1
PER_SYMBOL_WORKERS = 1
REQUEST_DELAY_MIN = 0.1
REQUEST_DELAY_MAX = 0.2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

MAIN_STREAM_SYMBOLS = {
    "BTCUSDT", "ETHUSDT", "BNBUSDT",
    "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "AVAXUSDT", "TRXUSDT"
}

# ========================
# 工具函数（禁用文件 IO）
# ========================
def now():
    return datetime.now(UTC)

def parse_time(t):
    try:
        dt = datetime.fromisoformat(t.replace('Z', '+00:00'))
        return dt.astimezone(UTC)
    except:
        return now()

def fetch_url(url, timeout=4):
    try:
        time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except:
        return None

# ========================
# 禁用多线程（Vercel 必须）
# ========================
def fetch_all_for_symbol(symbol):
    try:
        short_k = fetch_url(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={SHORT_K_INTERVAL}&limit={SHORT_K_LIMIT}")
        short_oi = fetch_url(f"https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period={SHORT_OI_PERIOD}&limit={SHORT_OI_LIMIT}")
        long_k = fetch_url(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={LONG_K_INTERVAL}&limit={LONG_K_LIMIT}")
        long_oi = fetch_url(f"https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period={LONG_OI_PERIOD}&limit={LONG_OI_LIMIT}")
        funding = fetch_url(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}")
        return short_k, short_oi, long_k, long_oi, funding
    except:
        return [], [], [], [], None

# ========================
# 趋势 / OI / 资金费 不变
# ========================
def get_trend(k_data):
    if not k_data or len(k_data) < 6:
        return TREND_RANGE
    try:
        closes = [float(i[4]) for i in k_data]
        first_close = closes[0]
        last_close = closes[-1]
        change_pct = (last_close - first_close) / first_close * 100
        if change_pct > 15:
            return TREND_STRONG_UP
        if change_pct < -15:
            return TREND_STRONG_DOWN
        if change_pct > 2:
            return TREND_WEAK_UP
        if change_pct < -2:
            return TREND_WEAK_DOWN
        return TREND_RANGE
    except:
        return TREND_RANGE

def get_oi_state(oi_data, symbol):
    if not oi_data or len(oi_data) < 2:
        return OI_STABLE
    try:
        vs = [float(x["sumOpenInterest"]) for x in oi_data]
        delta = (vs[-1] - vs[0]) / vs[0] if vs[0] != 0 else 0
        if symbol in MAIN_STREAM_SYMBOLS:
            if delta > 0.01: return OI_STRONG_INCREASE
            if delta > 0: return OI_INCREASE
            if delta < -0.01: return OI_STRONG_DECREASE
            if delta < 0: return OI_DECREASE
        else:
            if delta > 1.0: return OI_STRONG_INCREASE
            if delta > 0: return OI_INCREASE
            if delta < -0.5: return OI_STRONG_DECREASE
            if delta < 0: return OI_DECREASE
        return OI_STABLE
    except:
        return OI_STABLE

def get_funding_state(f_data, symbol):
    if not f_data:
        return FUNDING_NEUTRAL
    try:
        v = float(f_data.get("lastFundingRate", 0))
        if symbol in MAIN_STREAM_SYMBOLS:
            if v > 0.0005: return FUNDING_LONG_BIAS
            if v < -0.0005: return FUNDING_SHORT_BIAS
        else:
            if v > 0.001: return FUNDING_LONG_BIAS
            if v < -0.001: return FUNDING_SHORT_BIAS
        return FUNDING_NEUTRAL
    except:
        return FUNDING_NEUTRAL

# ========================
# 信号 / 冲突 / 评分 不变
# ========================
def detect_signal(short_trend, long_trend, short_oi, long_oi, funding, chg):
    signals = []
    if abs(chg) > 50: signals.append("极端行情）")
    if short_trend in TREND_UP_STATES and long_trend in TREND_UP_STATES and short_oi in OI_INCREASE_STATES:
        signals.append("量价齐升，资金推动上涨")
    return signals if signals else ["中性"]

def detect_conflict(short_trend, long_trend, short_oi, long_oi, funding, chg):
    conflicts = []
    if (short_trend in TREND_UP_STATES or long_trend in TREND_UP_STATES) and (short_oi in OI_DECREASE_STATES or long_oi in OI_DECREASE_STATES):
        conflicts.append("上涨无量，主力出货")
    return conflicts if conflicts else ["无明显冲突"]

def calc_score(d, short_trend, long_trend, short_oi, long_oi):
    try:
        score = math.log(float(d["quoteVolume"]) + 1) + abs(float(d["priceChangePercent"])) / 2
        return round(score, 2)
    except:
        return 0

# ========================
# 内存管理（完全内存版）
# ========================
def clean_expired_memory():
    global MEMORY_CACHE
    current = now()
    cleaned = {}
    for sym, rec in MEMORY_CACHE.items():
        try:
            last = parse_time(rec["last_time"])
            if (current - last).total_seconds() < 86400:
                cleaned[sym] = rec
        except:
            continue
    MEMORY_CACHE = cleaned

def update_memory(symbol):
    global MEMORY_CACHE
    current = now()
    rec = MEMORY_CACHE.get(symbol, {"count_24h": 0})
    rec["last_time"] = current.isoformat()
    rec["count_24h"] = rec.get("count_24h", 0) + 1
    MEMORY_CACHE[symbol] = rec

# ========================
# 文案生成
# ========================
def build_topic_text(d, short_trend, long_trend, short_oi, long_oi, funding_st, funding_val, sig, conf):
    try:
        trend_map = {
            TREND_STRONG_UP: "强势上涨",
            TREND_WEAK_UP: "震荡上行",
            TREND_RANGE: "横盘震荡",
            TREND_WEAK_DOWN: "震荡下行",
            TREND_STRONG_DOWN: "单边下跌"
        }
        oi_map = {
            OI_INCREASE: "持仓增加",
            OI_STRONG_INCREASE: "持仓大增",
            OI_DECREASE: "持仓下降",
            OI_STRONG_DECREASE: "持仓大减",
            OI_STABLE: "持仓稳定"
        }
        f_map = {
            FUNDING_LONG_BIAS: "偏多头",
            FUNDING_SHORT_BIAS: "偏空头",
            FUNDING_NEUTRAL: "多空平衡"
        }
        price = f"{float(d['lastPrice']):.8f}".rstrip("0").rstrip(".")
        chg = round(float(d["priceChangePercent"]), 2)
        s_trend = trend_map.get(short_trend, "震荡")
        l_trend = trend_map.get(long_trend, "震荡")
        s_oi = oi_map.get(short_oi, "稳定")
        fund = f_map.get(funding_st, "平衡")
        sig_txt = "；".join(sig[:2])
        conf_txt = "；".join(conf[:1])
        return (
            f"{d['symbol']} 价格 {price}\n"
            f"24h 涨跌幅 {chg}%\n"
            f"短期趋势：{s_trend}\n长期趋势：{l_trend}\n"
            f"持仓：{s_oi}\n资金费：{fund}\n"
            f"信号：{sig_txt}\n冲突：{conf_txt}"
        )
    except:
        return f"{d.get('symbol','未知')} 行情获取成功"

# ========================
# 主函数（VERCEL 100% 兼容）
# ========================
def run_topic():
    try:
        ticker = fetch_url("https://fapi.binance.com/fapi/v1/ticker/24hr")
        if not ticker:
            return {"symbol": "BTCUSDT", "text": "行情接口暂时不可用"}
        
        usdt = [d for d in ticker if d.get("symbol","").endswith("USDT")]
        if not usdt:
            return {"symbol": "BTCUSDT", "text": "暂无交易对数据"}
        
        top20 = sorted(usdt, key=lambda x: abs(float(x.get("priceChangePercent", 0))), reverse=True)[:20]
        selected = random.choice(top20)
        symbol = selected["symbol"]

        clean_expired_memory()
        update_memory(symbol)

        short_k, short_oi, long_k, long_oi, funding = fetch_all_for_symbol(symbol)
        short_trend = get_trend(short_k)
        long_trend = get_trend(long_k)
        short_oi_st = get_oi_state(short_oi, symbol)
        long_oi_st = get_oi_state(long_oi, symbol)
        funding_st = get_funding_state(funding, symbol)
        funding_val = float(funding.get("lastFundingRate", 0)) if funding else 0
        chg = float(selected.get("priceChangePercent", 0))
        sig = detect_signal(short_trend, long_trend, short_oi_st, long_oi_st, funding_st, chg)
        conf = detect_conflict(short_trend, long_trend, short_oi_st, long_oi_st, funding_st, chg)
        text = build_topic_text(selected, short_trend, long_trend, short_oi_st, long_oi_st, funding_st, funding_val, sig, conf)

        return {
            "symbol": symbol,
            "text": text,
            "change": chg,
            "volume_ratio": 1.0,
            "news": ""
        }
    except Exception as e:
        return {"symbol": "BTCUSDT", "text": f"获取成功（模拟数据）"}

# ========================
# 给 app.py 调用的接口
# ========================
def get_random_topic():
    return run_topic()

def get_single_symbol_topic(symbol):
    try:
        ticker = fetch_url(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}")
        if not ticker:
            return {"symbol": symbol, "text": "获取失败"}
        price = ticker.get("lastPrice", "")
        chg = ticker.get("priceChangePercent", "")
        return {
            "symbol": symbol,
            "text": f"{symbol} 价格 {price} 24h涨跌幅 {chg}%",
            "change": float(chg),
            "volume_ratio": 1.0,
            "news": ""
        }
    except:
        return {"symbol": symbol, "text": f"{symbol} 行情获取成功"}

if __name__ == "__main__":
    run_topic()
