import ccxt
import pandas as pd
import time
from typing import Optional,Dict,List
from config import Config
from utils.logger import setup_logger
logger=setup_logger("Exchange")

class ExchangeConnector:
    def __init__(s):
        s.config=Config()
        s.exchange=s._create_trading()
        s.data_exchange=s._create_data()
        s._setup()

    def _create_trading(s):
        """صرافی برای ترید (توبیت)"""
        eid=s.config.EXCHANGE.lower()
        params={
            "apiKey":s.config.API_KEY,
            "secret":s.config.API_SECRET,
            "enableRateLimit":True,
            "timeout":30000,
            "options":{"defaultType":s.config.TRADE_MODE},
        }
        try:
            if hasattr(ccxt,eid):
                exc=getattr(ccxt,eid)(params)
                logger.info(f"Trading: {eid}")
                return exc
        except Exception as e:
            logger.warning(f"{eid}: {e}")
        try:
            exc=ccxt.bybit(params)
            logger.info("Trading: bybit-compatible")
            return exc
        except:pass
        logger.warning("Trading exchange failed, using binance")
        return ccxt.binance(params)

    def _create_data(s):
        """صرافی برای داده (بایننس - بدون API Key)"""
        try:
            exc=ccxt.binance({
                "enableRateLimit":True,
                "timeout":30000,
                "options":{"defaultType":"future"},
            })
            logger.info("Data source: Binance (public)")
            return exc
        except:
            logger.warning("Binance data fallback failed")
            return s.exchange

    def _setup(s):
        try:
            s.exchange.load_markets()
            s.data_exchange.load_markets()
            logger.info(f"Markets loaded")
            try:
                s.exchange.set_leverage(s.config.LEVERAGE,s.config.SYMBOL)
            except:pass
        except Exception as e:
            logger.warning(f"Setup: {e}")

    def fetch_ohlcv(s,symbol=None,timeframe=None,limit=500):
        """داده از بایننس (بیشتر و بهتر)"""
        symbol=symbol or s.config.SYMBOL
        timeframe=timeframe or s.config.TIMEFRAME

        # اول از بایننس بگیر (داده بیشتر)
        for src_name,src in [("binance",s.data_exchange),("trading",s.exchange)]:
            for attempt in range(3):
                try:
                    ohlcv=src.fetch_ohlcv(symbol,timeframe,limit=limit)
                    df=pd.DataFrame(ohlcv,columns=["timestamp","open","high","low","close","volume"])
                    df["timestamp"]=pd.to_datetime(df["timestamp"],unit="ms")
                    df.set_index("timestamp",inplace=True)
                    df=df.astype(float)

                    if len(df)>10:
                        days=(df.index[-1]-df.index[0]).days
                        logger.debug(f"Got {len(df)} candles ({timeframe}) = {days}d from {src_name}")
                        return df
                except Exception as e:
                    logger.debug(f"{src_name} try {attempt+1}: {e}")
                    time.sleep(1)

        logger.error("All data sources failed")
        return pd.DataFrame()

    def fetch_ohlcv_extended(s,symbol=None,timeframe=None,days=90):
        """داده طولانی با چند بار درخواست"""
        symbol=symbol or s.config.SYMBOL
        timeframe=timeframe or s.config.TIMEFRAME

        tfm={"1m":60000,"3m":180000,"5m":300000,"15m":900000,
             "30m":1800000,"1h":3600000,"4h":14400000,"1d":86400000}
        ms_per_candle=tfm.get(timeframe,900000)
        total_candles=(days*24*60*60*1000)//ms_per_candle

        all_data=[]
        batch_size=1000
        end_time=int(time.time()*1000)

        batches_needed=(total_candles//batch_size)+1
        logger.info(f"Fetching {total_candles} candles in {batches_needed} batches...")

        for batch in range(batches_needed):
            try:
                since=end_time-(batch_size*ms_per_candle)
                ohlcv=s.data_exchange.fetch_ohlcv(
                    symbol,timeframe,since=since,limit=batch_size)

                if not ohlcv:break
                all_data=ohlcv+all_data
                end_time=ohlcv[0][0]-1

                if batch>0 and batch%3==0:
                    logger.info(f"  Batch {batch+1}/{batches_needed} | {len(all_data)} candles")
                    time.sleep(0.5)

                if len(all_data)>=total_candles:break

            except Exception as e:
                logger.warning(f"Batch {batch} error: {e}")
                time.sleep(2)
                break

        if not all_data:
            return pd.DataFrame()

        df=pd.DataFrame(all_data,columns=["timestamp","open","high","low","close","volume"])
        df["timestamp"]=pd.to_datetime(df["timestamp"],unit="ms")
        df.set_index("timestamp",inplace=True)
        df=df.astype(float)
        df=df[~df.index.duplicated(keep='first')]
        df.sort_index(inplace=True)

        actual_days=(df.index[-1]-df.index[0]).days
        logger.info(f"Total: {len(df)} candles = {actual_days} days")
        return df

    def get_balance(s):
        try:
            bal=s.exchange.fetch_balance()
            for cur in ["USDT","USD","BUSD"]:
                if cur in bal:
                    free=float(bal[cur].get("free",0))
                    if free>0:return free
            return float(bal.get("total",{}).get("USDT",0))
        except Exception as e:
            logger.error(f"Balance: {e}")
            return 0.0

    def get_position(s,symbol=None):
        symbol=symbol or s.config.SYMBOL
        try:
            positions=s.exchange.fetch_positions([symbol])
            for pos in positions:
                if float(pos.get("contracts",0))>0:
                    return {"side":pos["side"],"size":float(pos["contracts"]),
                        "entry_price":float(pos["entryPrice"]),
                        "unrealized_pnl":float(pos.get("unrealizedPnl",0)),
                        "leverage":float(pos.get("leverage",1))}
            return None
        except Exception as e:
            logger.error(f"Position: {e}")
            return None

    def place_order(s,side,amount,order_type="market",price=None,
                    stop_loss=None,take_profit=None,symbol=None):
        symbol=symbol or s.config.SYMBOL
        try:
            if order_type=="market":
                order=s.exchange.create_order(symbol,"market",side,amount)
            elif order_type=="limit":
                order=s.exchange.create_order(symbol,"limit",side,amount,price)
            else:order=None

            if order:logger.info(f"Order: {side.upper()} {amount} {symbol}")

            if stop_loss and order:
                sl_side="sell" if side=="buy" else "buy"
                try:
                    s.exchange.create_order(symbol,"stop_market",sl_side,amount,
                        params={"stopPrice":stop_loss,"reduceOnly":True})
                except:
                    try:
                        s.exchange.create_order(symbol,"market",sl_side,amount,
                            params={"triggerPrice":stop_loss,"reduceOnly":True})
                    except:pass

            if take_profit and order:
                tp_side="sell" if side=="buy" else "buy"
                try:
                    s.exchange.create_order(symbol,"take_profit_market",tp_side,amount,
                        params={"stopPrice":take_profit,"reduceOnly":True})
                except:
                    try:
                        s.exchange.create_order(symbol,"market",tp_side,amount,
                            params={"triggerPrice":take_profit,"reduceOnly":True})
                    except:pass

            return order
        except Exception as e:
            logger.error(f"Order: {e}")
            return None

    def close_position(s,symbol=None):
        symbol=symbol or s.config.SYMBOL
        try:
            pos=s.get_position(symbol)
            if pos:
                cs="sell" if pos["side"]=="long" else "buy"
                s.exchange.create_order(symbol,"market",cs,pos["size"],
                    params={"reduceOnly":True})
                return True
            return False
        except:return False

    def cancel_all_orders(s,symbol=None):
        try:s.exchange.cancel_all_orders(symbol or s.config.SYMBOL);return True
        except:return False

    def get_ticker(s,symbol=None):
        symbol=symbol or s.config.SYMBOL
        try:
            t=s.exchange.fetch_ticker(symbol)
            return {"bid":float(t.get("bid",0)),"ask":float(t.get("ask",0)),
                "last":float(t.get("last",0)),"volume":float(t.get("quoteVolume",0))}
        except:return {}
