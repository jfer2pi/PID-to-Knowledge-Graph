import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import sys, pickle, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pymupdf as fitz
from load import pdf
from PIL import Image, ImageDraw, ImageFont
def debug(i, dpi=150, out=None):
    H=pickle.load(open(f'{WORK}/cache/H{i:02d}.pkl','rb'))
    E=H['E']; clip=fitz.Rect(E.get('clip') or (20,20,950,830))
    p=fitz.open(pdf(i))[0]; pix=p.get_pixmap(dpi=dpi,clip=clip)
    im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
    im=Image.blend(im,Image.new('RGB',im.size,'white'),0.6); d=ImageDraw.Draw(im)
    k=dpi/72; f=lambda x,y:((x-clip.x0)*k,(y-clip.y0)*k)
    try: font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',int(11*dpi/150))
    except: font=None
    rng=np.random.default_rng(5)
    cc={j:tuple(int(v) for v in rng.integers(0,190,3)) for j in H['info']}
    for a,(t,src) in H['tab'].items():
        j=H['dot_comp'].get(a); c=cc.get(j,(0,0,0))
        d.rectangle([f(t[0],t[1]),f(t[2],t[3])],outline=c,width=2 if src=='read' else 1)
        x,y=H['D'][a]; u,v=f(x,y); d.ellipse([u-3,v-3,u+3,v+3],fill=c)
        d.line([f(x,y),f((t[0]+t[2])/2,(t[1]+t[3])/2)],fill=c)
    import collections
    grp=collections.defaultdict(list)
    for a,nm in H['dot_name'].items(): grp[(nm['n1'],nm['ta'],H['rid'][a])].append(a)
    rng2=np.random.default_rng(9)
    for (n1,ta,r),dots in grp.items():
        c=tuple(int(v) for v in rng2.integers(0,180,3))
        xs=H['D'][dots,0]; ys=H['D'][dots,1]
        for a in dots:
            t=H['tab'][a][0]; d.rectangle([f(t[0],t[1]+1),f(t[2],t[3]-1)],fill=None,outline=c,width=3)
        u,w=f(xs.mean(),ys.mean()-7)
        inf=any(H['dot_name'][a].get('inferred') or H['dot_name'][a].get('from_table') for a in dots)
        d.text((u,w),f"N1-{n1:02d}>TA{ta:02d}"+('*' if inf else ''),fill=c,font=font)
    for L in H['leaders']:
        u,w=f(*L['tip']); d.ellipse([u-4,w-4,u+4,w+4],outline=(0,0,0) if L.get('parsed') else (255,0,0),width=2)
    for q,t in enumerate(E['ta_raw']):
        d.rectangle([f(t[0],t[1]),f(t[2],t[3])],outline=(255,120,0),width=3)
        nm=H['board_name'].get(q); u,w=f(t[2]+1,t[1])
        d.text((u,w),f"TA{nm:02d}" if nm else 'TA?',fill=(255,80,0),font=font)
    im.save(out or f'{RENDER}/h{i:02d}.png')
if __name__=='__main__':
    for i in map(int,sys.argv[1:]): debug(i)
