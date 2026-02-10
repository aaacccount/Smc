import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from config import Config
from utils.logger import setup_logger
logger = setup_logger("OrderBlocks")


class OrderBlockDetector:
    """
    Order Block Detection - Pro Version

    Features:
    - OB + FVG (Imbalanced OB) = stronger score
    - Fresh OB (first touch) vs Tested vs Mitigated
    - Clean OB (no liquidity ahead)
    - Volume confirmation
    - Nested OB (HTF + LTF alignment)
    - Volume Profile Lite for supply/demand zones
    """

    def __init__(self):
        self.config = Config()
        self.lookback = self.config.OB_LOOKBACK

    def find_order_blocks(self, df, htf_df=None):
        """شناسایی OB با امتیازدهی پیشرفته"""
        raw_obs = []

        for i in range(2, min(self.lookback, len(df) - 3)):
            idx = len(df) - 1 - i

            bull = self._check_bullish_ob(df, idx)
            if bull:
                raw_obs.append(bull)

            bear = self._check_bearish_ob(df, idx)
            if bear:
                raw_obs.append(bear)

        # Score each OB
        scored = []
        for ob in raw_obs:
            ob = self._score_ob(df, ob, htf_df)
            if ob["total_score"] > 0:
                scored.append(ob)

        # Sort by total score
        scored.sort(key=lambda x: x["total_score"], reverse=True)
        logger.debug(f"Found {len(scored)} scored OBs")
        return scored[:15]

    def _check_bullish_ob(self, df, idx):
        """Bullish OB Detection"""
        if idx + 3 >= len(df) or idx < 0:
            return None

        c = df.iloc[idx]
        n1 = df.iloc[idx + 1]
        n2 = df.iloc[idx + 2]

        # Must be bearish candle
        if c["close"] >= c["open"]:
            return None

        rng = c["high"] - c["low"]
        if rng == 0:
            return None

        # Strong bullish move after
        move = n2["close"] - c["low"]
        if move < rng * 1.5:
            return None

        # Next candles must be bullish
        if not (n1["close"] > n1["open"] and n2["close"] > n2["open"]):
            return None

        # Check for FVG (gap between candle1 high and candle3 low)
        has_fvg = n2["low"] > c["high"]
        fvg_size = 0
        if has_fvg:
            fvg_size = (n2["low"] - c["high"]) / c["high"] * 100

        # Body percentage (how much of candle is body vs wick)
        body = abs(c["open"] - c["close"])
        body_pct = body / rng if rng > 0 else 0

        # Volume spike
        avg_vol = df["volume"].iloc[max(0, idx-20):idx].mean()
        vol_ratio = c["volume"] / avg_vol if avg_vol > 0 else 1

        return {
            "type": "bullish_ob",
            "top": max(c["open"], c["close"]),
            "bottom": c["low"],
            "midpoint": (max(c["open"], c["close"]) + c["low"]) / 2,
            "timestamp": df.index[idx],
            "candle_idx": idx,
            "volume": c["volume"],
            "vol_ratio": round(vol_ratio, 2),
            "has_fvg": has_fvg,
            "fvg_size": round(fvg_size, 3),
            "body_pct": round(body_pct, 2),
            "move_strength": round(move / rng, 2),
            "mitigated": False,
            "touch_count": 0,
            "is_fresh": True,
            "has_liquidity_ahead": False,
            "in_htf_zone": False,
            "total_score": 0,
        }

    def _check_bearish_ob(self, df, idx):
        """Bearish OB Detection"""
        if idx + 3 >= len(df) or idx < 0:
            return None

        c = df.iloc[idx]
        n1 = df.iloc[idx + 1]
        n2 = df.iloc[idx + 2]

        if c["close"] <= c["open"]:
            return None

        rng = c["high"] - c["low"]
        if rng == 0:
            return None

        move = c["high"] - n2["close"]
        if move < rng * 1.5:
            return None

        if not (n1["close"] < n1["open"] and n2["close"] < n2["open"]):
            return None

        has_fvg = n2["high"] < c["low"]
        fvg_size = 0
        if has_fvg:
            fvg_size = (c["low"] - n2["high"]) / c["low"] * 100

        body = abs(c["close"] - c["open"])
        body_pct = body / rng if rng > 0 else 0

        avg_vol = df["volume"].iloc[max(0, idx-20):idx].mean()
        vol_ratio = c["volume"] / avg_vol if avg_vol > 0 else 1

        return {
            "type": "bearish_ob",
            "top": c["high"],
            "bottom": min(c["open"], c["close"]),
            "midpoint": (c["high"] + min(c["open"], c["close"])) / 2,
            "timestamp": df.index[idx],
            "candle_idx": idx,
            "volume": c["volume"],
            "vol_ratio": round(vol_ratio, 2),
            "has_fvg": has_fvg,
            "fvg_size": round(fvg_size, 3),
            "body_pct": round(body_pct, 2),
            "move_strength": round(move / rng, 2),
            "mitigated": False,
            "touch_count": 0,
            "is_fresh": True,
            "has_liquidity_ahead": False,
            "in_htf_zone": False,
            "total_score": 0,
        }

    def _score_ob(self, df, ob, htf_df=None):
        """امتیازدهی جامع به OB"""
        score = 0
        price = df["close"].iloc[-1]
        reasons = []

        # ── 1. Check mitigated/fresh/tested ──
        ob = self._check_touch_status(df, ob)

        if ob["mitigated"]:
            ob["total_score"] = 0
            return ob

        # ── 2. Fresh OB (first touch) = +3 ──
        if ob["is_fresh"]:
            score += 3
            reasons.append("Fresh(+3)")
        elif ob["touch_count"] == 1:
            score += 1
            reasons.append("Tested1x(+1)")
        else:
            score += 0.5
            reasons.append(f"Tested{ob['touch_count']}x(+0.5)")

        # ── 3. OB + FVG = +2.5 ──
        if ob["has_fvg"]:
            score += 2.5
            reasons.append(f"FVG({ob['fvg_size']:.2f}%)(+2.5)")
        else:
            score += 0.5
            reasons.append("NoFVG(+0.5)")

        # ── 4. Move strength = +0 to +2 ──
        if ob["move_strength"] >= 3:
            score += 2
            reasons.append("StrongMove(+2)")
        elif ob["move_strength"] >= 2:
            score += 1.5
            reasons.append("GoodMove(+1.5)")
        else:
            score += 0.5
            reasons.append("WeakMove(+0.5)")

        # ── 5. Volume confirmation = +0 to +1.5 ──
        if ob["vol_ratio"] >= 2:
            score += 1.5
            reasons.append("HighVol(+1.5)")
        elif ob["vol_ratio"] >= 1.3:
            score += 1
            reasons.append("AboveAvgVol(+1)")

        # ── 6. Body percentage (full body = stronger) = +0 to +1 ──
        if ob["body_pct"] >= 0.7:
            score += 1
            reasons.append("FullBody(+1)")
        elif ob["body_pct"] >= 0.5:
            score += 0.5

        # ── 7. Clean OB (no liquidity ahead) = +2 ──
        ob["has_liquidity_ahead"] = self._check_liquidity_ahead(df, ob)
        if not ob["has_liquidity_ahead"]:
            score += 2
            reasons.append("Clean(+2)")
        else:
            score -= 1
            reasons.append("LiquidityAhead(-1)")

        # ── 8. Distance from price (closer = more relevant) ──
        distance_pct = abs(price - ob["midpoint"]) / price
        if distance_pct < 0.003:
            score += 1.5
            reasons.append("VeryClose(+1.5)")
        elif distance_pct < 0.008:
            score += 1
            reasons.append("Close(+1)")
        elif distance_pct < 0.02:
            score += 0.5
        elif distance_pct > 0.05:
            score -= 1

        # ── 9. HTF Zone alignment = +2 ──
        if htf_df is not None:
            ob["in_htf_zone"] = self._check_htf_alignment(ob, htf_df)
            if ob["in_htf_zone"]:
                score += 2
                reasons.append("HTF_Zone(+2)")

        # ── 10. Proximity check (valid side of price) ──
        if ob["type"] == "bullish_ob" and price < ob["bottom"]:
            score = 0  # Price below bullish OB = invalid
        elif ob["type"] == "bearish_ob" and price > ob["top"]:
            score = 0  # Price above bearish OB = invalid

        ob["total_score"] = round(max(score, 0), 1)
        ob["score_reasons"] = reasons
        return ob

    def _check_touch_status(self, df, ob):
        """بررسی Fresh / Tested / Mitigated"""
        try:
            ob_idx = df.index.get_loc(ob["timestamp"])
        except:
            ob["mitigated"] = True
            return ob

        touch_count = 0
        mitigated = False

        for j in range(ob_idx + 3, len(df)):
            if ob["type"] == "bullish_ob":
                # Price entered OB zone
                if df["low"].iloc[j] <= ob["top"] and df["low"].iloc[j] >= ob["bottom"]:
                    touch_count += 1
                # Price broke through
                if df["close"].iloc[j] < ob["bottom"]:
                    mitigated = True
                    break
            elif ob["type"] == "bearish_ob":
                if df["high"].iloc[j] >= ob["bottom"] and df["high"].iloc[j] <= ob["top"]:
                    touch_count += 1
                if df["close"].iloc[j] > ob["top"]:
                    mitigated = True
                    break

        ob["touch_count"] = touch_count
        ob["is_fresh"] = touch_count == 0
        ob["mitigated"] = mitigated
        return ob

    def _check_liquidity_ahead(self, df, ob):
        """آیا نقدینگی (Equal Highs/Lows) جلوی OB هست؟"""
        price = df["close"].iloc[-1]
        tolerance = price * 0.002

        if ob["type"] == "bullish_ob":
            # Check for equal lows between price and OB
            zone_low = ob["bottom"]
            zone_high = price
            lows_in_zone = df["low"][(df["low"] >= zone_low) & (df["low"] <= zone_high)]

            if len(lows_in_zone) < 3:
                return False

            # Check for clusters
            for i in range(len(lows_in_zone)):
                count = sum(1 for l in lows_in_zone if abs(l - lows_in_zone.iloc[i]) <= tolerance)
                if count >= 3:
                    return True  # Liquidity pool found

        elif ob["type"] == "bearish_ob":
            zone_low = price
            zone_high = ob["top"]
            highs_in_zone = df["high"][(df["high"] >= zone_low) & (df["high"] <= zone_high)]

            if len(highs_in_zone) < 3:
                return False

            for i in range(len(highs_in_zone)):
                count = sum(1 for h in highs_in_zone if abs(h - highs_in_zone.iloc[i]) <= tolerance)
                if count >= 3:
                    return True

        return False

    def _check_htf_alignment(self, ob, htf_df):
        """آیا OB در ناحیه عرضه/تقاضا تایم بالا هست؟"""
        if htf_df is None or len(htf_df) < 10:
            return False

        # Find HTF supply/demand using volume profile lite
        vp = self.volume_profile_lite(htf_df)

        for zone in vp:
            if ob["type"] == "bullish_ob" and zone["type"] == "demand":
                if zone["low"] <= ob["midpoint"] <= zone["high"]:
                    return True
            elif ob["type"] == "bearish_ob" and zone["type"] == "supply":
                if zone["low"] <= ob["midpoint"] <= zone["high"]:
                    return True

        # Also check HTF OBs
        htf_obs = []
        for i in range(2, min(30, len(htf_df) - 3)):
            idx = len(htf_df) - 1 - i
            bull = self._check_bullish_ob(htf_df, idx)
            if bull:
                htf_obs.append(bull)
            bear = self._check_bearish_ob(htf_df, idx)
            if bear:
                htf_obs.append(bear)

        for htf_ob in htf_obs:
            if (ob["type"] == "bullish_ob" and htf_ob["type"] == "bullish_ob"):
                if htf_ob["bottom"] <= ob["midpoint"] <= htf_ob["top"]:
                    return True
            elif (ob["type"] == "bearish_ob" and htf_ob["type"] == "bearish_ob"):
                if htf_ob["bottom"] <= ob["midpoint"] <= htf_ob["top"]:
                    return True

        return False

    def volume_profile_lite(self, df, num_levels=20):
        """
        Volume Profile ساده
        بدون tick data - از candle volume استفاده میکنه
        سبک و سریع برای گوشی
        """
        if len(df) < 10:
            return []

        price_high = df["high"].max()
        price_low = df["low"].min()
        price_range = price_high - price_low

        if price_range == 0:
            return []

        level_size = price_range / num_levels
        levels = []

        for i in range(num_levels):
            level_low = price_low + (i * level_size)
            level_high = level_low + level_size
            level_mid = (level_low + level_high) / 2

            # Calculate volume at this level
            vol_at_level = 0
            candles_at_level = 0

            for _, candle in df.iterrows():
                if candle["low"] <= level_high and candle["high"] >= level_low:
                    # Portion of candle in this level
                    candle_range = candle["high"] - candle["low"]
                    if candle_range > 0:
                        overlap_low = max(candle["low"], level_low)
                        overlap_high = min(candle["high"], level_high)
                        overlap = max(0, overlap_high - overlap_low)
                        portion = overlap / candle_range
                        vol_at_level += candle["volume"] * portion
                        candles_at_level += 1

            levels.append({
                "low": round(level_low, 2),
                "high": round(level_high, 2),
                "mid": round(level_mid, 2),
                "volume": round(vol_at_level, 2),
                "candles": candles_at_level,
            })

        # Find POC (Point of Control)
        if not levels:
            return []

        max_vol = max(l["volume"] for l in levels)
        avg_vol = sum(l["volume"] for l in levels) / len(levels)

        # Classify zones
        zones = []
        for level in levels:
            if level["volume"] < avg_vol * 0.5:
                # Low Volume Node = fast move area
                zone_type = "lvn"
            elif level["volume"] > avg_vol * 1.5:
                # High Volume Node = support/resistance
                zone_type = "hvn"
            else:
                zone_type = "normal"

            # Determine supply/demand
            # Below POC = demand, Above POC = supply
            poc = max(levels, key=lambda x: x["volume"])
            if level["mid"] < poc["mid"]:
                sd_type = "demand"
            else:
                sd_type = "supply"

            if zone_type in ["lvn", "hvn"]:
                zones.append({
                    "type": sd_type,
                    "zone_type": zone_type,
                    "low": level["low"],
                    "high": level["high"],
                    "mid": level["mid"],
                    "volume": level["volume"],
                    "strength": round(level["volume"] / max(avg_vol, 1), 2),
                })

        return zones

    def get_best_ob(self, df, direction, htf_df=None):
        """بهترین OB برای یک جهت خاص"""
        obs = self.find_order_blocks(df, htf_df)

        if direction == "long":
            bull_obs = [ob for ob in obs if ob["type"] == "bullish_ob"]
            if bull_obs:
                return bull_obs[0]  # Already sorted by score
        elif direction == "short":
            bear_obs = [ob for ob in obs if ob["type"] == "bearish_ob"]
            if bear_obs:
                return bear_obs[0]

        return None
