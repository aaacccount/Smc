import pandas as pd,numpy as np,json,os
from datetime import datetime
from config import Config
from utils.logger import setup_logger
logger=setup_logger("Backtest")

class Trade:
    def __init__(s,tid,d,ep,sl,tp,sz,et,sig,conf):
        s.id=tid;s.direction=d;s.entry_price=ep;s.stop_loss=sl;s.take_profit=tp
        s.size=sz;s.entry_time=et;s.exit_time=None;s.exit_price=None;s.pnl=0
        s.pnl_pct=0;s.exit_reason=None;s.signal=sig;s.confidence=conf
        s.max_fav=0;s.max_adv=0;s.r_multiple=0;s.is_open=True
    def update(s,c):
        if not s.is_open:return
        h,l=c["high"],c["low"]
        if s.direction=="long":
            s.max_fav=max(s.max_fav,h-s.entry_price)
            s.max_adv=max(s.max_adv,s.entry_price-l)
            if l<=s.stop_loss:s._close(s.stop_loss,c.name,"stop_loss");return
            if h>=s.take_profit:s._close(s.take_profit,c.name,"take_profit")
        else:
            s.max_fav=max(s.max_fav,s.entry_price-l)
            s.max_adv=max(s.max_adv,h-s.entry_price)
            if h>=s.stop_loss:s._close(s.stop_loss,c.name,"stop_loss");return
            if l<=s.take_profit:s._close(s.take_profit,c.name,"take_profit")
    def _close(s,ep,et,r):
        s.exit_price=ep;s.exit_time=et;s.exit_reason=r;s.is_open=False
        if s.direction=="long":
            s.pnl=(ep-s.entry_price)*s.size
            s.pnl_pct=(ep-s.entry_price)/s.entry_price*100
        else:
            s.pnl=(s.entry_price-ep)*s.size
            s.pnl_pct=(s.entry_price-ep)/s.entry_price*100
        risk=abs(s.entry_price-s.stop_loss)
        if risk>0:
            if s.direction=="long":s.r_multiple=(ep-s.entry_price)/risk
            else:s.r_multiple=(s.entry_price-ep)/risk
    def force_close(s,p,t):
        if s.is_open:s._close(p,t,"end_of_data")
    def to_dict(s):
        return {"id":s.id,"direction":s.direction,"entry_price":round(s.entry_price,2),
            "exit_price":round(s.exit_price,2) if s.exit_price else None,
            "stop_loss":round(s.stop_loss,2),"take_profit":round(s.take_profit,2),
            "pnl":round(s.pnl,2),"pnl_pct":round(s.pnl_pct,4),
            "r_multiple":round(s.r_multiple,2),"exit_reason":s.exit_reason,
            "signal":s.signal,"entry_time":str(s.entry_time),
            "exit_time":str(s.exit_time) if s.exit_time else None}

class BacktestEngine:
    def __init__(s,strategy,initial_balance=10000,commission=0.0006,slippage=0.0002):
        s.strategy=strategy;s.ib=initial_balance;s.balance=initial_balance
        s.comm=commission;s.slip=slippage;s.config=Config()
        s.trades=[];s.ot=None;s.tc=0;s.eq=[];s.peak=initial_balance;s.mdd=0;s.mdd_pct=0
    def run(s,df,htf=None,warmup=50,progress=True):
        logger.info(f"Backtest: {len(df)} candles | ${s.ib:,.2f}")
        s.balance=s.ib;s.trades=[];s.ot=None;s.tc=0;s.eq=[]
        s.peak=s.ib;s.mdd=0;s.mdd_pct=0
        n=len(df);rp=max(n//20,1)
        for i in range(warmup,n):
            if progress and i%rp==0:
                logger.info(f"  {i/n*100:.0f}% | Trades:{len(s.trades)} | ${s.balance:,.2f}")
            cc=df.iloc[i];ct=df.index[i]
            ch=None
            if htf is not None and len(htf)>0:
                m=htf.index<=ct
                if m.any():ch=htf[m].copy()
            if s.ot and s.ot.is_open:
                s.ot.update(cc)
                if not s.ot.is_open:
                    cost=abs(s.ot.pnl)*s.comm*2
                    s.ot.pnl-=cost;s.balance+=s.ot.pnl
                    s.trades.append(s.ot);s.ot=None
            ur=0
            if s.ot and s.ot.is_open:
                if s.ot.direction=="long":ur=(cc["close"]-s.ot.entry_price)*s.ot.size
                else:ur=(s.ot.entry_price-cc["close"])*s.ot.size
            eq=s.balance+ur
            s.eq.append({"timestamp":ct,"equity":eq,"balance":s.balance})
            if eq>s.peak:s.peak=eq
            dd=s.peak-eq;ddp=dd/s.peak if s.peak>0 else 0
            if dd>s.mdd:s.mdd=dd;s.mdd_pct=ddp
            if s.ot:continue
            if s.balance<s.ib*0.5:break
            try:
                cd=df.iloc[:i+1].copy()
                if len(cd)<warmup:continue
                a=s.strategy.analyze(cd,ch)
                if a["signal"] in ["STRONG_BUY","BUY","STRONG_SELL","SELL"]:
                    if a["entry"] and a["stop_loss"] and a["take_profit"]:
                        s._open(a,ct)
            except:continue
        if s.ot and s.ot.is_open:
            s.ot.force_close(df["close"].iloc[-1],df.index[-1])
            s.ot.pnl-=abs(s.ot.pnl)*s.comm*2
            s.balance+=s.ot.pnl;s.trades.append(s.ot)
        return s._report(df)
    def _open(s,a,t):
        e=a["entry"];sl=a["stop_loss"];tp=a["take_profit"];d=a["direction"]
        c=a.get("confidence",0.5)
        if d=="long":e*=(1+s.slip)
        else:e*=(1-s.slip)
        ra=s.balance*s.config.RISK_PER_TRADE*c;ru=abs(e-sl)
        if ru<=0:return
        sz=min(ra/ru,(s.balance*s.config.LEVERAGE*0.95)/e)
        if sz<=0:return
        s.tc+=1;s.ot=Trade(s.tc,d,e,sl,tp,sz,t,a["signal"],c)
    def _report(s,df):
        if not s.trades:return {"error":"No trades"}
        w=[t for t in s.trades if t.pnl>0];l=[t for t in s.trades if t.pnl<=0]
        wp=[t.pnl for t in w];lp=[t.pnl for t in l];ap=[t.pnl for t in s.trades]
        tp=sum(ap);wr=len(w)/len(s.trades)*100
        pf=abs(sum(wp))/abs(sum(lp)) if lp and sum(lp)!=0 else 999
        rm=[t.r_multiple for t in s.trades]
        edf=pd.DataFrame(s.eq);sh=so=cal=0
        if len(edf)>0:
            edf.set_index("timestamp",inplace=True)
            de=edf["equity"].resample("D").last().dropna()
            dr=de.pct_change().dropna()
            if len(dr)>1 and dr.std()>0:sh=dr.mean()/dr.std()*np.sqrt(365)
            neg=dr[dr<0]
            if len(neg)>1 and neg.std()>0:so=dr.mean()/neg.std()*np.sqrt(365)
            if s.mdd_pct>0:cal=(tp/s.ib)/s.mdd_pct
        mr={}
        for t in s.trades:
            mk=str(t.entry_time)[:7];mr[mk]=mr.get(mk,0)+t.pnl
        lo=[t for t in s.trades if t.direction=="long"]
        sho=[t for t in s.trades if t.direction=="short"]
        lwr=len([t for t in lo if t.pnl>0])/max(len(lo),1)*100
        swr=len([t for t in sho if t.pnl>0])/max(len(sho),1)*100
        ss={}
        for t in s.trades:
            if t.signal not in ss:ss[t.signal]={"trades":0,"wins":0,"pnl":0}
            ss[t.signal]["trades"]+=1
            if t.pnl>0:ss[t.signal]["wins"]+=1
            ss[t.signal]["pnl"]+=t.pnl
        for k in ss:
            ss[k]["win_rate"]=round(ss[k]["wins"]/max(ss[k]["trades"],1)*100,1)
            ss[k]["pnl"]=round(ss[k]["pnl"],2)
        return {"summary":{"period_start":str(df.index[0]),"period_end":str(df.index[-1]),
            "total_candles":len(df),"initial_balance":s.ib,"final_balance":round(s.balance,2),
            "total_pnl":round(tp,2),"total_return_pct":round(tp/s.ib*100,2),
            "total_trades":len(s.trades),"winning_trades":len(w),"losing_trades":len(l),
            "win_rate":round(wr,1),"profit_factor":round(pf,2),
            "avg_win":round(np.mean(wp),2) if wp else 0,
            "avg_loss":round(np.mean(lp),2) if lp else 0,
            "largest_win":round(max(ap),2),"largest_loss":round(min(ap),2),
            "avg_r_multiple":round(np.mean(rm),2),"expectancy_r":round(np.mean(rm),2),
            "max_drawdown":round(s.mdd,2),"max_drawdown_pct":round(s.mdd_pct*100,2),
            "sharpe_ratio":round(sh,2),"sortino_ratio":round(so,2),"calmar_ratio":round(cal,2),
            },
            "direction_stats":{"long_trades":len(lo),"long_win_rate":round(lwr,1),
                "long_pnl":round(sum(t.pnl for t in lo),2),
                "short_trades":len(sho),"short_win_rate":round(swr,1),
                "short_pnl":round(sum(t.pnl for t in sho),2)},
            "signal_stats":ss,
            "monthly_returns":{k:round(v,2) for k,v in mr.items()},
            "trades":[t.to_dict() for t in s.trades]}
