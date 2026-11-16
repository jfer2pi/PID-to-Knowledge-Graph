import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import pickle, collections, sys
for i in map(int, sys.argv[1:]):
    H=pickle.load(open(f'{WORK}/cache/H{i:02d}.pkl','rb'))
    tab={e['n1']:e['ta'] for e in H['table']}
    found=collections.defaultdict(collections.Counter)
    for a,v in H['dot_name'].items(): found[v['n1']][v['ta']]+=1
    miss=sorted(set(tab)-set(found)); extra=sorted(set(found)-set(tab))
    mism=[(n, dict(found[n]), tab[n]) for n in sorted(found) if n in tab and set(found[n])!={tab[n]}]
    q=H['qa']
    print(i, H['table_src'], 'table',len(tab),'found',len(found),'missing',miss,'extra',extra,'| dots',q['dots'],'unnamed',q['dots_unnamed'],'inferred',q['dots_named_inferred'],'from_table',q['dots_named_from_table'])
    if mism: print('   ta mismatch', mism)
