import pandas as pd, numpy as np
from config import Config
from utils.logger import setup_logger
logger = setup_logger("Liquidity")

class LiquidityAnalyzer:
    def __init__(self):
        self.config = Config()
        self.th = self.config.LIQUIDITY_THRESHOLD

    def find_liquidity_pools(self, df):
        pools=[]; tol=df["close"].iloc[-1]*0.001
        for lv in self._eq_levels(df["high"],tol):
            pools.append({"type":"buy_side_liquidity","level":lv["level"],"strength":lv["touches"],"desc":"EQH"})
        for lv in self._eq_levels(df["low"],tol):
            pools.append({"type":"sell_side_liquidity","level":lv["level"],"strength":lv["touches"],"desc":"EQL"})
        try:
            daily=df.resample("D").agg({"high":"max","low":"min"}).dropna()
            if len(daily)>1:
                pools.append({"type":"buy_side_liquidity","level":daily.iloc[-2]["high"],"strength":5,"desc":"PDH"})
                pools.append({"type":"sell_side_liquidity","level":daily.iloc[-2]["low"],"strength":5,"desc":"PDL"})
        except: pass
        return pools

    def _eq_levels(self, series, tol):
        levels=[]; vals=series.values
        for i in range(len(vals)-1):
            t=1; s=vals[i]
            for j in range(i+1,len(vals)):
                if abs(vals[j]-vals[i])<=tol: t+=1; s+=vals[j]
            if t>=self.th:
                avg=s/t
                if not any(abs(l["level"]-avg)<=tol for l in levels):
                    levels.append({"level":round(avg,2),"touches":t})
        return levels

    def detect_liquidity_sweep(self, df):
        sweeps=[]; pools=self.find_liquidity_pools(df)
        for pool in pools:
            lv=pool["level"]
            for i in range(-5,0):
                if abs(i)>=len(df): continue
                c=df.iloc[i]
                if pool["type"]=="buy_side_liquidity" and c["high"]>lv and c["close"]<lv and c["close"]<c["open"]:
                    sweeps.append({"type":"bearish_sweep","level":lv,"timestamp":df.index[i],"desc":pool["desc"]})
                elif pool["type"]=="sell_side_liquidity" and c["low"]<lv and c["close"]>lv and c["close"]>c["open"]:
                    sweeps.append({"type":"bullish_sweep","level":lv,"timestamp":df.index[i],"desc":pool["desc"]})
        return sweeps

    def find_fvg(self, df):
        fvgs=[]; ms=self.config.FVG_MIN_SIZE
        for i in range(2,min(50,len(df))):
            idx=len(df)-1-i
            if idx<0 or idx+2>=len(df): continue
            c1=df.iloc[idx]; c3=df.iloc[idx+2]
            if c3["low"]>c1["high"]:
                g=c3["low"]-c1["high"]; p=g/c1["high"]
                if p>=ms and not any(df["low"].iloc[j]<=c1["high"] for j in range(idx+3,len(df))):
                    fvgs.append({"type":"bullish_fvg","top":c3["low"],"bottom":c1["high"],"midpoint":(c3["low"]+c1["high"])/2,"size_pct":round(p*100,3),"timestamp":df.index[idx+1]})
            if c3["high"]<c1["low"]:
                g=c1["low"]-c3["high"]; p=g/c1["low"]
                if p>=ms and not any(df["high"].iloc[j]>=c1["low"] for j in range(idx+3,len(df))):
                    fvgs.append({"type":"bearish_fvg","top":c1["low"],"bottom":c3["high"],"midpoint":(c1["low"]+c3["high"])/2,"size_pct":round(p*100,3),"timestamp":df.index[idx+1]})
        return fvgs
