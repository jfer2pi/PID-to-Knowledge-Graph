import fitz, pickle, numpy as np, re, collections, json
from scipy.optimize import linear_sum_assignment
from scipy.sparse.csgraph import connected_components
from scipy.sparse import csr_matrix
R=pickle.load(open("extract.pkl","rb")); K=pickle.load(open("colours2.pkl","rb"))
out={}
for pn in range(239,245):
    m=fitz.Matrix(*R[pn]['rotm']); C=R[pn]['main'][1]
    cols=K[pn]['cols']
    cent=[]
    for r in R[pn]['structs']:
        c=fitz.Point((r[0]+r[2])/2,(r[1]+r[3])/2)*m; cent.append((c.x*C,c.y*C))
    cent=np.array(cent); n=len(cent)
    def same(a,b): return a is not None and b is not None and np.linalg.norm(np.array(a)-np.array(b))<20
    rows=[];colsx=[]
    for i in range(n):
        for j in range(i+1,n):
            dx,dy=abs(cent[i,0]-cent[j,0]),abs(cent[i,1]-cent[j,1])
            if dx<19.5 and dy<9.5 and same(cols[i],cols[j]): rows+= [i,j]; colsx+=[j,i]
    A=csr_matrix((np.ones(len(rows)),(rows,colsx)),shape=(n,n))
    k,lab=connected_components(A,directed=False)
    comps=[np.where(lab==c)[0] for c in range(k)]
    comps=[cp for cp in comps if len(cp)>=3 and cols[cp[0]] is not None and not (cols[cp[0]][2]>200 and cols[cp[0]][0]<60)]
    labels=[]
    for t,bb in R[pn]['words']:
        mm=re.match(r'\s*(\d)\.(\d)\.(\d+)\s*STRINGS-SBC(\d+)',t)
        if mm:
            P=fitz.Point((bb[0]+bb[2])/2,(bb[1]+bb[3])/2)*m
            labels.append(dict(area=int(mm[1]),inv=int(mm[2]),n=int(mm[3]),sbc=int(mm[4]),xy=(P.x*C,P.y*C)))
    Cm=np.array([[np.min(np.linalg.norm(cent[cp]-np.array(l['xy']),axis=1))+ 20*abs(len(cp)-l['n']) for l in labels] for cp in comps])
    ri,ci=linear_sum_assignment(Cm)
    assign={}
    print(pn,"components",sorted(len(c) for c in comps))
    for a,b in zip(ri,ci):
        l=labels[b]; cp=comps[a]
        dd=np.min(np.linalg.norm(cent[cp]-np.array(l['xy']),axis=1))
        print("   comp n",len(cp),"col",cols[cp[0]],"-> SBC%02d"%l['sbc'],"label n",l['n'],"dist %.1f m"%dd,"OK" if len(cp)==l['n'] else "MISMATCH")
        for i in cp: assign[int(i)]=(l['area'],l['inv'],l['sbc'],l['n'])
    used=set(ri)
    for a,cp in enumerate(comps):
        if a in used: continue
        mates=[b for b in ri if np.linalg.norm(np.array(cols[comps[b][0]])-np.array(cols[cp[0]]))<20]
        if len(mates)==1:
            tgt=assign[int(comps[mates[0]][0])]
            for i in cp: assign[int(i)]=tgt
            print("   merged leftover comp n",len(cp),"into SBC%02d"%tgt[2])
        else: print("   UNASSIGNED comp n",len(cp),cols[cp[0]],"mates",len(mates))
    cnt=collections.Counter(v[2] for v in assign.values())
    bad={s:(c,[l['n'] for l in labels if l['sbc']==s][0]) for s,c in cnt.items() if c!=[l['n'] for l in labels if l['sbc']==s][0]}
    print("   counts vs labels mismatches:",bad, "total",sum(cnt.values()))
    out[pn]=assign
pickle.dump(out,open("groups.pkl","wb"))
