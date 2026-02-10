import json,os
from datetime import datetime
from utils.logger import setup_logger
logger=setup_logger("Reporter")
RD="data/backtest_results"

class BacktestReporter:
    def __init__(s):os.makedirs(RD,exist_ok=True)
    def display(s,r):
        if "error" in r:print(f"\n  {r['error']}\n");return
        su=r["summary"];d=r["direction_stats"];g=s._grade(su)
        print("\n"+"="*58)
        print("  BACKTEST RESULTS")
        print("="*58)
        print(f"  Period: {su['period_start'][:10]} to {su['period_end'][:10]}")
        print(f"  Candles: {su['total_candles']}")
        print("-"*58)
        re="+" if su["total_return_pct"]>0 else ""
        print(f"  Return:       {re}{su['total_return_pct']:.2f}%")
        print(f"  Balance:      ${su['initial_balance']:,.2f} -> ${su['final_balance']:,.2f}")
        print(f"  Total PnL:    ${su['total_pnl']:+,.2f}")
        print("-"*58)
        print(f"  Trades:       {su['total_trades']} ({su['winning_trades']}W / {su['losing_trades']}L)")
        print(f"  Win Rate:     {su['win_rate']}%")
        print(f"  Profit Factor:{su['profit_factor']}")
        print(f"  Avg Win:      ${su['avg_win']:+,.2f}")
        print(f"  Avg Loss:     ${su['avg_loss']:+,.2f}")
        print(f"  Avg R:        {su['avg_r_multiple']}R")
        print("-"*58)
        print(f"  Max Drawdown: {su['max_drawdown_pct']}% (${su['max_drawdown']:,.2f})")
        print(f"  Sharpe:       {su['sharpe_ratio']}")
        print(f"  Sortino:      {su['sortino_ratio']}")
        print("-"*58)
        print(f"  Long:  {d['long_trades']}t WR:{d['long_win_rate']}% PnL:${d['long_pnl']:+,.2f}")
        print(f"  Short: {d['short_trades']}t WR:{d['short_win_rate']}% PnL:${d['short_pnl']:+,.2f}")
        if r.get("signal_stats"):
            print("-"*58)
            for sig,st in r["signal_stats"].items():
                print(f"  {sig}: {st['trades']}t WR:{st['win_rate']}% ${st['pnl']:+,.2f}")
        if r.get("monthly_returns"):
            print("-"*58)
            for m,ret in list(r["monthly_returns"].items())[-6:]:
                print(f"  {m}: ${ret:+8,.2f}")
        print("="*58)
        print(f"  GRADE: {g['grade']} ({g['score']}/100) - {g['verdict']}")
        print("="*58+"\n")
    def _grade(s,su):
        sc=0
        if su["win_rate"]>=60:sc+=20
        elif su["win_rate"]>=50:sc+=15
        elif su["win_rate"]>=40:sc+=10
        if su["profit_factor"]>=2:sc+=25
        elif su["profit_factor"]>=1.5:sc+=20
        elif su["profit_factor"]>=1.2:sc+=15
        elif su["profit_factor"]>=1:sc+=8
        if su["total_return_pct"]>=100:sc+=20
        elif su["total_return_pct"]>=50:sc+=15
        elif su["total_return_pct"]>=20:sc+=10
        elif su["total_return_pct"]>0:sc+=5
        if su["max_drawdown_pct"]<10:sc+=20
        elif su["max_drawdown_pct"]<15:sc+=15
        elif su["max_drawdown_pct"]<25:sc+=10
        if su["sharpe_ratio"]>=2:sc+=15
        elif su["sharpe_ratio"]>=1.5:sc+=12
        elif su["sharpe_ratio"]>=1:sc+=8
        gm={"85":"A+","75":"A","65":"B+","55":"B","45":"C","35":"D"}
        gr="F"
        for th,g in sorted(gm.items(),key=lambda x:int(x[0]),reverse=True):
            if sc>=int(th):gr=g;break
        vm={"A+":"EXCELLENT","A":"VERY GOOD","B+":"GOOD","B":"DECENT","C":"AVERAGE","D":"BELOW AVG","F":"POOR"}
        return {"grade":gr,"score":sc,"verdict":vm.get(gr,"POOR")}
    def save(s,r,name=None):
        if name is None:name=f"bt_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        fp=os.path.join(RD,f"{name}.json")
        try:
            with open(fp,"w") as f:
                json.dump({k:r[k] for k in ["summary","direction_stats","signal_stats","monthly_returns","trades"] if k in r},f,indent=2,default=str)
            print(f"  Saved: {fp}")
        except Exception as e:logger.error(f"Save: {e}")
