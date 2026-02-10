import json,os,time,sys
from datetime import datetime

# Fix import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from exchange.connector import ExchangeConnector
from strategy.smart_money import SmartMoneyStrategy
from ml.brain import MLBrain
from utils.logger import setup_logger
logger=setup_logger("Paper")
PF="data/paper_state.json"

class PaperTrade:
    def __init__(s,tid,d,ep,sl,tp,sz,sig,conf):
        s.id=tid;s.direction=d;s.entry_price=ep;s.stop_loss=sl
        s.take_profit=tp;s.size=sz;s.signal=sig;s.confidence=conf
        s.entry_time=datetime.utcnow();s.exit_time=None;s.exit_price=None
        s.pnl=0;s.pnl_pct=0;s.exit_reason=None;s.is_open=True
        s.current_sl=sl;s.be=False
    def check_exit(s,p,h,l):
        if not s.is_open:return False
        if s.direction=="long":
            if l<=s.current_sl:s._close(s.current_sl,"SL");return True
            if h>=s.take_profit:s._close(s.take_profit,"TP");return True
        else:
            if h>=s.current_sl:s._close(s.current_sl,"SL");return True
            if l<=s.take_profit:s._close(s.take_profit,"TP");return True
        r=abs(s.entry_price-s.stop_loss)
        if not s.be:
            if s.direction=="long" and p>=s.entry_price+r:
                s.current_sl=round(s.entry_price+r*0.1,2);s.be=True
                logger.info(f"  Break-even activated")
            elif s.direction=="short" and p<=s.entry_price-r:
                s.current_sl=round(s.entry_price-r*0.1,2);s.be=True
                logger.info(f"  Break-even activated")
        if s.be:
            t=r*0.8
            if s.direction=="long":
                ns=p-t
                if ns>s.current_sl:s.current_sl=round(ns,2)
            else:
                ns=p+t
                if ns<s.current_sl:s.current_sl=round(ns,2)
        return False
    def _close(s,ep,r):
        s.exit_price=ep;s.exit_time=datetime.utcnow();s.exit_reason=r;s.is_open=False
        if s.direction=="long":
            s.pnl=(ep-s.entry_price)*s.size
            s.pnl_pct=(ep-s.entry_price)/s.entry_price*100
        else:
            s.pnl=(s.entry_price-ep)*s.size
            s.pnl_pct=(s.entry_price-ep)/s.entry_price*100
    def to_dict(s):
        return {"id":s.id,"direction":s.direction,"entry":round(s.entry_price,2),
            "exit":round(s.exit_price,2) if s.exit_price else None,
            "sl":round(s.current_sl,2),"tp":round(s.take_profit,2),
            "pnl":round(s.pnl,2),"pnl_pct":round(s.pnl_pct,4),
            "reason":s.exit_reason,"signal":s.signal,"open":s.is_open,
            "time":str(s.entry_time)}

class PaperTrader:
    def __init__(s,ib=10000):
        s.config=Config()
        s.exchange=ExchangeConnector()
        s.strategy=SmartMoneyStrategy()
        s.ml=MLBrain()
        s.ib=ib;s.balance=ib;s.ot=None;s.closed=[]
        s.tc=0;s.running=False;s.peak=ib
        os.makedirs("data",exist_ok=True)
        s._load()

    def _load(s):
        try:
            if os.path.exists(PF):
                with open(PF) as f:
                    d=json.load(f)
                    s.balance=d.get("balance",s.ib)
                    s.tc=d.get("tc",0)
                    s.peak=d.get("peak",s.ib)
                    s.closed=d.get("closed",[])
                    logger.info(f"Loaded: ${s.balance:,.2f} | {len(s.closed)} trades")
        except:pass

    def _save(s):
        try:
            with open(PF,"w") as f:
                json.dump({"balance":s.balance,"tc":s.tc,"peak":s.peak,
                    "closed":s.closed[-500:],"updated":str(datetime.utcnow())
                },f,indent=2,default=str)
        except Exception as e:
            logger.error(f"Save: {e}")

    def start(s):
        print(f"""
{'='*55}
  Paper Trading Mode
  Balance: ${s.balance:,.2f}
  Symbol:  {s.config.SYMBOL}
  TF:      {s.config.TF_ENTRY} / {s.config.TF_STRUCTURE}
  Ctrl+C to stop
{'='*55}
        """)
        s.running=True;cy=0
        iv={"1m":55,"3m":170,"5m":290,"15m":890,"30m":1790,"1h":3590,"4h":14390}
        sleep_time=iv.get(s.config.TF_ENTRY,890)
        logger.info(f"Cycle: every {sleep_time}s ({sleep_time//60}m)")

        while s.running:
            try:
                cy+=1
                s._cycle(cy)
                if cy%10==0:s._stats()

                for _ in range(sleep_time):
                    if not s.running:break
                    time.sleep(1)

            except KeyboardInterrupt:
                print("\n  Stopping...")
                s._save()
                s._stats()
                s._final_report()
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                time.sleep(30)

    def _cycle(s,cy):
        # Fetch data
        df=s.exchange.fetch_ohlcv(
            s.config.SYMBOL,s.config.TF_ENTRY,500)
        htf=s.exchange.fetch_ohlcv(
            s.config.SYMBOL,s.config.TF_STRUCTURE,200)

        if df.empty:
            logger.warning("No data")
            return

        p=df["close"].iloc[-1]
        h=df["high"].iloc[-1]
        l=df["low"].iloc[-1]

        if cy%5==0:
            logger.info(f"#{cy} | ${p:,.2f} | {datetime.utcnow().strftime('%H:%M')}")

        # Check open trade
        if s.ot and s.ot.is_open:
            closed=s.ot.check_exit(p,h,l)
            if closed:
                s.balance+=s.ot.pnl
                s.peak=max(s.peak,s.balance)
                emoji="+" if s.ot.pnl>0 else ""
                win="WIN" if s.ot.pnl>0 else "LOSS"

                logger.info(f"  {win} #{s.ot.id} | ${emoji}{s.ot.pnl:.2f} "
                          f"({s.ot.pnl_pct:+.2f}%) | {s.ot.exit_reason} "
                          f"| Balance: ${s.balance:,.2f}")

                s.closed.append(s.ot.to_dict())
                s.ot=None
                s._save()
            else:
                # Show unrealized PnL
                if s.ot.direction=="long":
                    ur=(p-s.ot.entry_price)/s.ot.entry_price*100
                else:
                    ur=(s.ot.entry_price-p)/s.ot.entry_price*100
                if cy%5==0:
                    logger.debug(f"  Open: {s.ot.direction} | uPnL: {ur:+.2f}% | SL: ${s.ot.current_sl:,.2f}")
            return

        # Analyze
        a=s.strategy.analyze(df,htf)

        # ML filter
        if s.config.ML_ENABLED and a["signal"]!="NO_SIGNAL":
            ml=s.ml.predict(a.get("features",{}))
            if ml.get("model_ready") and not ml.get("should_trade"):
                return

        # Check signal
        if a["signal"] in ["STRONG_BUY","STRONG_SELL","BUY","SELL"]:
            conf=a.get("confidence",0)
            if a["signal"] in ["BUY","SELL"] and conf<0.55:
                return

            e=a["entry"];sl=a["stop_loss"];tp=a["take_profit"]
            if not e or not sl or not tp:return

            ru=abs(e-sl)
            if ru<=0:return

            # Position size
            risk_amt=s.balance*s.config.RISK_PER_TRADE*conf
            sz=risk_amt/ru

            s.tc+=1
            s.ot=PaperTrade(s.tc,a["direction"],e,sl,tp,sz,a["signal"],conf)

            risk_pct=ru/e*100
            rr=abs(tp-e)/ru

            logger.info(f"  NEW #{s.tc} | {a['signal']} {a['direction'].upper()}")
            logger.info(f"  Entry: ${e:,.2f} | SL: ${sl:,.2f} ({risk_pct:.2f}%)")
            logger.info(f"  TP: ${tp:,.2f} | R:R = 1:{rr:.1f}")
            logger.info(f"  Size: {sz:.6f} | Risk: ${risk_amt:.2f}")

            s._save()

    def _stats(s):
        if not s.closed:
            logger.info(f"Paper | ${s.balance:,.2f} | No trades yet")
            return

        pnls=[t["pnl"] for t in s.closed]
        w=[p for p in pnls if p>0]
        l=[p for p in pnls if p<=0]
        wr=len(w)/len(pnls)*100
        total_pnl=sum(pnls)
        ret=(s.balance-s.ib)/s.ib*100
        dd=(s.peak-s.balance)/s.peak*100 if s.peak>0 else 0

        open_info="None"
        if s.ot and s.ot.is_open:
            open_info=f"{s.ot.direction} @${s.ot.entry_price:,.2f}"

        print(f"""
{'='*55}
  PAPER TRADING STATUS
  Balance:   ${s.balance:,.2f} ({ret:+.2f}%)
  PnL:       ${total_pnl:+,.2f}
  Trades:    {len(pnls)} ({len(w)}W / {len(l)}L)
  Win Rate:  {wr:.1f}%
  Drawdown:  {dd:.1f}%
  Open:      {open_info}
{'='*55}
        """)

    def _final_report(s):
        if not s.closed:return
        pnls=[t["pnl"] for t in s.closed]
        w=[p for p in pnls if p>0]
        l=[p for p in pnls if p<=0]

        print(f"""
{'='*55}
  FINAL PAPER TRADING REPORT
{'='*55}
  Initial:   ${s.ib:,.2f}
  Final:     ${s.balance:,.2f}
  Return:    {(s.balance-s.ib)/s.ib*100:+.2f}%
  Trades:    {len(pnls)}
  Win Rate:  {len(w)/max(len(pnls),1)*100:.1f}%
  Avg Win:   ${sum(w)/max(len(w),1):+.2f}
  Avg Loss:  ${sum(l)/max(len(l),1):+.2f}
  PF:        {abs(sum(w))/max(abs(sum(l)),1):.2f}
{'='*55}
        """)

        # Last 10 trades
        print("  Last trades:")
        for t in s.closed[-10:]:
            emoji="+" if t["pnl"]>0 else ""
            print(f"  #{t['id']} {t['direction']:>5} {t['signal']:>12} "
                  f"${t['entry']:>9,.2f} -> ${t.get('exit',0):>9,.2f} "
                  f"${emoji}{t['pnl']:.2f} ({t.get('reason','?')})")


if __name__ == "__main__":
    trader = PaperTrader(10000)
    trader.start()
