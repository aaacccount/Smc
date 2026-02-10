import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    EXCHANGE = os.getenv("EXCHANGE", "toobit")
    API_KEY = os.getenv("API_KEY", "")
    API_SECRET = os.getenv("API_SECRET", "")
    TESTNET = os.getenv("TESTNET", "True").lower() == "true"
    TRADE_MODE = os.getenv("TRADE_MODE", "futures")
    SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
    LEVERAGE = int(os.getenv("LEVERAGE", "10"))
    TF_DIRECTION = os.getenv("TF_DIRECTION", "1d")
    TF_STRUCTURE = os.getenv("TF_STRUCTURE", "4h")
    TF_ENTRY = os.getenv("TF_ENTRY", "15m")
    TF_SNIPER = os.getenv("TF_SNIPER", "5m")
    TIMEFRAME = TF_ENTRY
    HIGHER_TIMEFRAME = TF_STRUCTURE
    RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.02"))
    MAX_OPEN_TRADES = int(os.getenv("MAX_OPEN_TRADES", "3"))
    MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "0.06"))
    RISK_REWARD_RATIO = float(os.getenv("RISK_REWARD_RATIO", "2.5"))
    MAX_DRAWDOWN = float(os.getenv("MAX_DRAWDOWN", "0.15"))
    SWING_LOOKBACK = int(os.getenv("SWING_LOOKBACK", "10"))
    OB_LOOKBACK = int(os.getenv("OB_LOOKBACK", "50"))
    FVG_MIN_SIZE = float(os.getenv("FVG_MIN_SIZE", "0.001"))
    LIQUIDITY_THRESHOLD = float(os.getenv("LIQUIDITY_THRESHOLD", "3"))
    BOS_CONFIRMATION_CANDLES = int(os.getenv("BOS_CONFIRMATION_CANDLES", "3"))
    ML_ENABLED = os.getenv("ML_ENABLED", "True").lower() == "true"
    ML_RETRAIN_HOURS = int(os.getenv("ML_RETRAIN_HOURS", "24"))
    ML_MIN_SAMPLES = int(os.getenv("ML_MIN_SAMPLES", "100"))
    ML_CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.6"))
    SLEEP_BETWEEN_CYCLES = int(os.getenv("SLEEP_BETWEEN_CYCLES", "5"))
    CACHE_CANDLES = os.getenv("CACHE_CANDLES", "True").lower() == "true"
    LOW_POWER_MODE = os.getenv("LOW_POWER_MODE", "False").lower() == "true"
    LONDON_OPEN = 8; LONDON_CLOSE = 16; NY_OPEN = 13; NY_CLOSE = 21; ASIA_OPEN = 0; ASIA_CLOSE = 8
    TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "False").lower() == "true"
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
