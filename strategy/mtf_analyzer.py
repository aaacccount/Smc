import pandas as pd, numpy as np
from config import Config
from strategy.market_structure import MarketStructure
from strategy.order_blocks import OrderBlockDetector
from strategy.liquidity import LiquidityAnalyzer
from utils.logger import setup_logger
logger = setup_logger("MTF")

class MTFAnalyzer:
    def __init__(self):
        self.config=Config(); self.ms=MarketStructure(); self.ob=OrderBlockDetector(); self.liq=LiquidityAnalyzer()

    def analyze_all_timeframes(self, td):
        r={"direction_bias":"neutral","structure_trend":"neutral","entry_signal":"NO_SIGNAL","sniper_confirmed":False,"confluence_score":0,"details":{},"final_signal":"NO_SIGNAL","tradeable":False}
        da=self._direction(td.get("direction")); r["direction_bias"]=da["bias"]; r["details"]["direction"]=da
        sa=self._structure(td.get("structure")); r["structure_trend"]=sa["trend"]; r["details"]["structure"]=sa
        ea=self._entry(td.get("entry")); r["entry_signal"]=ea["signal"]; r["details"]["entry"]=ea
        sn=self._sniper(td.get("sniper")); r["sniper_confirmed"]=sn["confirmed"]; r["details"]["sniper"]=sn
        r["confluence_score"]=self._confluence(da,sa,ea,sn)
        f=self._final(da,sa,ea,sn,r["confluence_score"])
        r.update({"final_signal":f["signal"],"tradeable":f["tradeable"],"direction":f.get("direction"),"entry_price":f.get("entry"),"stop_loss":f.get("stop_loss"),"take_profit":f.get("take_profit"),"confidence":f.get("confidence",0)})
        logger.info(f"MTF | Dir:{r['direction_bias']} Str:{r['structure_trend']} Ent:{r['entry_signal']} Snp:{'Y' if r['sniper_confirmed'] else 'N'} Score:{r['confluence_score']}/10")
        return r

    def _direction(self, df):
        a={"bias":"neutral","strength":0,"key_levels":{}}
        if df is None or len(df)<30: return a
        s=self.ms.detect_structure(df); pz=self.ms.get_premium_discount(df)
        a["bias"]=s["trend"]; a["strength"]=s["strength"]; a["key_levels"]={"zone":pz["zone"]}
        for b in s["bos_levels"]:
            if b["type"]=="bullish_bos": a["bias"]="strong_bullish"; a["strength"]+=2
            elif b["type"]=="bearish_bos": a["bias"]="strong_bearish"; a["strength"]+=2
        return a

    def _structure(self, df):
        a={"trend":"neutral","strength":0,"order_blocks":[],"bos":[],"choch":[],"fvgs":[],"key_level":None}
        if df is None or len(df)<30: return a
        s=self.ms.detect_structure(df); obs=self.ob.find_order_blocks(df); fvgs=self.liq.find_fvg(df)
        a.update({"trend":s["trend"],"strength":s["strength"],"order_blocks":obs[:5],"bos":s["bos_levels"],"choch":s["choch_levels"],"fvgs":fvgs[:5]})
        if obs:
            p=df["close"].iloc[-1]; a["key_level"]=min(obs,key=lambda o:abs(p-o["midpoint"]))
        return a

    def _entry(self, df):
        a={"signal":"NO_SIGNAL","direction":None,"entry":None,"stop_loss":None,"take_profit":None,"confidence":0,"trigger":[]}
        if df is None or len(df)<30: return a
        s=self.ms.detect_structure(df); obs=self.ob.find_order_blocks(df); sw=self.liq.detect_liquidity_sweep(df); fvgs=self.liq.find_fvg(df); pz=self.ms.get_premium_discount(df)
        p=df["close"].iloc[-1]; atr=self._atr(df); rr=self.config.RISK_REWARD_RATIO
        bt=0; br=[]; st=0; sr=[]
        for b in s["bos_levels"]:
            if b["type"]=="bullish_bos": bt+=2; br.append("BOS")
            elif b["type"]=="bearish_bos": st+=2; sr.append("BOS")
        for c in s["choch_levels"]:
            if c["type"]=="bullish_choch": bt+=1.5; br.append("CHoCH")
            elif c["type"]=="bearish_choch": st+=1.5; sr.append("CHoCH")
        for ob in obs:
            d=abs(p-ob["midpoint"])/p
            if ob["type"]=="bullish_ob" and d<0.003: bt+=2; br.append("OB")
            elif ob["type"]=="bullish_ob" and d<0.008: bt+=1; br.append("OB_near")
            elif ob["type"]=="bearish_ob" and d<0.003: st+=2; sr.append("OB")
            elif ob["type"]=="bearish_ob" and d<0.008: st+=1; sr.append("OB_near")
        for x in sw[-3:]:
            if x["type"]=="bullish_sweep": bt+=1.5; br.append("Sweep"); break
            elif x["type"]=="bearish_sweep": st+=1.5; sr.append("Sweep"); break
        if pz["zone"] in ["discount","slight_discount"]: bt+=1; br.append("Discount")
        elif pz["zone"] in ["premium","slight_premium"]: st+=1; sr.append("Premium")
        for f in fvgs:
            if f["type"]=="bullish_fvg" and f["bottom"]<=p<=f["top"]: bt+=1; br.append("FVG"); break
            elif f["type"]=="bearish_fvg" and f["bottom"]<=p<=f["top"]: st+=1; sr.append("FVG"); break
        if bt>=4 and bt>st+1:
            bob=next((o for o in obs if o["type"]=="bullish_ob"),None)
            sl=bob["bottom"]-atr*0.3 if bob else p-atr*1.5
            a.update({"signal":"STRONG_BUY" if bt>=6 else "BUY","direction":"long","confidence":min(bt/8,1.0),"trigger":br,"entry":p,"stop_loss":sl,"take_profit":p+abs(p-sl)*rr})
        elif st>=4 and st>bt+1:
            sob=next((o for o in obs if o["type"]=="bearish_ob"),None)
            sl=sob["top"]+atr*0.3 if sob else p+atr*1.5
            a.update({"signal":"STRONG_SELL" if st>=6 else "SELL","direction":"short","confidence":min(st/8,1.0),"trigger":sr,"entry":p,"stop_loss":sl,"take_profit":p-abs(sl-p)*rr})
        return a

    def _sniper(self, df):
        a={"confirmed":False,"momentum":"neutral","volume_confirm":False}
        if df is None or len(df)<20: return a
        s=self.ms.detect_structure(df)
        delta=df["close"].diff(); g=delta.where(delta>0,0).rolling(14).mean().iloc[-1]; l=(-delta.where(delta<0,0)).rolling(14).mean().iloc[-1]
        rsi=100-(100/(1+g/max(l,1e-10)))
        if rsi>55: a["momentum"]="bullish"
        elif rsi<45: a["momentum"]="bearish"
        va=df["volume"].rolling(20).mean().iloc[-1]; a["volume_confirm"]=df["volume"].iloc[-1]>va*1.2
        last3=df.tail(3); bc=sum(1 for _,c in last3.iterrows() if c["close"]>c["open"])
        if bc>=2 and a["momentum"]=="bullish": a["confirmed"]=True; a["direction"]="bullish"
        elif bc<=1 and a["momentum"]=="bearish": a["confirmed"]=True; a["direction"]="bearish"
        return a

    def _confluence(self,d,s,e,sn):
        sc=0; db=d["bias"]
        if "strong" in db: sc+=3
        elif db in ["bullish","bearish"]: sc+=2
        st=s["trend"]
        if db.replace("strong_","")==st: sc+=2
        if e["signal"] in ["STRONG_BUY","STRONG_SELL"]: sc+=3
        elif e["signal"] in ["BUY","SELL"]: sc+=2
        if sn["confirmed"]: sc+=1.5
        if sn.get("volume_confirm"): sc+=0.5
        return min(round(sc,1),10)

    def _final(self,d,s,e,sn,score):
        r={"signal":"NO_SIGNAL","tradeable":False}
        if e["signal"]=="NO_SIGNAL": return r
        ed=e.get("direction"); db=d["bias"].replace("strong_",""); st=s["trend"]
        if ed=="long" and db=="bearish": return r
        if ed=="short" and db=="bullish": return r
        if ed=="long" and st=="bearish": return r
        if ed=="short" and st=="bullish": return r
        if score<5: return r
        if not sn["confirmed"] and e["signal"] not in ["STRONG_BUY","STRONG_SELL"]: return r
        conf=e.get("confidence",0.5)
        if db==ed.replace("long","bullish").replace("short","bearish"): conf*=1.1
        if st==ed.replace("long","bullish").replace("short","bearish"): conf*=1.1
        if sn["confirmed"]: conf*=1.1
        return {"signal":e["signal"],"tradeable":True,"direction":ed,"entry":e.get("entry"),"stop_loss":e.get("stop_loss"),"take_profit":e.get("take_profit"),"confidence":min(round(conf,3),1.0)}

    def _atr(self,df,p=14):
        h,l,c=df["high"],df["low"],df["close"]
        tr=pd.concat([h-l,abs(h-c.shift(1)),abs(l-c.shift(1))],axis=1).max(axis=1)
        return tr.rolling(p).mean().iloc[-1]
