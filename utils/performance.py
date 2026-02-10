import time, gc, pandas as pd
from datetime import datetime, timedelta
from config import Config
from utils.logger import setup_logger
logger = setup_logger("Performance")

class CandleCache:
    def __init__(self):
        self.cache = {}
        self.expiry = {}
        self.hit = 0
        self.miss = 0

    def get(self, key):
        if key in self.cache and datetime.utcnow() < self.expiry.get(key, datetime.min):
            self.hit += 1
            return self.cache[key].copy()
        self.miss += 1
        return None

    def set(self, key, df, ttl=60):
        self.cache[key] = df.copy()
        self.expiry[key] = datetime.utcnow() + timedelta(seconds=ttl)

    def clear_expired(self):
        now = datetime.utcnow()
        expired = [k for k,v in self.expiry.items() if now >= v]
        for k in expired:
            del self.cache[k]
            del self.expiry[k]

    def stats(self):
        t = self.hit + self.miss
        return {"hits": self.hit, "misses": self.miss, "rate": f"{self.hit/max(t,1)*100:.0f}%", "cached": len(self.cache)}

class PerformanceManager:
    def __init__(self):
        self.config = Config()
        self.candle_cache = CandleCache()
        self.cycle_times = []
        self.last_gc = datetime.utcnow()

    def get_tf_ttl(self, tf):
        return {"1m":50,"3m":150,"5m":250,"15m":800,"30m":1700,"1h":3400,"4h":13000,"1d":80000}.get(tf, 300)

    def get_cached_candles(self, exchange, symbol, tf, limit=500):
        if not self.config.CACHE_CANDLES:
            return exchange.fetch_ohlcv(symbol, tf, limit)
        key = f"{symbol}_{tf}"
        cached = self.candle_cache.get(key)
        if cached is not None:
            return cached
        df = exchange.fetch_ohlcv(symbol, tf, limit)
        if not df.empty:
            self.candle_cache.set(key, df, self.get_tf_ttl(tf))
        return df

    def optimize_memory(self):
        if (datetime.utcnow() - self.last_gc).total_seconds() > 300:
            self.candle_cache.clear_expired()
            gc.collect()
            self.last_gc = datetime.utcnow()

    def get_sleep_time(self):
        tf = self.config.TF_ENTRY
        base = {"1m":55,"3m":170,"5m":290,"15m":890,"30m":1790,"1h":3590,"4h":14390}.get(tf, 890)
        return int(base * 1.5) if self.config.LOW_POWER_MODE else base

    def record_cycle_time(self, s):
        self.cycle_times.append(s)
        if len(self.cycle_times) > 100:
            self.cycle_times = self.cycle_times[-100:]

    def get_stats(self):
        avg = sum(self.cycle_times)/max(len(self.cycle_times),1)
        return {"avg_cycle_time": f"{avg:.2f}s", "cache": self.candle_cache.stats()}
