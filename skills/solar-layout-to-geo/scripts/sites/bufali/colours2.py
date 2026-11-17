import os
import fitz, pickle, numpy as np, re, collections, json
from scipy.optimize import linear_sum_assignment
d=fitz.open(os.environ.get("BUFALI_PDF", "bufali.pdf"))
R=pickle.load(open("extract.pkl","rb"))
Z=3
out={}
for pn in range(239,245):
    p=d[pn-1]; m=fitz.Matrix(*R[pn]['rotm'])
    pix=p.get_pixmap(matrix=fitz.Matrix(Z,Z),alpha=False)
    A=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,3).astype(int)
    cols=[];cent=[]
    for r in R[pn]['structs']:
        x0,y0,x1,y1=r; S=[]
        for fu in np.linspace(0.08,0.92,12):
            for fv in (0.15,0.3,0.7,0.85):
                P=fitz.Point(x0+fv*(x1-x0),y0+fu*(y1-y0))*m
                S.append(A[int(P.y*Z),int(P.x*Z)])
        S=np.array(S)
        keep=S[(S.sum(1)>120)&(S.sum(1)<735)&~((S[:,2]>150)&(S[:,0]<120)&(S[:,1]<120))]
        if len(keep)<6: cols.append(None)
        else:
            q=collections.Counter(map(tuple,(keep//6*6))).most_common(1)[0]
            cols.append(q[0] if q[1]>=len(keep)*0.3 else tuple(np.median(keep,0).astype(int)//6*6))
        c=fitz.Point((x0+x1)/2,(y0+y1)/2)*m; cent.append((c.x,c.y))
    cent=np.array(cent)
    cc=collections.Counter(c for c in cols if c is not None)
    # merge near colours
    clusters=[]
    for c,n in cc.most_common():
        for cl in clusters:
            if np.linalg.norm(np.array(c)-np.array(cl['c']))<20: cl['m'].append(c); cl['n']+=n; break
        else: clusters.append(dict(c=c,m=[c],n=n))
    labels=[]
    for t,bb in R[pn]['words']:
        mm=re.match(r'\s*(\d)\.(\d)\.(\d+)\s*STRINGS-SBC(\d+)',t)
        if mm:
            P=fitz.Point((bb[0]+bb[2])/2,(bb[1]+bb[3])/2)*m
            labels.append(dict(area=int(mm[1]),inv=int(mm[2]),n=int(mm[3]),sbc=int(mm[4]),xy=(P.x,P.y)))
    big=[cl for cl in clusters if cl['n']>=4]
    print(pn,"clusters",[(cl['c'],cl['n']) for cl in big],"small",[(cl['c'],cl['n']) for cl in clusters if cl['n']<4],"labels",[(l['sbc'],l['n']) for l in labels])
    # cost: label to nearest structure of cluster
    memb=[np.array([i for i,c in enumerate(cols) if c is not None and c in cl['m']]) for cl in big]
    Cm=np.array([[np.min(np.linalg.norm(cent[mb]-np.array(l['xy']),axis=1)) for l in labels] for mb in memb])
    ri,ci=linear_sum_assignment(Cm)
    assign={}
    for a,b in zip(ri,ci):
        l=labels[b]; print("   cluster",big[a]['c'],"n",len(memb[a]),"-> SBC%02d"%l['sbc'],"label n",l['n'],"dist %.0f"%Cm[a,b], "OK" if len(memb[a])==l['n'] else "MISMATCH")
        for i in memb[a]: assign[i]=l
    out[pn]=dict(assign={i:(l['area'],l['inv'],l['sbc'],l['n']) for i,l in assign.items()},cols=cols)
pickle.dump(out,open("colours2.pkl","wb"))
