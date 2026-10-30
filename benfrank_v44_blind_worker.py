"""Isolated blind ML regression worker.

Input contract permits ONLY numeric training features and a candidate vector.
It NEVER receives player names, prop line, opponent, primary model output, or
an answer to imitate. This is process separation, not a hardened OS sandbox.
"""
import hashlib
import json
import math
import statistics
import sys

FEATURES=5
ALLOWED={"train","candidate","ridge"}
VERSION="BENFRANK_BLIND_RIDGE_1.0"

def solve(matrix, vector):
    n=len(vector)
    a=[list(map(float, matrix[i]))+[float(vector[i])] for i in range(n)]
    for k in range(n):
        pivot=max(range(k,n),key=lambda i:abs(a[i][k]))
        a[k],a[pivot]=a[pivot],a[k]
        if abs(a[k][k])<1e-12:
            raise ValueError("Singular normal equations")
        div=a[k][k]
        for j in range(k,n+1):
            a[k][j]/=div
        for i in range(n):
            if i==k:
                continue
            factor=a[i][k]
            for j in range(k,n+1):
                a[i][j]-=factor*a[k][j]
    return [a[i][-1] for i in range(n)]

def calculate(data):
    if not isinstance(data,dict) or set(data) != ALLOWED:
        raise ValueError("Blind worker payload MUST contain only train, candidate, ridge")
    train=data["train"]
    candidate=data["candidate"]
    ridge=data["ridge"]
    if not isinstance(train,list) or len(train)<20:
        raise ValueError("Need at least 20 chronologically eligible training rows")
    if not isinstance(ridge,(int,float)) or not 0.05<=ridge<=10:
        raise ValueError("Regularization must be 0.05..10")
    def check_vector(v):
        if not isinstance(v,list) or len(v)!=FEATURES:
            raise ValueError("Features must be five-element arrays")
        if not all(isinstance(x,(int,float)) and not isinstance(x,bool)
                   and math.isfinite(x) and abs(x)<100000 for x in v):
            raise ValueError("Non-finite or excessive feature")
        return [float(x) for x in v]
    xs=[]
    ys=[]
    for row in train:
        if not isinstance(row,dict) or set(row)!={"x","y"}:
            raise ValueError("Each training row must contain only x and y")
        xs.append(check_vector(row["x"]))
        y=row["y"]
        if not isinstance(y,(int,float)) or isinstance(y,bool) or not math.isfinite(y) or abs(y)>100000:
            raise ValueError("Training outcome not finite")
        ys.append(float(y))
    vector=check_vector(candidate)
    n=len(xs)
    means=[statistics.mean(x[j] for x in xs) for j in range(FEATURES)]
    scales=[max(statistics.pstdev(x[j] for x in xs),1e-6) for j in range(FEATURES)]
    center=statistics.mean(ys)
    xx=[[0.0]*FEATURES for _ in range(FEATURES)]
    xy=[0.0]*FEATURES
    for x,y in zip(xs,ys):
        z=[(x[j]-means[j])/scales[j] for j in range(FEATURES)]
        for i in range(FEATURES):
            xy[i]+=z[i]*(y-center)
            for j in range(FEATURES):
                xx[i][j]+=z[i]*z[j]
    for i in range(FEATURES):
        xx[i][i]+=ridge*n
    weights=solve(xx,xy)
    estimate=center+sum(weights[j]*(vector[j]-means[j])/scales[j] for j in range(FEATURES))
    digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    return {"status":"EXECUTED_PROCESS_SEPARATE_ML",
            "model":VERSION,"projection":round(estimate,4),
            "training_n":n,"input_sha256":digest,"line_received":False,
            "algorithm":"Player-specific ridge regression, standardized lagged historical features",
            "independence":"Separate Python process receiving only sanitized numerical features",
            "certification":"NOT_VALIDATED_OR_CALIBRATED"}

def main():
    try:
        data=json.load(sys.stdin)
        result=calculate(data)
        json.dump(result,sys.stdout)
    except (ValueError,TypeError,KeyError,OverflowError) as exc:
        json.dump({"status":"BLOCKED","error":str(exc)},sys.stdout)
        raise SystemExit(2)

if __name__=="__main__":
    main()
