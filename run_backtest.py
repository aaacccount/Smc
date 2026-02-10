#!/usr/bin/env python3
"""
Smart Money Backtest Engine v3
Interactive Menu + Smart Analysis
"""
import sys,os,json,argparse
import pandas as pd
import numpy as np
from datetime import datetime
from config import Config
from exchange.connector import ExchangeConnector
from strategy.smart_money import SmartMoneyStrategy
from backtesting.engine import BacktestEngine
from backtesting.reporter import BacktestReporter
from utils.logger import setup_logger
logger=setup_logger("BT")


def clear():
    os.system('clear' if os.name=='posix' else 'cls')


def colored(text,color):
    colors={"green":"\033[92m","red":"\033[91m","yellow":"\033[93m",
            "blue":"\033[94m","cyan":"\033[96m","white":"\033[97m",
            "bold":"\033[1m","end":"\033[0m"}
    return f"{colors.get(color,'')}{text}{colors['end']}"


def fetch_data(exchange,symbol,tf,htf,days):
    """دریافت داده با نمایش پیشرفت"""
    print(f"\n  {colored('Fetching data...','cyan')}")
    tfm={"1m":1,"3m":3,"5m":5,"15m":15,"30m":30,"1h":60,"2h":120,"4h":240,"1d":1440}
    minutes=tfm.get(tf,15)
    candles_needed=min((days*24*60)//minutes,1500)
    htf_minutes=tfm.get(htf,240)
    htf_candles=min((days*24*60)//htf_minutes,500)

    print(f"  Requesting {candles_needed} candles ({tf})...")
    df=exchange.fetch_ohlcv_extended(symbol,tf,days) if hasattr(exchange,"fetch_ohlcv_extended") else exchange.fetch_ohlcv(symbol,tf,int(candles_needed))

    print(f"  Requesting {htf_candles} candles ({htf})...")
    htf_df=exchange.fetch_ohlcv(symbol,htf,int(htf_candles))

    if df.empty:
        print(colored("  No data received!","red"))
        return None,None

    actual_days=(df.index[-1]-df.index[0]).days
    print(f"  {colored('OK','green')} {len(df)} candles ({tf}) = {actual_days} days")
    print(f"  {colored('OK','green')} {len(htf_df)} candles ({htf})")
    print(f"  Period: {str(df.index[0])[:16]} -> {str(df.index[-1])[:16]}")

    if actual_days<days*0.5:
        print(colored(f"\n  Warning: Got {actual_days}d instead of {days}d","yellow"))
        print(colored(f"  Exchange limit. Try larger timeframe.","yellow"))

    return df,htf_df


def analyze_trades(report):
    """تحلیل هوشمند معاملات - پیدا کردن مشکلات"""
    if "error" in report or not report.get("trades"):
        return []

    issues=[]
    trades=report["trades"]
    su=report["summary"]

    # 1. SL Analysis
    sl_hits=[t for t in trades if t.get("exit_reason")=="stop_loss"]
    tp_hits=[t for t in trades if t.get("exit_reason")=="take_profit"]
    sl_pct=len(sl_hits)/max(len(trades),1)*100

    if sl_pct>65:
        # Check if SL is too tight
        avg_adverse=np.mean([abs(t.get("entry_price",0)-t.get("stop_loss",0))/max(t.get("entry_price",1),1)*100 for t in trades])
        issues.append({
            "type":"SL_TOO_TIGHT",
            "severity":"HIGH",
            "detail":f"Stop Loss hit {sl_pct:.0f}% of trades. Avg SL distance: {avg_adverse:.2f}%",
            "fix":"Increase SL distance or use ATR-based SL. Try RISK_REWARD_RATIO=2.0 or SWING_LOOKBACK=15"
        })

    # 2. R-Multiple Analysis
    r_mults=[t.get("r_multiple",0) for t in trades]
    negative_r=[r for r in r_mults if r<0]
    if negative_r:
        avg_neg_r=np.mean(negative_r)
        if avg_neg_r<-0.8:
            issues.append({
                "type":"FULL_SL_HITS",
                "severity":"MEDIUM",
                "detail":f"Average losing R: {avg_neg_r:.2f}R - Trades hitting full SL",
                "fix":"Consider adding trailing stop or break-even earlier"
            })

    # 3. Direction Imbalance
    longs=[t for t in trades if t["direction"]=="long"]
    shorts=[t for t in trades if t["direction"]=="short"]
    if len(longs)>0 and len(shorts)==0:
        issues.append({
            "type":"NO_SHORTS",
            "severity":"MEDIUM",
            "detail":"No short trades taken. Strategy is long-only.",
            "fix":"Check bearish signal thresholds. May need to lower SELL confluence requirement."
        })
    elif len(shorts)>0 and len(longs)==0:
        issues.append({
            "type":"NO_LONGS",
            "severity":"MEDIUM",
            "detail":"No long trades taken.",
            "fix":"Check bullish signal thresholds."
        })

    # 4. Win Rate by Signal
    if report.get("signal_stats"):
        for sig,stats in report["signal_stats"].items():
            if stats["trades"]>=3 and stats["win_rate"]<30:
                issues.append({
                    "type":"WEAK_SIGNAL",
                    "severity":"HIGH",
                    "detail":f"Signal '{sig}' has {stats['win_rate']}% WR ({stats['trades']} trades)",
                    "fix":f"Consider disabling '{sig}' or increasing confidence threshold"
                })

    # 5. Consecutive Losses
    max_consec=0;current=0
    for t in trades:
        if t["pnl"]<=0:current+=1;max_consec=max(max_consec,current)
        else:current=0
    if max_consec>=5:
        issues.append({
            "type":"LONG_LOSING_STREAK",
            "severity":"HIGH",
            "detail":f"Max {max_consec} consecutive losses",
            "fix":"Add cool-down period or reduce position size after 3 losses"
        })

    # 6. Time Analysis
    try:
        win_hours=[]
        lose_hours=[]
        for t in trades:
            hour=pd.Timestamp(t["entry_time"]).hour
            if t["pnl"]>0:win_hours.append(hour)
            else:lose_hours.append(hour)
        if win_hours and lose_hours:
            best_hours=pd.Series(win_hours).value_counts().head(3).index.tolist()
            worst_hours=pd.Series(lose_hours).value_counts().head(3).index.tolist()
            issues.append({
                "type":"TIME_ANALYSIS",
                "severity":"INFO",
                "detail":f"Best hours (UTC): {best_hours} | Worst: {worst_hours}",
                "fix":"Consider limiting trading to best performing hours"
            })
    except:pass

    # 7. Volume Analysis
    big_wins=[t for t in trades if t["pnl"]>0 and t["r_multiple"]>1.5]
    big_losses=[t for t in trades if t["pnl"]<0 and t["r_multiple"]<-0.9]
    if len(big_losses)>len(big_wins)*2:
        issues.append({
            "type":"ASYMMETRIC_RESULTS",
            "severity":"MEDIUM",
            "detail":f"Big losses ({len(big_losses)}) >> Big wins ({len(big_wins)})",
            "fix":"R:R ratio may be too aggressive or entries are poorly timed"
        })

    # 8. Drawdown Duration
    if su["max_drawdown_pct"]>20:
        issues.append({
            "type":"HIGH_DRAWDOWN",
            "severity":"HIGH",
            "detail":f"Max drawdown {su['max_drawdown_pct']}% is too high",
            "fix":"Reduce RISK_PER_TRADE to 0.01 or add max drawdown stop"
        })

    # 9. Trade Frequency
    if su["total_candles"]>0:
        trades_per_100=len(trades)/(su["total_candles"]/100)
        if trades_per_100<0.5:
            issues.append({
                "type":"LOW_FREQUENCY",
                "severity":"INFO",
                "detail":f"Only {trades_per_100:.1f} trades per 100 candles",
                "fix":"Lower confluence threshold or add more signal types"
            })
        elif trades_per_100>5:
            issues.append({
                "type":"OVERTRADING",
                "severity":"MEDIUM",
                "detail":f"{trades_per_100:.1f} trades per 100 candles - overtrading",
                "fix":"Increase confluence threshold or add more filters"
            })

    # 10. Profit Factor Components
    if su["profit_factor"]<1.0:
        issues.append({
            "type":"LOSING_STRATEGY",
            "severity":"CRITICAL",
            "detail":f"Profit Factor {su['profit_factor']} < 1.0 - Strategy loses money!",
            "fix":"Major changes needed: review entry logic, SL/TP levels, or confluence requirements"
        })

    # 11. Entry Timing
    early_sl=[t for t in sl_hits if t.get("r_multiple",0)>-0.3]
    if len(early_sl)>len(sl_hits)*0.3 and len(sl_hits)>3:
        issues.append({
            "type":"SL_TOO_CLOSE",
            "severity":"HIGH",
            "detail":f"{len(early_sl)}/{len(sl_hits)} SL hits were very close to entry",
            "fix":"SL is too tight. Use wider SL with smaller position size."
        })

    return issues


def display_analysis(issues):
    """نمایش تحلیل هوشمند"""
    if not issues:
        print(colored("\n  No significant issues found!","green"))
        return

    sev_colors={"CRITICAL":"red","HIGH":"red","MEDIUM":"yellow","INFO":"cyan"}
    sev_icons={"CRITICAL":"!!!","HIGH":"!!","MEDIUM":"!","INFO":"i"}

    print(f"\n{'='*60}")
    print(colored("  SMART ANALYSIS - Issues & Recommendations","bold"))
    print(f"{'='*60}")

    for i,issue in enumerate(issues,1):
        sev=issue["severity"]
        color=sev_colors.get(sev,"white")
        icon=sev_icons.get(sev,"?")

        print(f"\n  [{icon}] {colored(issue['type'],color)} ({sev})")
        print(f"      {issue['detail']}")
        print(colored(f"      Fix: {issue['fix']}","green"))

    print(f"\n{'='*60}")

    # Summary
    critical=len([i for i in issues if i["severity"]=="CRITICAL"])
    high=len([i for i in issues if i["severity"]=="HIGH"])
    medium=len([i for i in issues if i["severity"]=="MEDIUM"])

    if critical>0:
        print(colored("  VERDICT: Strategy needs major fixes before use!","red"))
    elif high>=2:
        print(colored("  VERDICT: Several issues need attention","yellow"))
    elif high==1:
        print(colored("  VERDICT: Minor issues, fixable with parameter tuning","yellow"))
    else:
        print(colored("  VERDICT: Strategy looks reasonable","green"))

    print(f"{'='*60}")


def display_trade_log(trades,limit=20):
    """نمایش لیست معاملات"""
    if not trades:
        print("  No trades");return

    print(f"\n{'='*75}")
    print(f"  {'#':>3} {'Dir':>5} {'Signal':>12} {'Entry':>10} {'Exit':>10} {'PnL':>10} {'R':>6} {'Reason':>8}")
    print(f"  {'-'*72}")

    for t in trades[-limit:]:
        pnl_color="green" if t["pnl"]>0 else "red"
        pnl_str=colored(f"${t['pnl']:+8.2f}",pnl_color)
        r_str=colored(f"{t['r_multiple']:+5.2f}R",pnl_color)
        reason=t.get("exit_reason","?")[:8]
        print(f"  {t['id']:>3} {t['direction']:>5} {t['signal']:>12} ${t['entry_price']:>9,.2f} ${t.get('exit_price',0):>9,.2f} {pnl_str} {r_str} {reason:>8}")

    print(f"{'='*75}")


def auto_optimize(exchange,symbol,tf,htf,df,htf_df):
    """بهینه‌سازی خودکار"""
    import itertools
    print(colored("\n  AUTO-OPTIMIZATION","bold"))
    print(f"{'='*55}")

    grid={
        "RISK_PER_TRADE":[0.01,0.015,0.02,0.025],
        "RISK_REWARD_RATIO":[1.5,2.0,2.5,3.0],
        "SWING_LOOKBACK":[5,8,10,15],
        "OB_LOOKBACK":[30,50,70],
    }

    combos=list(itertools.product(*grid.values()))
    keys=list(grid.keys())
    results=[]
    total=len(combos)

    print(f"  Testing {total} parameter combinations...\n")

    for i,combo in enumerate(combos):
        params=dict(zip(keys,combo))
        try:
            cfg=Config()
            for k,v in params.items():setattr(cfg,k,v)
            st=SmartMoneyStrategy();st.config=cfg
            en=BacktestEngine(st);en.config=cfg
            r=en.run(df.copy(),htf_df,progress=False)
            if "error" not in r:
                s=r["summary"]
                score=0
                score+=min(s["total_return_pct"],200)*0.25
                score+=s["win_rate"]*0.2
                score+=min(s["profit_factor"],5)*8*0.2
                score-=s["max_drawdown_pct"]*0.2
                score+=min(s["sharpe_ratio"],3)*10*0.15
                if s["total_trades"]>=5:score+=5

                results.append({
                    "params":params,"score":round(score,1),
                    "ret":s["total_return_pct"],"wr":s["win_rate"],
                    "pf":s["profit_factor"],"dd":s["max_drawdown_pct"],
                    "sh":s["sharpe_ratio"],"trades":s["total_trades"],
                })
        except:pass

        if (i+1)%20==0 or i==total-1:
            pct=(i+1)/total*100
            bar="█"*int(pct//5)+"░"*(20-int(pct//5))
            best_sc=max((r["score"] for r in results),default=0)
            print(f"  [{bar}] {pct:.0f}% | Best: {best_sc:.1f}",end="\r")

    print("\n")

    if not results:
        print(colored("  No valid results!","red"));return

    results.sort(key=lambda x:x["score"],reverse=True)

    print(f"  {'='*70}")
    print(f"  {'#':>3} {'Return':>8} {'WR':>6} {'PF':>6} {'DD':>7} {'Sharpe':>7} {'Trades':>6} {'Score':>6}")
    print(f"  {'-'*67}")

    for i,r in enumerate(results[:10],1):
        color="green" if i<=3 else "white"
        print(colored(
            f"  {i:>3} {r['ret']:>+7.1f}% {r['wr']:>5.1f}% {r['pf']:>5.2f} "
            f"{r['dd']:>6.1f}% {r['sh']:>6.2f} {r['trades']:>5} {r['score']:>5.1f}",
            color))

    best=results[0]
    print(f"\n  {colored('BEST PARAMETERS:','green')}")
    print(f"  {'='*40}")
    for k,v in best["params"].items():
        print(f"  {k} = {v}")
    print(f"  {'='*40}")

    # Save to file
    apply=input(f"\n  Apply these settings to .env? (y/n): ").strip().lower()
    if apply=="y":
        try:
            env_path=os.path.join(os.path.dirname(__file__),".env")
            with open(env_path,"r") as f:content=f.read()
            for k,v in best["params"].items():
                import re
                pattern=f"^{k}=.*$"
                replacement=f"{k}={v}"
                content=re.sub(pattern,replacement,content,flags=re.MULTILINE)
            with open(env_path,"w") as f:f.write(content)
            print(colored("  Settings applied to .env!","green"))
        except Exception as e:
            print(f"  Could not update .env: {e}")
            print(f"  Manually update with values above")


def interactive_menu():
    """منوی تعاملی"""
    config=Config()
    exchange=ExchangeConnector()

    while True:
        clear()
        print(colored("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║    📊  Smart Money Backtest Engine v3                    ║
║                                                          ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║    1️⃣   Quick Backtest (90 days)                        ║
║    2️⃣   Custom Backtest                                 ║
║    3️⃣   Scalping Mode (1m/5m)                           ║
║    4️⃣   Swing Mode (4h/1d)                              ║
║    5️⃣   Multi-Timeframe Test                            ║
║    6️⃣   Auto-Optimize                                   ║
║    7️⃣   Compare Timeframes                              ║
║    8️⃣   Full Analysis (Best)                            ║
║    9️⃣   View Last Results                               ║
║    0️⃣   Exit                                            ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
        ""","cyan"))

        print(f"  Current: {config.SYMBOL} | {config.TF_ENTRY} | {config.EXCHANGE}")
        choice=input(f"\n  Select (0-9): ").strip()

        if choice=="0":
            print("\n  Goodbye!\n");break

        elif choice=="1":
            quick_backtest(exchange,config)

        elif choice=="2":
            custom_backtest(exchange,config)

        elif choice=="3":
            scalping_backtest(exchange,config)

        elif choice=="4":
            swing_backtest(exchange,config)

        elif choice=="5":
            multi_tf_backtest(exchange,config)

        elif choice=="6":
            optimization_menu(exchange,config)

        elif choice=="7":
            compare_timeframes(exchange,config)

        elif choice=="8":
            full_analysis(exchange,config)

        elif choice=="9":
            view_results()

        else:
            print("  Invalid choice")

        input(colored("\n  Press Enter to continue...","cyan"))


def quick_backtest(exchange,config):
    """بک‌تست سریع 90 روزه"""
    print(colored("\n  QUICK BACKTEST - 90 Days","bold"))
    symbol=config.SYMBOL
    tf=config.TF_ENTRY
    htf=config.TF_STRUCTURE

    df,htf_df=fetch_data(exchange,symbol,tf,htf,90)
    if df is None:return

    st=SmartMoneyStrategy()
    en=BacktestEngine(st,10000)
    report=en.run(df,htf_df)

    rp=BacktestReporter()
    rp.display(report)

    issues=analyze_trades(report)
    display_analysis(issues)

    save=input("\n  Save results? (y/n): ").strip().lower()
    if save=="y":
        rp.save(report,f"quick_{symbol.replace('/','_')}_{tf}")


def custom_backtest(exchange,config):
    """بک‌تست سفارشی"""
    print(colored("\n  CUSTOM BACKTEST","bold"))

    symbol=input(f"  Symbol [{config.SYMBOL}]: ").strip() or config.SYMBOL

    print("\n  Timeframes:")
    print("    1) 1m    2) 3m    3) 5m    4) 15m")
    print("    5) 30m   6) 1h    7) 4h    8) 1d")
    tf_map={"1":"1m","2":"3m","3":"5m","4":"15m","5":"30m","6":"1h","7":"4h","8":"1d"}
    tf_choice=input(f"  Entry TF [{config.TF_ENTRY}]: ").strip()
    tf=tf_map.get(tf_choice,config.TF_ENTRY)

    htf_choice=input(f"  HTF [{config.TF_STRUCTURE}]: ").strip()
    htf=tf_map.get(htf_choice,config.TF_STRUCTURE)

    print("\n  Period:")
    print("    1) 7 days    2) 30 days   3) 90 days")
    print("    4) 180 days  5) 365 days  6) Custom")
    day_map={"1":7,"2":30,"3":90,"4":180,"5":365}
    day_choice=input("  Select [3]: ").strip() or "3"
    if day_choice=="6":
        days=int(input("  Days: ").strip())
    else:
        days=day_map.get(day_choice,90)

    balance=input("  Balance [$10000]: ").strip()
    balance=float(balance) if balance else 10000

    df,htf_df=fetch_data(exchange,symbol,tf,htf,days)
    if df is None:return

    st=SmartMoneyStrategy()
    en=BacktestEngine(st,balance)
    report=en.run(df,htf_df)

    rp=BacktestReporter()
    rp.display(report)

    issues=analyze_trades(report)
    display_analysis(issues)

    show_trades=input("\n  Show trade log? (y/n): ").strip().lower()
    if show_trades=="y":
        display_trade_log(report.get("trades",[]))

    save=input("\n  Save? (y/n): ").strip().lower()
    if save=="y":
        rp.save(report,f"custom_{symbol.replace('/','_')}_{tf}_{days}d")


def scalping_backtest(exchange,config):
    """بک‌تست اسکلپ"""
    print(colored("\n  SCALPING BACKTEST","bold"))
    print("  Best for: Quick trades, small TFs\n")

    print("  Scalp Presets:")
    print("    1) Ultra Scalp:  1m entry, 5m HTF,  1 day")
    print("    2) Fast Scalp:   3m entry, 15m HTF, 3 days")
    print("    3) Normal Scalp: 5m entry, 1h HTF,  7 days")
    print("    4) Slow Scalp:   15m entry, 4h HTF, 14 days")

    choice=input("\n  Select [3]: ").strip() or "3"
    presets={
        "1":("1m","5m",1),
        "2":("3m","15m",3),
        "3":("5m","1h",7),
        "4":("15m","4h",14),
    }
    tf,htf,days=presets.get(choice,("5m","1h",7))

    # Adjust params for scalping
    symbol=config.SYMBOL
    df,htf_df=fetch_data(exchange,symbol,tf,htf,days)
    if df is None:return

    st=SmartMoneyStrategy()
    # Tighter params for scalp
    st.config.RISK_REWARD_RATIO=1.5
    st.config.SWING_LOOKBACK=5
    st.config.OB_LOOKBACK=30

    en=BacktestEngine(st,10000,commission=0.0008,slippage=0.0003)
    en.config.RISK_REWARD_RATIO=1.5
    report=en.run(df,htf_df)

    rp=BacktestReporter()
    rp.display(report)

    issues=analyze_trades(report)
    display_analysis(issues)

    save=input("\n  Save? (y/n): ").strip().lower()
    if save=="y":
        rp.save(report,f"scalp_{tf}_{days}d")


def swing_backtest(exchange,config):
    """بک‌تست سوئینگ"""
    print(colored("\n  SWING TRADING BACKTEST","bold"))
    print("  Best for: Longer holds, bigger moves\n")

    print("  Swing Presets:")
    print("    1) Short Swing:  1h entry, 4h HTF,  30 days")
    print("    2) Medium Swing: 4h entry, 1d HTF,  90 days")
    print("    3) Long Swing:   1d entry, 1d HTF,  180 days")

    choice=input("\n  Select [2]: ").strip() or "2"
    presets={
        "1":("1h","4h",30),
        "2":("4h","1d",90),
        "3":("1d","1d",180),
    }
    tf,htf,days=presets.get(choice,("4h","1d",90))

    symbol=config.SYMBOL
    df,htf_df=fetch_data(exchange,symbol,tf,htf,days)
    if df is None:return

    st=SmartMoneyStrategy()
    st.config.RISK_REWARD_RATIO=3.0
    st.config.SWING_LOOKBACK=15
    st.config.OB_LOOKBACK=70

    en=BacktestEngine(st,10000,commission=0.0004,slippage=0.0001)
    en.config.RISK_REWARD_RATIO=3.0
    report=en.run(df,htf_df)

    rp=BacktestReporter()
    rp.display(report)

    issues=analyze_trades(report)
    display_analysis(issues)

    save=input("\n  Save? (y/n): ").strip().lower()
    if save=="y":
        rp.save(report,f"swing_{tf}_{days}d")


def multi_tf_backtest(exchange,config):
    """تست مولتی تایم‌فریم"""
    print(colored("\n  MULTI-TIMEFRAME COMPARISON","bold"))
    print("  Tests same strategy on different timeframes\n")

    symbol=config.SYMBOL
    timeframes=[
        ("5m","1h",7,"Scalp 5m"),
        ("15m","4h",30,"Intraday 15m"),
        ("1h","4h",60,"Swing 1h"),
        ("4h","1d",90,"Position 4h"),
    ]

    results={}
    for tf,htf,days,name in timeframes:
        print(f"\n  Testing {name}...")
        df,htf_df=fetch_data(exchange,symbol,tf,htf,days)
        if df is None:continue

        st=SmartMoneyStrategy()
        en=BacktestEngine(st,10000)
        report=en.run(df,htf_df,progress=False)

        if "error" not in report:
            results[name]=report
            s=report["summary"]
            color="green" if s["total_return_pct"]>0 else "red"
            print(colored(f"    Result: {s['total_return_pct']:+.1f}% | WR:{s['win_rate']}% | {s['total_trades']}t",color))

    if len(results)>1:
        print(f"\n{'='*75}")
        print(colored("  COMPARISON TABLE","bold"))
        print(f"  {'Name':<18} {'Return':>8} {'WR':>6} {'PF':>6} {'DD':>7} {'Sharpe':>7} {'Trades':>6}")
        print(f"  {'-'*72}")

        for name,report in results.items():
            s=report["summary"]
            color="green" if s["total_return_pct"]>0 else "red"
            print(colored(
                f"  {name:<18} {s['total_return_pct']:>+7.1f}% {s['win_rate']:>5.1f}% "
                f"{s['profit_factor']:>5.2f} {s['max_drawdown_pct']:>6.1f}% "
                f"{s['sharpe_ratio']:>6.2f} {s['total_trades']:>5}",
                color))

        print(f"{'='*75}")

        best_name=max(results.keys(),key=lambda k:results[k]["summary"]["total_return_pct"])
        print(colored(f"\n  Best: {best_name}","green"))


def optimization_menu(exchange,config):
    """منوی بهینه‌سازی"""
    print(colored("\n  OPTIMIZATION","bold"))

    tf=input(f"  Timeframe [{config.TF_ENTRY}]: ").strip() or config.TF_ENTRY
    htf=input(f"  HTF [{config.TF_STRUCTURE}]: ").strip() or config.TF_STRUCTURE
    days=int(input("  Days [90]: ").strip() or "90")

    df,htf_df=fetch_data(exchange,config.SYMBOL,tf,htf,days)
    if df is None:return

    auto_optimize(exchange,config.SYMBOL,tf,htf,df,htf_df)


def compare_timeframes(exchange,config):
    """مقایسه تایم‌فریم‌ها"""
    multi_tf_backtest(exchange,config)


def full_analysis(exchange,config):
    """تحلیل کامل"""
    print(colored("\n  FULL ANALYSIS","bold"))
    print("  Running comprehensive backtest with smart analysis...\n")

    symbol=config.SYMBOL
    tf=input(f"  Timeframe [{config.TF_ENTRY}]: ").strip() or config.TF_ENTRY
    htf=input(f"  HTF [{config.TF_STRUCTURE}]: ").strip() or config.TF_STRUCTURE
    days=int(input("  Days [90]: ").strip() or "90")

    df,htf_df=fetch_data(exchange,symbol,tf,htf,days)
    if df is None:return

    st=SmartMoneyStrategy()
    en=BacktestEngine(st,10000)
    report=en.run(df,htf_df)

    # Display results
    rp=BacktestReporter()
    rp.display(report)

    # Smart analysis
    issues=analyze_trades(report)
    display_analysis(issues)

    # Trade log
    if report.get("trades"):
        print(f"\n  Total trades: {len(report['trades'])}")
        show=input("  Show trade log? (y/n): ").strip().lower()
        if show=="y":
            limit=input("  How many? [20]: ").strip()
            limit=int(limit) if limit else 20
            display_trade_log(report["trades"],limit)

    # Recommendations
    print(colored("\n  RECOMMENDATIONS","bold"))
    print(f"  {'='*50}")

    su=report["summary"]
    if su["profit_factor"]<1:
        print(colored("  1. Strategy is losing money - DO NOT trade live","red"))
        print("  2. Run optimization (option 6)")
        print("  3. Try different timeframes (option 7)")
    elif su["win_rate"]<40:
        print("  1. Win rate is low - increase R:R ratio")
        print("  2. Try tighter entry criteria")
        print("  3. Run optimization to find better params")
    elif su["max_drawdown_pct"]>25:
        print("  1. Drawdown too high - reduce risk per trade")
        print("  2. Add daily loss limit")
        print("  3. Consider position sizing adjustment")
    elif su["profit_factor"]>=1.5 and su["win_rate"]>=45:
        print(colored("  Strategy looks promising!","green"))
        print("  1. Run paper trading for 1-2 weeks")
        print("  2. Then demo trade for 1 week")
        print("  3. Then live with 5-10% of capital")
    else:
        print("  1. Run optimization for better parameters")
        print("  2. Test on multiple timeframes")
        print("  3. Paper trade before going live")

    print(f"  {'='*50}")

    save=input("\n  Save full report? (y/n): ").strip().lower()
    if save=="y":
        rp.save(report,f"full_{symbol.replace('/','_')}_{tf}_{days}d")


def view_results():
    """مشاهده نتایج قبلی"""
    rd="data/backtest_results"
    if not os.path.exists(rd):
        print("  No saved results");return

    files=[f for f in os.listdir(rd) if f.endswith(".json")]
    if not files:
        print("  No saved results");return

    print(colored("\n  SAVED RESULTS","bold"))
    print(f"  {'='*50}")
    for i,f in enumerate(sorted(files,reverse=True)[:10],1):
        try:
            with open(os.path.join(rd,f)) as fh:
                data=json.load(fh)
            s=data["summary"]
            color="green" if s["total_return_pct"]>0 else "red"
            print(colored(f"  {i}. {f}: {s['total_return_pct']:+.1f}% | WR:{s['win_rate']}% | {s['total_trades']}t",color))
        except:
            print(f"  {i}. {f}: (error reading)")

    choice=input("\n  View details (number) or Enter to skip: ").strip()
    if choice.isdigit():
        idx=int(choice)-1
        if 0<=idx<len(files):
            with open(os.path.join(rd,sorted(files,reverse=True)[idx])) as f:
                data=json.load(f)
            rp=BacktestReporter()
            rp.display(data)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--menu",action="store_true",help="Interactive menu")
    p.add_argument("--symbol",type=str,default=None)
    p.add_argument("--timeframe",type=str,default=None)
    p.add_argument("--htf",type=str,default=None)
    p.add_argument("--days",type=int,default=90)
    p.add_argument("--balance",type=float,default=10000)
    p.add_argument("--commission",type=float,default=0.0006)
    p.add_argument("--slippage",type=float,default=0.0002)
    p.add_argument("--save",action="store_true")
    p.add_argument("--optimize",action="store_true")
    p.add_argument("--analyze",action="store_true")
    a=p.parse_args()

    # Default to menu if no args
    if len(sys.argv)==1 or a.menu:
        interactive_menu()
        return

    # Command line mode
    c=Config()
    exc=ExchangeConnector()
    sym=a.symbol or c.SYMBOL
    tf=a.timeframe or c.TF_ENTRY
    htf=a.htf or c.TF_STRUCTURE

    if a.optimize:
        df,htf_df=fetch_data(exc,sym,tf,htf,a.days)
        if df is not None:
            auto_optimize(exc,sym,tf,htf,df,htf_df)
    else:
        df,htf_df=fetch_data(exc,sym,tf,htf,a.days)
        if df is None:return
        st=SmartMoneyStrategy()
        en=BacktestEngine(st,a.balance,a.commission,a.slippage)
        report=en.run(df,htf_df)
        rp=BacktestReporter();rp.display(report)

        if a.analyze or True:
            issues=analyze_trades(report)
            display_analysis(issues)

        if a.save:
            rp.save(report,f"{sym.replace('/','_')}_{tf}_{a.days}d")

if __name__=="__main__":main()
