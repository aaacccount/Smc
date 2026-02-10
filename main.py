#!/usr/bin/env python3
"""
Smart Money Bot v2.2
python3 main.py              Live/Demo
python3 main.py paper        Paper Trading
python3 main.py backtest     Backtest
python3 main.py optimize     Optimize
python3 main.py status       Stats
"""
import sys,time
from datetime import datetime
from config import Config
from exchange.connector import ExchangeConnector
from strategy.smart_money import SmartMoneyStrategy
from risk_management.manager import RiskManager
from ml.brain import MLBrain
from utils.logger import setup_logger
from utils.notifier import TelegramNotifier
from utils.performance import PerformanceManager
logger=setup_logger("Main")

class SmartMoneyBot:
    def __init__(s):
        s.config=Config();s.exchange=ExchangeConnector();s.strategy=SmartMoneyStrategy()
        s.risk=RiskManager();s.ml=MLBrain();s.notif=TelegramNotifier();s.perf=PerformanceManager()
        s.trade=None;s.running=False;s.ptp=0;s.cy=0

    def start(s):
        print(f"\n{'='*55}")
        print(f"  Smart Money Bot v2.2 - Multi Timeframe + ML")
        print(f"{'='*55}")
        print(f"  Exchange:  {s.config.EXCHANGE}")
        print(f"  Symbol:    {s.config.SYMBOL}")
        print(f"  TFs:       {s.config.TF_DIRECTION} > {s.config.TF_STRUCTURE} > {s.config.TF_ENTRY} > {s.config.TF_SNIPER}")
        print(f"  Leverage:  {s.config.LEVERAGE}x")
        print(f"  Risk:      {s.config.RISK_PER_TRADE*100}%")
        print(f"  R:R:       1:{s.config.RISK_REWARD_RATIO}")
        print(f"  ML:        {s.config.ML_ENABLED}")
        print(f"  Mode:      {'TESTNET' if s.config.TESTNET else 'LIVE'}")
        print(f"{'='*55}")
        bal=s.exchange.get_balance()
        print(f"  Balance:   ${bal:,.2f}")
        print(f"{'='*55}\n")
        if bal<=0:
            print("  No balance! Check API keys.");return
        s.risk.peak_balance=max(s.risk.peak_balance,bal)
        if s.config.ML_ENABLED:
            ms=s.ml.get_stats()
            if not ms["model_ready"]:
                print("  Training ML...")
                df=s.perf.get_cached_candles(s.exchange,s.config.SYMBOL,s.config.TF_ENTRY,500)
                if len(df)>100:s.ml.generate_synthetic_data(df,s.strategy,200)
        s.running=True
        sl=s.perf.get_sleep_time()
        print(f"  Cycle: every {sl}s ({sl//60}m)")
        print(f"  Ctrl+C to stop\n")
        s.notif.send(f"<b>Bot Started</b>\n{s.config.SYMBOL}\nBalance: ${bal:.2f}")
        while s.running:
            try:
                t0=time.time();s._cycle();ct=time.time()-t0
                s.perf.record_cycle_time(ct);s.perf.optimize_memory()
                for _ in range(sl):
                    if not s.running:break
                    time.sleep(1)
            except KeyboardInterrupt:s._shutdown();break
            except Exception as e:logger.error(f"Error: {e}",exc_info=True);time.sleep(60)

    def _cycle(s):
        s.cy+=1;sym=s.config.SYMBOL
        edf=s.perf.get_cached_candles(s.exchange,sym,s.config.TF_ENTRY,500)
        sdf=s.perf.get_cached_candles(s.exchange,sym,s.config.TF_STRUCTURE,200)
        ddf=s.perf.get_cached_candles(s.exchange,sym,s.config.TF_DIRECTION,100)
        sndf=s.perf.get_cached_candles(s.exchange,sym,s.config.TF_SNIPER,200)
        if edf.empty:logger.warning("No data");return
        p=edf["close"].iloc[-1]
        if s.cy%5==0:logger.info(f"#{s.cy} | ${p:,.2f} | {datetime.utcnow().strftime('%H:%M:%S')}")
        if s.cy%20==0:s._status()
        if s.cy%240==0 and s.config.ML_ENABLED:
            ms=s.ml.get_stats()
            if ms["labeled_records"]>=s.config.ML_MIN_SAMPLES:s.ml.train()
        pos=s.exchange.get_position()
        if pos:s._manage(edf,pos,p);return
        bal=s.exchange.get_balance()
        can=s.risk.can_open_trade(bal)
        if not can["allowed"]:
            if s.cy%10==0:logger.info(f"Blocked: {can['reason']}")
            return
        a=s.strategy.analyze(edf,sdf,ddf,sndf)
        if s.config.ML_ENABLED and a.get("features"):
            s.ml.record_analysis(a["features"],a["signal"],p)
        ml={"should_trade":True,"ml_confidence":0.5}
        if s.config.ML_ENABLED and a["signal"]!="NO_SIGNAL":
            ml=s.ml.predict(a.get("features",{}))
            if not ml["should_trade"] and ml.get("model_ready"):
                logger.info(f"ML blocked: {a['signal']}");return
        if a["signal"] in ["STRONG_BUY","STRONG_SELL"]:s._exec(a,bal,ml)
        elif a["signal"] in ["BUY","SELL"] and a.get("confidence",0)>=0.55:s._exec(a,bal,ml)

    def _exec(s,a,bal,ml):
        e=a["entry"];sl=a["stop_loss"];tp=a["take_profit"]
        d=a["direction"];c=a.get("confidence",0.5);mc=ml.get("ml_confidence",0.5)
        logger.info("="*55)
        logger.info(f"SIGNAL: {a['signal']} | {d.upper()}")
        logger.info(f"Entry: ${e:,.2f} | SL: ${sl:,.2f} | TP: ${tp:,.2f}")
        logger.info(f"Conf: {c:.0%} | ML: {mc:.0%}")
        mode=a.get("analysis",{}).get("mode","")
        if mode=="MTF_4TF":
            an=a["analysis"]
            logger.info(f"Daily: {an.get('direction_bias','?')} | 4H: {an.get('structure_trend','?')}")
            logger.info(f"Sniper: {'YES' if an.get('sniper_confirmed') else 'NO'} | Score: {an.get('confluence_score',0)}/10")
        sz=s.risk.calculate_position_size(bal,e,sl,c,mc)
        if sz<=0:logger.warning("Size=0");return
        side="buy" if d=="long" else "sell"
        o=s.exchange.place_order(side=side,amount=sz,stop_loss=sl,take_profit=tp)
        if o:
            s.trade={"signal":a["signal"],"direction":d,"entry":e,"stop_loss":sl,
                "take_profit":tp,"size":sz,"original_sl":sl,"original_size":sz,
                "confidence":c,"ml_confidence":mc,"timestamp":datetime.utcnow()}
            s.ptp=0;logger.info(f"Executed! Size: {sz}")
            a["symbol"]=s.config.SYMBOL;a["ml_confidence"]=mc
            s.notif.send_signal(a)
        else:logger.error("Order FAILED!")
        logger.info("="*55)

    def _manage(s,df,pos,price):
        if not s.trade:return
        entry=s.trade["entry"];d=s.trade["direction"]
        atr=s.strategy.calculate_atr(df)
        be=s.risk.should_break_even(entry,price,d,s.trade["stop_loss"])
        if be and be!=s.trade["stop_loss"] and s.ptp==0:
            s.trade["stop_loss"]=be;logger.info(f"Break-even: ${be:,.2f}")
        ns=s.risk.calculate_trailing_stop(entry,price,d,s.trade["stop_loss"],atr)
        if ns!=s.trade["stop_loss"]:s.trade["stop_loss"]=ns
        pt=s.risk.partial_take_profit(entry,price,d,s.trade["original_sl"],s.ptp)
        if pt:
            csz=s.trade["size"]*pt["portion"];cs="sell" if d=="long" else "buy"
            try:
                s.exchange.exchange.create_order(s.config.SYMBOL,"market",cs,csz,params={"reduceOnly":True})
                s.ptp+=1;s.trade["size"]-=csz;logger.info(f"Partial TP at {pt['r_level']}R")
            except:pass
        s._check_closed()

    def _check_closed(s):
        pos=s.exchange.get_position()
        if pos is None and s.trade:
            entry=s.trade["entry"];d=s.trade["direction"]
            ticker=s.exchange.get_ticker();exit_p=ticker.get("last",entry)
            if d=="long":pnl_pct=(exit_p-entry)/entry
            else:pnl_pct=(entry-exit_p)/entry
            bal=s.exchange.get_balance();pnl_usd=pnl_pct*s.trade["size"]*entry
            s.risk.update_trade_result(pnl_usd,bal)
            if s.config.ML_ENABLED:s.ml.record_outcome(entry,exit_p,d)
            logger.info(f"Closed | PnL: {pnl_pct:+.2%} (${pnl_usd:+.2f})")
            s.notif.send_trade_result(pnl_usd,bal);s.trade=None;s.ptp=0

    def _status(s):
        bal=s.exchange.get_balance();rs=s.risk.get_stats();ps=s.perf.get_stats()
        logger.info("="*55)
        logger.info(f"Balance: ${bal:,.2f} | Daily: ${rs['daily_pnl']:+.2f} | Total: ${rs['total_pnl']:+.2f}")
        logger.info(f"Trades: {rs['total_trades']} | WR: {rs['win_rate']}% | PF: {rs.get('profit_factor',0)}")
        logger.info(f"Cycle: {ps['avg_cycle_time']} | Cache: {ps['cache']}")
        if s.config.ML_ENABLED:
            ms=s.ml.get_stats()
            logger.info(f"ML: {'Ready' if ms['model_ready'] else 'No'} | Acc: {ms['model_accuracy']}%")
        logger.info("="*55)

    def _shutdown(s):
        s.running=False;rs=s.risk.get_stats()
        print(f"\n{'='*55}")
        print(f"  Stopped | {rs['total_trades']}t | WR:{rs['win_rate']}% | PnL:${rs['total_pnl']:+.2f}")
        print(f"{'='*55}\n")
        s.notif.send(f"Bot Stopped\nPnL: ${rs['total_pnl']:+.2f}")

def show_status():
    print(f"\n{'='*45}\n  STATUS\n{'='*45}")
    c=Config()
    if c.ML_ENABLED:
        ml=MLBrain();ms=ml.get_stats()
        print(f"  ML: {'Ready' if ms['model_ready'] else 'No'} | Acc: {ms['model_accuracy']}%")
        print(f"  Records: {ms['total_records']} ({ms['labeled_records']} labeled)")
    rm=RiskManager();rs=rm.get_stats()
    print(f"  Trades: {rs['total_trades']} | WR: {rs['win_rate']}%")
    print(f"  PnL: ${rs['total_pnl']:+.2f} | PF: {rs.get('profit_factor',0)}")
    print(f"{'='*45}\n")

def main():
    mode=sys.argv[1] if len(sys.argv)>1 else "live"
    if mode=="paper":
        from paper_trading.simulator import PaperTrader
        PaperTrader(10000).start()
    elif mode=="backtest":
        from run_backtest import main as bt
        sys.argv=sys.argv[1:];bt()
    elif mode=="optimize":
        if "--optimize" not in sys.argv:sys.argv.append("--optimize")
        from run_backtest import main as bt
        sys.argv=sys.argv[1:];bt()
    elif mode=="status":show_status()
    else:SmartMoneyBot().start()

if __name__=="__main__":main()
