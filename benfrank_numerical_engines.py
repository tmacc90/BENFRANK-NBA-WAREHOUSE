"""Deterministic BENFRANK four-engine historical audit. No claim of calibration without frozen outcomes."""
import hashlib,random,statistics,math
from benfrank_logs import MARKETS,analyze
def _values(rows,market):
 return [sum(float(r[k]) for k in MARKETS[market]) for r in rows]
def _rate(values,line):
 n=len(values)
 return {'games':n,'over':sum(v>line for v in values),'under':sum(v<line for v in values),'push':sum(v==line for v in values),'over_rate':sum(v>line for v in values)/n if n else None}
def evaluate(rows,market,line,opponent=None,cutoff=None,draws=25000):
 if market not in MARKETS:raise ValueError('UNSUPPORTED_MARKET')
 if not math.isfinite(float(line)):raise ValueError('INVALID_LINE')
 if draws!=25000:raise ValueError('REQUIRED_25000_DRAWS')
 eligible=sorted((r for r in rows if not cutoff or r['date']<cutoff),key=lambda r:r['date'])
 if not eligible:raise ValueError('NO_PREGAME_GAME_LOGS')
 vals=_values(eligible,market)
 seed=int.from_bytes(hashlib.sha256(repr((market,line,[(r.get('date'),v) for r,v in zip(eligible,vals)])).encode()).digest()[:8],'big')
 rng=random.Random(seed)
 # Block-bootstrap the most recent available 20 observations. Not a calibrated predictive distribution.
 sample=vals[-20:]
 sims=[sample[rng.randrange(len(sample))] for _ in range(draws)]
 over=sum(x>line for x in sims);under=sum(x<line for x in sims);push=draws-over-under
 # Independent line-blind baseline: hold out latest 20%, estimate distribution from earlier observations only.
 split=max(1,int(len(vals)*0.8))
 blind_train=vals[:split] if len(vals)>1 else vals
 blind_center=statistics.median(blind_train)
 blind_spread=statistics.pstdev(blind_train) if len(blind_train)>1 else None
 blind_side='OVER' if blind_center>line else 'UNDER'
 primary_side='OVER' if over>under else 'UNDER'
 return {'exact_line':analyze(eligible,market,line,opponent),'sensitivity':{str(round(line+d,2)):_rate(vals,line+d) for d in (-1,-0.5,0,0.5,1)},'simulation':{'draws':draws,'seed':seed,'method':'EMPIRICAL_BOOTSTRAP_L20','over':over,'under':under,'push':push,'over_fraction':over/draws,'under_fraction':under/draws,'calibrated':False},'blind_baseline':{'method':'LINE_BLIND_HISTORICAL_MEDIAN','train_games':len(blind_train),'median':blind_center,'stddev':blind_spread,'side_after_line_reveal':blind_side,'independent_ai':False},'decision':{'side':primary_side,'blind_agrees':primary_side==blind_side,'ticket_qualified':False},'calibration':{'status':'UNAVAILABLE','reason':'NEEDS_FROZEN_PREGAME_FORECASTS_AND_SETTLED_OUTCOMES'},'limitations':['Bootstrap is not a calibrated cover probability','Blind historical baseline is not an independent AI model']}
