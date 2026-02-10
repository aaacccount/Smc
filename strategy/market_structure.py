import pandas as pd, numpy as np
from config import Config
from utils.logger import setup_logger
logger = setup_logger("MarketStructure")

class MarketStructure:
    def __init__(self):
        self.config = Config()
        self.lb = self.config.SWING_LOOKBACK

    def find_swing_highs(self, df, lb=None):
        lb = lb or self.lb
        sh = pd.Series(index=df.index, dtype=float)
        for i in range(lb, len(df)-lb):
            h = df["high"].iloc[i]
            if all(df["high"].iloc[i-j] < h and df["high"].iloc[i+j] < h for j in range(1, lb+1)):
                sh.iloc[i] = h
        return sh.dropna()

    def find_swing_lows(self, df, lb=None):
        lb = lb or self.lb
        sl = pd.Series(index=df.index, dtype=float)
        for i in range(lb, len(df)-lb):
            l = df["low"].iloc[i]
            if all(df["low"].iloc[i-j] > l and df["low"].iloc[i+j] > l for j in range(1, lb+1)):
                sl.iloc[i] = l
        return sl.dropna()

    def detect_structure(self, df):
        sh = self.find_swing_highs(df)
        sl = self.find_swing_lows(df)
        s = {"trend":"neutral","swing_highs":sh,"swing_lows":sl,"bos_levels":[],"choch_levels":[],"last_hh":None,"last_ll":None,"strength":0}
        if len(sh)<3 or len(sl)<3:
            return s
        h = sh.values; l = sl.values
        hh = sum(1 for i in range(1,min(5,len(h))) if i+1<=len(h) and h[-i]>h[-(i+1)])
        lh = sum(1 for i in range(1,min(5,len(h))) if i+1<=len(h) and h[-i]<h[-(i+1)])
        hl = sum(1 for i in range(1,min(5,len(l))) if i+1<=len(l) and l[-i]>l[-(i+1)])
        ll = sum(1 for i in range(1,min(5,len(l))) if i+1<=len(l) and l[-i]<l[-(i+1)])
        bull = hh+hl; bear = lh+ll
        if bull>=3 and bull>bear: s["trend"]="bullish"; s["strength"]=bull
        elif bear>=3 and bear>bull: s["trend"]="bearish"; s["strength"]=bear
        s["last_hh"]=h[-1]; s["last_ll"]=l[-1]
        p = df["close"].iloc[-1]
        if len(sh)>=2 and p>sh.iloc[-1]:
            s["bos_levels"].append({"type":"bullish_bos","level":sh.iloc[-1],"timestamp":sh.index[-1]})
        if len(sl)>=2 and p<sl.iloc[-1]:
            s["bos_levels"].append({"type":"bearish_bos","level":sl.iloc[-1],"timestamp":sl.index[-1]})
        if len(h)>=3 and len(l)>=3:
            if h[-3]>h[-2] and l[-1]>l[-2] and h[-1]>h[-2]:
                s["choch_levels"].append({"type":"bullish_choch","level":h[-2],"timestamp":sh.index[-1]})
            if l[-3]<l[-2] and h[-1]<h[-2] and l[-1]<l[-2]:
                s["choch_levels"].append({"type":"bearish_choch","level":l[-2],"timestamp":sl.index[-1]})
        return s

    def get_premium_discount(self, df):
        sh = self.find_swing_highs(df); sl = self.find_swing_lows(df)
        if len(sh)==0 or len(sl)==0:
            return {"zone":"equilibrium","level":0.5}
        h=sh.iloc[-1]; l=sl.iloc[-1]; c=df["close"].iloc[-1]; r=h-l
        if r==0: return {"zone":"equilibrium","level":0.5}
        p = (c-l)/r
        if p>0.7: z="premium"
        elif p<0.3: z="discount"
        elif p>0.5: z="slight_premium"
        elif p<0.5: z="slight_discount"
        else: z="equilibrium"
        return {"zone":z,"level":round(p,4),"equilibrium":l+r*0.5,"high":h,"low":l}
