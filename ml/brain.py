import os,json,joblib,numpy as np,pandas as pd
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier,GradientBoostingClassifier
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import StandardScaler
from config import Config
from utils.logger import setup_logger
logger = setup_logger("ML")

MD="data"; MF=os.path.join(MD,"ml_model.pkl"); SF=os.path.join(MD,"ml_scaler.pkl"); DF=os.path.join(MD,"trade_data.json"); STF=os.path.join(MD,"ml_stats.json")
FC=["rsi","atr_pct","vol_ratio","pct_change_1","pct_change_5","macd","trend","htf_trend","structure_strength","ob_count","sweep_count","fvg_count","zone","kill_zone","bull_score","bear_score","ob_distance","spread_score"]

class MLBrain:
    def __init__(self):
        self.config=Config(); self.model=None; self.scaler=None; self.trade_data=[]; self.last_train=None; self.accuracy=0; self.total_pred=0; self.correct_pred=0
        os.makedirs(MD,exist_ok=True); self._load()

    def _load(self):
        try:
            if os.path.exists(MF): self.model=joblib.load(MF); self.scaler=joblib.load(SF); logger.info("ML model loaded")
        except: pass
        try:
            if os.path.exists(DF):
                with open(DF) as f: self.trade_data=json.load(f)
        except: pass
        try:
            if os.path.exists(STF):
                with open(STF) as f: s=json.load(f); self.accuracy=s.get("accuracy",0); self.total_pred=s.get("total_predictions",0); self.correct_pred=s.get("correct_predictions",0); self.last_train=s.get("last_train_time")
        except: pass

    def _save(self):
        try:
            if self.model: joblib.dump(self.model,MF); joblib.dump(self.scaler,SF)
        except: pass
        try:
            with open(DF,"w") as f: json.dump(self.trade_data[-2000:],f,default=str)
        except: pass
        try:
            with open(STF,"w") as f: json.dump({"accuracy":self.accuracy,"total_predictions":self.total_pred,"correct_predictions":self.correct_pred,"last_train_time":str(self.last_train),"data_count":len(self.trade_data)},f)
        except: pass

    def record_analysis(self,features,signal,price):
        self.trade_data.append({"timestamp":str(datetime.utcnow()),"features":features,"signal":signal,"entry_price":price,"outcome":None})
        self._save()

    def record_outcome(self,entry,exit_price,direction):
        for r in reversed(self.trade_data):
            if r["outcome"] is None and abs(r["entry_price"]-entry)<entry*0.001:
                pnl=(exit_price-entry)/entry*100 if direction=="long" else (entry-exit_price)/entry*100
                r["outcome"]=1 if pnl>0 else 0; r["pnl_pct"]=round(pnl,4)
                self.total_pred+=1
                if pnl>0: self.correct_pred+=1
                self._save(); break
        self._check_retrain()

    def predict(self,features):
        r={"ml_confidence":0.5,"ml_signal":"neutral","should_trade":True,"model_ready":False}
        if not self.model or not self.scaler: return r
        try:
            X=self._to_arr(features)
            if X is None: return r
            Xs=self.scaler.transform(X); pred=self.model.predict(Xs)[0]; prob=self.model.predict_proba(Xs)[0]
            conf=max(prob); r["model_ready"]=True; r["ml_confidence"]=round(conf,4)
            r["ml_signal"]="profitable" if pred==1 else "unprofitable"
            r["should_trade"]=conf>=self.config.ML_CONFIDENCE_THRESHOLD if pred==1 else False
        except Exception as e: logger.error(f"Predict: {e}")
        return r

    def train(self,force=False):
        labeled=[d for d in self.trade_data if d.get("outcome") is not None]
        if len(labeled)<20: return False
        if len(labeled)<self.config.ML_MIN_SAMPLES and not force: return False
        logger.info(f"Training with {len(labeled)} samples...")
        try:
            Xl=[]; yl=[]
            for r in labeled:
                a=self._to_arr(r["features"])
                if a is not None: Xl.append(a[0]); yl.append(r["outcome"])
            if len(Xl)<20: return False
            X=np.array(Xl); y=np.array(yl)
            self.scaler=StandardScaler(); Xs=self.scaler.fit_transform(X)
            best=None; bs=0
            for name,m in [("RF",RandomForestClassifier(n_estimators=100,max_depth=10,random_state=42,class_weight="balanced")),("GB",GradientBoostingClassifier(n_estimators=100,max_depth=5,random_state=42))]:
                try:
                    cv=min(5,len(Xs)//2)
                    if cv>=2: sc=cross_val_score(m,Xs,y,cv=cv).mean()
                    else: m.fit(Xs,y); sc=m.score(Xs,y)
                    if sc>bs: bs=sc; best=m
                except: continue
            if best: best.fit(Xs,y); self.model=best; self.accuracy=bs; self.last_train=datetime.utcnow(); self._save(); logger.info(f"Trained: {bs:.1%}")
            return True
        except Exception as e: logger.error(f"Train: {e}"); return False

    def _check_retrain(self):
        labeled=[d for d in self.trade_data if d.get("outcome") is not None]
        if len(labeled)<self.config.ML_MIN_SAMPLES: return
        if self.last_train:
            try:
                h=(datetime.utcnow()-datetime.fromisoformat(str(self.last_train))).total_seconds()/3600
                if h>=self.config.ML_RETRAIN_HOURS: self.train()
            except: self.train()
        else: self.train()

    def _to_arr(self,f):
        try: return np.array([[float(f.get(c,0) or 0) for c in FC]])
        except: return None

    def generate_synthetic_data(self,df,strategy,n=200):
        logger.info(f"Generating {n} synthetic samples...")
        if len(df)<100: return 0
        cnt=0; step=max(1,(len(df)-60)//n)
        for i in range(50,len(df)-10,step):
            if cnt>=n: break
            try:
                sub=df.iloc[:i].copy()
                if len(sub)<50: continue
                a=strategy.analyze(sub)
                if a["signal"]=="NO_SIGNAL": continue
                entry=sub["close"].iloc[-1]; future=df.iloc[i:i+10]
                if len(future)<5: continue
                if a["direction"]=="long": pp=(future["high"].max()-entry)/entry; pl=(entry-future["low"].min())/entry
                else: pp=(entry-future["low"].min())/entry; pl=(future["high"].max()-entry)/entry
                outcome=1 if pp>pl and pp>0.005 else 0
                self.trade_data.append({"timestamp":str(sub.index[-1]),"features":a["features"],"signal":a["signal"],"entry_price":entry,"outcome":outcome,"pnl_pct":round((pp if outcome else -pl)*100,4),"synthetic":True})
                cnt+=1
            except: continue
        self._save()
        if cnt>=20: self.train(force=True)
        return cnt

    def get_stats(self):
        labeled=[d for d in self.trade_data if d.get("outcome") is not None]
        wins=[d for d in labeled if d["outcome"]==1]
        return {"model_ready":self.model is not None,"model_accuracy":round(self.accuracy*100,1),"total_records":len(self.trade_data),"labeled_records":len(labeled),"win_rate_actual":round(len(wins)/max(len(labeled),1)*100,1),"total_predictions":self.total_pred,"correct_predictions":self.correct_pred,"prediction_accuracy":round(self.correct_pred/max(self.total_pred,1)*100,1),"last_train":str(self.last_train) if self.last_train else "Never"}
