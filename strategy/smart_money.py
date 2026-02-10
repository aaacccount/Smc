import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Dict, List
from config import Config
from strategy.market_structure import MarketStructure
from strategy.order_blocks import OrderBlockDetector
from strategy.liquidity import LiquidityAnalyzer
from strategy.mtf_analyzer import MTFAnalyzer
from utils.logger import setup_logger
logger = setup_logger("SmartMoney")


class SmartMoneyStrategy:
    """Smart Money Strategy - Pro Version with all enhancements"""

    def __init__(self):
        self.config = Config()
        self.ms = MarketStructure()
        self.ob = OrderBlockDetector()
        self.liq = LiquidityAnalyzer()
        self.mtf = MTFAnalyzer()

    def analyze(self, df, htf_df=None, direction_df=None, sniper_df=None):
        result = {
            "signal": "NO_SIGNAL", "direction": None, "confidence": 0,
            "entry": None, "stop_loss": None, "take_profit": None,
            "analysis": {}, "features": {},
        }

        if len(df) < 50:
            return result

        if direction_df is not None or sniper_df is not None:
            return self._mtf_analyze(df, htf_df, direction_df, sniper_df)

        return self._legacy_analyze(df, htf_df)

    def _mtf_analyze(self, entry_df, structure_df, direction_df, sniper_df):
        tf_data = {
            "direction": direction_df,
            "structure": structure_df,
            "entry": entry_df,
            "sniper": sniper_df,
        }
        mtf_result = self.mtf.analyze_all_timeframes(tf_data)
        features = self._extract_features(entry_df,
            self.ms.detect_structure(entry_df), "neutral",
            None, [], [], {"zone": "equilibrium"}, 0, 0)

        result = {
            "signal": mtf_result["final_signal"],
            "direction": mtf_result.get("direction"),
            "confidence": mtf_result.get("confidence", 0),
            "entry": mtf_result.get("entry_price"),
            "stop_loss": mtf_result.get("stop_loss"),
            "take_profit": mtf_result.get("take_profit"),
            "analysis": {
                "mode": "MTF_4TF",
                "direction_bias": mtf_result["direction_bias"],
                "structure_trend": mtf_result["structure_trend"],
                "entry_signal": mtf_result["entry_signal"],
                "sniper_confirmed": mtf_result["sniper_confirmed"],
                "confluence_score": mtf_result["confluence_score"],
            },
            "features": features,
        }
        for k in ["entry", "stop_loss", "take_profit"]:
            if result[k] is not None:
                result[k] = round(result[k], 2)
        return result

    def _legacy_analyze(self, df, htf_df):
        result = {
            "signal": "NO_SIGNAL", "direction": None, "confidence": 0,
            "entry": None, "stop_loss": None, "take_profit": None,
            "analysis": {}, "features": {},
        }

        structure = self.ms.detect_structure(df)
        result["analysis"]["structure"] = structure["trend"]
        result["analysis"]["mode"] = "Pro_2TF"

        htf_bias = "neutral"
        if htf_df is not None and len(htf_df) > 50:
            htf_structure = self.ms.detect_structure(htf_df)
            htf_bias = htf_structure["trend"]
        result["analysis"]["htf_bias"] = htf_bias

        # Pro OB detection with HTF alignment
        obs = self.ob.find_order_blocks(df, htf_df)
        sweeps = self.liq.detect_liquidity_sweep(df)
        fvgs = self.liq.find_fvg(df)
        pd_zone = self.ms.get_premium_discount(df)

        result["analysis"]["order_blocks"] = len(obs)
        result["analysis"]["sweeps"] = len(sweeps)
        result["analysis"]["fvgs"] = len(fvgs)
        result["analysis"]["zone"] = pd_zone["zone"]

        # Kill Zone with proper scoring
        kz = self._kill_zone_score()
        result["analysis"]["kill_zone"] = kz

        # Best OBs
        best_bull_ob = self.ob.get_best_ob(df, "long", htf_df)
        best_bear_ob = self.ob.get_best_ob(df, "short", htf_df)

        # Volume Profile zones
        vp_zones = self.ob.volume_profile_lite(htf_df if htf_df is not None else df)
        result["analysis"]["vp_zones"] = len(vp_zones)

        # Confluence scoring
        bull, bear = self._pro_confluence(
            structure, htf_bias, best_bull_ob, best_bear_ob,
            sweeps, fvgs, pd_zone, kz, vp_zones, df
        )

        result["analysis"]["bull_score"] = bull
        result["analysis"]["bear_score"] = bear

        result["features"] = self._extract_features(
            df, structure, htf_bias, best_bull_ob,
            sweeps, fvgs, pd_zone, bull, bear
        )

        sig = self._generate_signal_pro(
            bull, bear, df, best_bull_ob, best_bear_ob, structure, kz
        )
        result.update(sig)
        return result

    def _kill_zone_score(self):
        """Kill Zone با امتیاز واقعی"""
        h = datetime.utcnow().hour

        # London-NY Overlap (best time)
        if 13 <= h < 16:
            return {"name": "London-NY Overlap", "score": 2.0, "quality": "BEST"}
        # London Open
        elif 8 <= h < 10:
            return {"name": "London Open", "score": 1.5, "quality": "GREAT"}
        # NY Open
        elif 13 <= h < 15:
            return {"name": "NY Open", "score": 1.5, "quality": "GREAT"}
        # London Session
        elif 10 <= h < 13:
            return {"name": "London", "score": 1.0, "quality": "GOOD"}
        # NY Session
        elif 15 <= h < 21:
            return {"name": "New York", "score": 1.0, "quality": "GOOD"}
        # Asia
        elif 0 <= h < 8:
            return {"name": "Asia", "score": 0.0, "quality": "AVOID"}
        else:
            return {"name": "Off", "score": -0.5, "quality": "AVOID"}

    def _pro_confluence(self, structure, htf_bias, bull_ob, bear_ob,
                        sweeps, fvgs, pd_zone, kz, vp_zones, df):
        """Pro Confluence Scoring"""
        bull = bear = 0
        price = df["close"].iloc[-1]

        # 1. Structure (2)
        if structure["trend"] == "bullish":
            bull += 2
        elif structure["trend"] == "bearish":
            bear += 2

        # 2. HTF Bias (2)
        if htf_bias == "bullish":
            bull += 2
        elif htf_bias == "bearish":
            bear += 2

        # 3. OB Score (0-5) - uses total_score from OB detector
        if bull_ob:
            ob_score = min(bull_ob["total_score"] / 3, 5)
            bull += ob_score
            if bull_ob["has_fvg"]:
                bull += 0.5  # Bonus for FVG
            if bull_ob["is_fresh"]:
                bull += 0.5  # Bonus for fresh

        if bear_ob:
            ob_score = min(bear_ob["total_score"] / 3, 5)
            bear += ob_score
            if bear_ob["has_fvg"]:
                bear += 0.5
            if bear_ob["is_fresh"]:
                bear += 0.5

        # 4. Sweep (1.5)
        for s in sweeps[-3:]:
            if s["type"] == "bullish_sweep":
                bull += 1.5
                break
            elif s["type"] == "bearish_sweep":
                bear += 1.5
                break

        # 5. Premium/Discount (1)
        if pd_zone["zone"] in ["discount", "slight_discount"]:
            bull += 1
        elif pd_zone["zone"] in ["premium", "slight_premium"]:
            bear += 1

        # 6. Kill Zone (0-2)
        kz_score = kz["score"]
        if kz_score > 0:
            bull += kz_score * 0.5
            bear += kz_score * 0.5

        # 7. BOS/CHoCH (1.5)
        for b in structure["bos_levels"]:
            if b["type"] == "bullish_bos":
                bull += 1.5
                break
            elif b["type"] == "bearish_bos":
                bear += 1.5
                break

        for c in structure["choch_levels"]:
            if c["type"] == "bullish_choch":
                bull += 1
            elif c["type"] == "bearish_choch":
                bear += 1

        # 8. Volume Profile zones (1)
        for zone in vp_zones:
            if zone["type"] == "demand":
                dist = abs(price - zone["mid"]) / price
                if dist < 0.005:
                    bull += 1
                    break
            elif zone["type"] == "supply":
                dist = abs(price - zone["mid"]) / price
                if dist < 0.005:
                    bear += 1
                    break

        return round(bull, 1), round(bear, 1)

    def _generate_signal_pro(self, bull, bear, df, bull_ob, bear_ob, structure, kz):
        """Pro Signal Generation with smart SL/TP"""
        price = df["close"].iloc[-1]
        atr = self.calculate_atr(df)
        rr = self.config.RISK_REWARD_RATIO

        sig = {
            "signal": "NO_SIGNAL", "direction": None, "confidence": 0,
            "entry": None, "stop_loss": None, "take_profit": None,
            "ob_score": 0, "kz_quality": kz["quality"],
        }

        # Avoid trading in Asia unless very strong signal
        if kz["quality"] == "AVOID" and max(bull, bear) < 10:
            return sig

        if bull >= 8 and bear < 3:
            sig["signal"] = "STRONG_BUY"
            sig["direction"] = "long"
            sig["confidence"] = min(bull / 15, 1.0)

            if bull_ob and bull_ob["total_score"] >= 5:
                sig["entry"] = bull_ob["midpoint"]
                sig["stop_loss"] = bull_ob["bottom"] - atr * 0.3
                sig["ob_score"] = bull_ob["total_score"]
            else:
                sig["entry"] = price
                sig["stop_loss"] = price - atr * 1.5

            risk = abs(sig["entry"] - sig["stop_loss"])
            sig["take_profit"] = sig["entry"] + risk * rr

        elif bull >= 5.5 and bull > bear + 2:
            sig["signal"] = "BUY"
            sig["direction"] = "long"
            sig["confidence"] = min(bull / 15, 1.0)

            if bull_ob and bull_ob["total_score"] >= 3:
                sig["entry"] = bull_ob["midpoint"]
                sig["stop_loss"] = bull_ob["bottom"] - atr * 0.3
                sig["ob_score"] = bull_ob["total_score"]
            else:
                sig["entry"] = price
                sig["stop_loss"] = price - atr * 1.5

            risk = abs(sig["entry"] - sig["stop_loss"])
            sig["take_profit"] = sig["entry"] + risk * rr

        elif bear >= 8 and bull < 3:
            sig["signal"] = "STRONG_SELL"
            sig["direction"] = "short"
            sig["confidence"] = min(bear / 15, 1.0)

            if bear_ob and bear_ob["total_score"] >= 5:
                sig["entry"] = bear_ob["midpoint"]
                sig["stop_loss"] = bear_ob["top"] + atr * 0.3
                sig["ob_score"] = bear_ob["total_score"]
            else:
                sig["entry"] = price
                sig["stop_loss"] = price + atr * 1.5

            risk = abs(sig["stop_loss"] - sig["entry"])
            sig["take_profit"] = sig["entry"] - risk * rr

        elif bear >= 5.5 and bear > bull + 2:
            sig["signal"] = "SELL"
            sig["direction"] = "short"
            sig["confidence"] = min(bear / 15, 1.0)

            if bear_ob and bear_ob["total_score"] >= 3:
                sig["entry"] = bear_ob["midpoint"]
                sig["stop_loss"] = bear_ob["top"] + atr * 0.3
                sig["ob_score"] = bear_ob["total_score"]
            else:
                sig["entry"] = price
                sig["stop_loss"] = price + atr * 1.5

            risk = abs(sig["stop_loss"] - sig["entry"])
            sig["take_profit"] = sig["entry"] - risk * rr

        for k in ["entry", "stop_loss", "take_profit"]:
            if sig[k] is not None:
                sig[k] = round(sig[k], 2)

        return sig

    def _extract_features(self, df, structure, htf_bias, nearest_ob,
                          sweeps, fvgs, pd_zone, bull, bear):
        price = df["close"].iloc[-1]
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
        rsi = 100 - (100 / (1 + gain / max(loss, 1e-10)))
        atr = self.calculate_atr(df)
        vol_sma = df["volume"].rolling(20).mean().iloc[-1]
        ema12 = df["close"].ewm(span=12).mean().iloc[-1]
        ema26 = df["close"].ewm(span=26).mean().iloc[-1]
        trend_map = {"bullish": 1, "bearish": -1, "neutral": 0}
        zone_map = {"premium": 1, "slight_premium": 0.5, "equilibrium": 0,
                    "slight_discount": -0.5, "discount": -1}

        ob_dist = 1.0
        ob_score = 0
        if nearest_ob:
            ob_dist = abs(price - nearest_ob["midpoint"]) / price
            ob_score = nearest_ob.get("total_score", 0)

        return {
            "rsi": round(rsi, 2),
            "atr_pct": round(atr / price * 100, 4),
            "vol_ratio": round(df["volume"].iloc[-1] / max(vol_sma, 1), 2),
            "pct_change_1": round((price / df["close"].iloc[-2] - 1) * 100, 4) if len(df) > 1 else 0,
            "pct_change_5": round((price / df["close"].iloc[-5] - 1) * 100, 4) if len(df) > 5 else 0,
            "macd": round(ema12 - ema26, 4),
            "trend": trend_map.get(structure["trend"], 0),
            "htf_trend": trend_map.get(htf_bias, 0),
            "structure_strength": structure["strength"],
            "ob_count": len(fvgs),
            "sweep_count": len(sweeps),
            "fvg_count": len(fvgs),
            "zone": zone_map.get(pd_zone["zone"], 0),
            "kill_zone": self._kill_zone_score()["score"],
            "bull_score": bull,
            "bear_score": bear,
            "ob_distance": round(ob_dist, 4),
            "spread_score": bull - bear,
        }

    def calculate_atr(self, df, period=14):
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([h - l, abs(h - c.shift(1)), abs(l - c.shift(1))], axis=1).max(axis=1)
        return tr.rolling(period).mean().iloc[-1]
