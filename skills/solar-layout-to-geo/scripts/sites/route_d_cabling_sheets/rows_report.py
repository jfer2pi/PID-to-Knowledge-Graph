import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import pickle, collections, sys, numpy as np
for i in map(int, sys.argv[1:]):
    H=pickle.load(open(f'{WORK}/cache/H{i:02d}.pkl','rb'))
    g=collections.defaultdict(list)
    for a,v in H['dot_name'].items():
        g[(H['lab_row'].get(H['rid'][a]), v['n1'], v['ta'])].append(H['D'][a,0])
    out=collections.defaultdict(list)
    for (row,n1,ta),xs in sorted(g.items(), key=lambda kv:(kv[0][0] or '', np.mean(kv[1]))):
        out[row].append(f"N1-{n1:02d}>TA{ta:02d}x{len(xs)}")
    print(i, ' | '.join(f"{r[-2:] if r else '?'}: {' '.join(v)}" for r,v in out.items()))
