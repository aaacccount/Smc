import requests
from config import Config
from utils.logger import setup_logger
logger = setup_logger("Notifier")

class TelegramNotifier:
    def __init__(self):
        c = Config()
        self.enabled = c.TELEGRAM_ENABLED
        self.token = c.TELEGRAM_TOKEN
        self.chat_id = c.TELEGRAM_CHAT_ID

    def send(self, message, parse_mode="HTML"):
        if not self.enabled or not self.token:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            resp = requests.post(url, data={"chat_id": self.chat_id, "text": message, "parse_mode": parse_mode}, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Telegram: {e}")
            return False

    def send_signal(self, data):
        if not self.enabled: return
        emoji = {"STRONG_BUY":"🟢🟢","BUY":"🟢","STRONG_SELL":"🔴🔴","SELL":"🔴"}.get(data.get("signal",""),"⚪")
        self.send(f"{emoji} <b>{data.get('signal')}</b>\n📊 {data.get('symbol')}\n💰 Entry: {data.get('entry')}\n🛑 SL: {data.get('stop_loss')}\n🎯 TP: {data.get('take_profit')}\n📊 Conf: {data.get('confidence',0):.0%}")

    def send_trade_result(self, pnl, balance):
        if not self.enabled: return
        self.send(f"{'✅' if pnl>0 else '❌'} PnL: {pnl:+.2f} | Balance: {balance:.2f}")
