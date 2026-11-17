import os
"""Bufali-Palomar: extract structures, SBC colour groups, labels per sheet (PyMuPDF, unrotated page coords)."""
import fitz, pickle, re, sys, json, collections
import numpy as np
PDF=os.environ.get("BUFALI_PDF", "bufali.pdf")
OUT="."
d=fitz.open(PDF)
def vps(page):
    vp=d.xref_get_key(page.xref,"VP")[1]
    return [(fitz.Rect(*map(float,m.group(1).split())),float(m.group(2))) for m in re.finditer(r'/BBox\[([^\]]+)\][^>]*?/Measure.*?/X\[<</C ([\d.]+)',vp)]
res={}
for pn in [238]+list(range(239,245)):
    p=d[pn-1]
    V=[v for v in vps(p) if v[1] not in (.3528,.35279,.3528)]
    main=max(V,key=lambda v:v[0].get_area())
    dr=p.get_drawings()
    st=[x['rect'] for x in dr if x.get('layer')=='ND_MESAS_ESTRUCTURA'
        and max(x['rect'].width,x['rect'].height)>0.8*17.4/main[1] and max(x['rect'].width,x['rect'].height)<1.25*17.4/main[1]
        and min(x['rect'].width,x['rect'].height)>0.6*4.4/main[1]]
    # dedupe
    seen=set(); S=[]
    for r in st:
        k=(round(r.x0,0),round(r.y0,0))
        if k in seen: continue
        seen.add(k); S.append(tuple(r))
    caja={}
    for x in dr:
        m=re.match(r'ND_CAJA_AGRUPACION_(\d+)$',x.get('layer') or '')
        if m and x.get('color'): caja[int(m.group(1))]=tuple(x['color'])
    words=[]
    for b in p.get_text("dict")["blocks"]:
        for l in b.get("lines",[]):
            t="".join(s["text"] for s in l["spans"])
            if re.search(r'SBC|CIT|CEM|INVERSOR',t): words.append((t,tuple(l["bbox"])))
    est=[tuple(x['rect']) for x in dr if x.get('layer') in('ND_ESTACION SOLAR','ND_CEM','ND_C.instrumentación') and x['rect'] in main[0]]
    res[pn]=dict(main=(tuple(main[0]),main[1]),structs=S,caja=caja,words=words,
                 rot=p.rotation,rotm=tuple(p.rotation_matrix),
                 est=[(x.get('layer'),tuple(x['rect'])) for x in dr if x.get('layer') in('ND_ESTACION SOLAR','ND_CEM') and x['rect'] in main[0]])
    print(pn,"C",main[1],"structs",len(S),"caja",sorted(caja),"labels",[w[0] for w in words if 'SBC' in w[0]][:12])
pickle.dump(res,open(f"{OUT}/extract.pkl","wb"))
