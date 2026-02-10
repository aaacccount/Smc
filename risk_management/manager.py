import json,os
from datetime import datetime
from config import Config
from utils.logger import setup_logger
logger=setup_logger("Risk")
HF="data/risk_history.json"

class RiskManager:
    """Risk Management with Smart Trailing TP"""

    def __init__(s):
        s.config=Config();s.daily_pnl=0;s.daily_trades=0
        s.last_reset=datetime.utcnow().date();s.trade_history=[]
        s.peak_balance=0;s.consecutive_losses=0;s._load()

    def _load(s):
        try:
            if os.path.exists(HF):
                with open(HF) as f:
                    d=json.load(f);s.trade_history=d.get("history",[])
                    s.peak_balance=d.get("peak_balance",0)
        except:pass

    def _save(s):
        try:
            os.makedirs("data",exist_ok=True)
            with open(HF,"w") as f:
                json.dump({"history":s.trade_history[-500:],
                    "peak_balance":s.peak_balance},f,indent=2,default=str)
        except:pass

    def calculate_position_size(s,balance,entry,sl,confidence=1.0,ml_conf=0.5):
        s._reset()
        if entry==0 or sl==0:return 0
        rp=s.config.RISK_PER_TRADE*confidence
        if ml_conf>0.7:rp*=1.2
        elif ml_conf<0.4:rp*=0.5
        if s.consecutive_losses>=2:rp*=max(0.3,1-s.consecutive_losses*0.15)
        ra=balance*rp;ru=abs(entry-sl)
        if ru==0:return 0
        ps=ra/ru;mx=(balance*s.config.LEVERAGE*0.95)/entry
        return round(min(ps,mx),6)

    def can_open_trade(s,balance):
        s._reset()
        if s.daily_trades>=s.config.MAX_OPEN_TRADES:
            return {"allowed":False,"reason":"Max trades"}
        if s.daily_pnl<=-balance*s.config.MAX_DAILY_LOSS:
            return {"allowed":False,"reason":"Daily loss limit"}
        if s.peak_balance>0 and (s.peak_balance-balance)/s.peak_balance>=s.config.MAX_DRAWDOWN:
            return {"allowed":False,"reason":"Max drawdown"}
        if s.consecutive_losses>=4:
            return {"allowed":False,"reason":"Cool-down"}
        return {"allowed":True,"reason":""}

    def update_trade_result(s,pnl,balance=0):
        s.daily_pnl+=pnl;s.daily_trades+=1
        if pnl>0:s.consecutive_losses=0
        else:s.consecutive_losses+=1
        if balance>s.peak_balance:s.peak_balance=balance
        s.trade_history.append({"timestamp":str(datetime.utcnow()),
            "pnl":pnl,"balance":balance})
        s._save()

    def smart_tp_management(s, entry, current_price, direction, 
                            current_sl, original_sl, taken_parts=0, atr=None):
        """
        Smart TP Management - پلکانی هوشمند

        مرحله 0: ورود
          SL = original_sl
          TP1 = 1R

        مرحله 1: رسیدن به 1R
          ببند 30%
          SL → Break-even (entry + 0.1R)
          TP2 = 2R

        مرحله 2: رسیدن به 2R
          ببند 30%
          SL → 1R (جایگزین TP1)
          TP3 = 3R

        مرحله 3: رسیدن به 3R
          ببند 20%
          SL → 2R
          بقیه 20% = trailing stop

        مرحله 4+: Trailing
          SL = price - ATR*1.0
          تا وقتی روند برنگشته
        """
        if atr is None:
            atr = abs(entry - original_sl)

        risk = abs(entry - original_sl)
        if risk == 0:
            return {"action": "hold", "new_sl": current_sl}

        result = {
            "action": "hold",
            "new_sl": current_sl,
            "close_portion": 0,
            "new_tp": None,
            "r_level": 0,
            "trailing": False,
        }

        if direction == "long":
            current_r = (current_price - entry) / risk
        else:
            current_r = (entry - current_price) / risk

        # ── Stage 1: Hit 1R ──
        if taken_parts == 0 and current_r >= 1.0:
            result["action"] = "partial_close"
            result["close_portion"] = 0.30
            result["r_level"] = 1.0

            # SL → Break-even
            if direction == "long":
                result["new_sl"] = round(entry + risk * 0.1, 2)
                result["new_tp"] = round(entry + risk * 2.0, 2)
            else:
                result["new_sl"] = round(entry - risk * 0.1, 2)
                result["new_tp"] = round(entry - risk * 2.0, 2)

            logger.info(f"  Smart TP: 1R hit! Close 30%, SL→BE, TP→2R")

        # ── Stage 2: Hit 2R ──
        elif taken_parts == 1 and current_r >= 2.0:
            result["action"] = "partial_close"
            result["close_portion"] = 0.30
            result["r_level"] = 2.0

            # SL → 1R level (was TP1)
            if direction == "long":
                result["new_sl"] = round(entry + risk * 1.0, 2)
                result["new_tp"] = round(entry + risk * 3.0, 2)
            else:
                result["new_sl"] = round(entry - risk * 1.0, 2)
                result["new_tp"] = round(entry - risk * 3.0, 2)

            logger.info(f"  Smart TP: 2R hit! Close 30%, SL→1R, TP→3R")

        # ── Stage 3: Hit 3R ──
        elif taken_parts == 2 and current_r >= 3.0:
            result["action"] = "partial_close"
            result["close_portion"] = 0.20
            result["r_level"] = 3.0
            result["trailing"] = True

            # SL → 2R level
            if direction == "long":
                result["new_sl"] = round(entry + risk * 2.0, 2)
            else:
                result["new_sl"] = round(entry - risk * 2.0, 2)

            logger.info(f"  Smart TP: 3R hit! Close 20%, SL→2R, rest=trailing")

        # ── Stage 4+: Trailing the remaining 20% ──
        elif taken_parts >= 3 and current_r >= 3.0:
            result["action"] = "trail"
            result["trailing"] = True

            trail_distance = atr * 0.8

            if direction == "long":
                trail_sl = round(current_price - trail_distance, 2)
                if trail_sl > current_sl:
                    result["new_sl"] = trail_sl
                    logger.debug(f"  Trail: SL→${trail_sl:,.2f} ({current_r:.1f}R)")
            else:
                trail_sl = round(current_price + trail_distance, 2)
                if trail_sl < current_sl:
                    result["new_sl"] = trail_sl
                    logger.debug(f"  Trail: SL→${trail_sl:,.2f} ({current_r:.1f}R)")

        # ── Standard trailing for lower stages ──
        elif current_r >= 0.5 and taken_parts < 3:
            trail_distance = atr * 1.2
            if direction == "long":
                trail_sl = round(current_price - trail_distance, 2)
                if trail_sl > current_sl:
                    result["new_sl"] = trail_sl
            else:
                trail_sl = round(current_price + trail_distance, 2)
                if trail_sl < current_sl:
                    result["new_sl"] = trail_sl

        return result

    def should_break_even(s, entry, price, direction, sl):
        """Legacy break-even (used by non-smart-tp mode)"""
        r = abs(entry - sl)
        if direction == "long" and price >= entry + r:
            return round(entry + r * 0.1, 2)
        if direction == "short" and price <= entry - r:
            return round(entry - r * 0.1, 2)
        return None

    def calculate_trailing_stop(s, entry, price, direction, sl, atr=None):
        """Legacy trailing stop"""
        if atr is None: atr = entry * 0.01
        t = atr * 1.2
        if direction == "long" and (price - entry) / entry > 0.01:
            ns = price - t
            if ns > sl: return round(ns, 2)
        elif direction == "short" and (entry - price) / entry > 0.01:
            ns = price + t
            if ns < sl: return round(ns, 2)
        return sl

    def partial_take_profit(s, entry, price, direction, sl, taken=0):
        """Legacy partial TP"""
        r = abs(entry - sl)
        targets = [1.0, 2.0, 3.0]
        if taken >= len(targets): return None
        tr = targets[taken]
        if direction == "long" and price >= entry + r * tr:
            return {"price": entry + r * tr, "portion": 0.33, "r_level": tr}
        if direction == "short" and price <= entry - r * tr:
            return {"price": entry - r * tr, "portion": 0.33, "r_level": tr}
        return None

    def _reset(s):
        t = datetime.utcnow().date()
        if t != s.last_reset:
            s.daily_pnl = 0; s.daily_trades = 0; s.last_reset = t

    def get_stats(s):
        if not s.trade_history:
            return {"total_trades":0,"win_rate":0,"total_pnl":0,
                "daily_pnl":0,"daily_trades":0,"consecutive_losses":0,
                "peak_balance":0,"profit_factor":0}
        pnls = [t["pnl"] for t in s.trade_history]
        w = [p for p in pnls if p > 0]
        l = [p for p in pnls if p <= 0]
        return {
            "total_trades": len(pnls),
            "win_rate": round(len(w) / max(len(pnls), 1) * 100, 1),
            "avg_win": round(sum(w) / max(len(w), 1), 2),
            "avg_loss": round(sum(l) / max(len(l), 1), 2),
            "total_pnl": round(sum(pnls), 2),
            "daily_pnl": round(s.daily_pnl, 2),
            "daily_trades": s.daily_trades,
            "consecutive_losses": s.consecutive_losses,
            "peak_balance": round(s.peak_balance, 2),
            "profit_factor": round(abs(sum(w)) / max(abs(sum(l)), 1), 2) if l else 999,
        }
