import os
import fitz, pickle, numpy as np, re, collections, json
from scipy.spatial import cKDTree
d=fitz.open(os.environ.get("BUFALI_PDF", "bufali.pdf"))
R=pickle.load(open("extract.pkl","rb"))
def disp(pn,x,y):
    m=fitz.Matrix(*R[pn]['rotm']); p=fitz.Point(x,y)*m; return p.x,p.y
def centres_m(pn):
    C=R[pn]['main'][1]; out=[]
    for r in R[pn]['structs']:
        cx,cy=(r[0]+r[2])/2,(r[1]+r[3])/2
        X,Y=disp(pn,cx,cy); out.append((X*C,-Y*C))
    return np.array(out)
G=centres_m(238); tG=cKDTree(G)
reg={}
for pn in range(239,245):
    S=centres_m(pn)
    # translation vote at 1 m bins
    D=(G[None,:,:]-S[:,None,:]).reshape(-1,2)
    H=collections.Counter(map(tuple,np.round(D).astype(int)))
    (tx,ty),n=H.most_common(1)[0]
    t=np.array([tx,ty],float)
    for _ in range(3):
        dd,ii=tG.query(S+t); ok=dd<2.0
        t=t+np.median(G[ii[ok]]-(S[ok]+t),axis=0)
    dd,ii=tG.query(S+t); ok=dd<1.0
    reg[pn]=dict(t=t.tolist(),matched=int(ok.sum()),n=len(S),rms=float(np.sqrt(np.mean(dd[ok]**2))),votes=n)
    print(pn,reg[pn])
json.dump(reg,open("register.json","w"),indent=1)
