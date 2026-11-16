import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import SRC, WORK, RENDER, OUT
import pymupdf as fitz, glob, pickle, os, re
from _paths import SRC
def pdf(i): return glob.glob(f"{SRC}/*4.{i}_00.pdf")[0]
def load(i):
    c=f"{WORK}/cache/s{i:02d}.pkl"
    if os.path.exists(c): return pickle.load(open(c,"rb"))
    d=fitz.open(pdf(i)); p=d[0]
    dr=p.get_drawings()
    for g in dr:
        g.pop('items_raw',None)
    words=p.get_text("words")
    o=" ".join(d.xref_object(p.xref).split())
    vps=re.findall(r"/BBox \[ ([\d. -]+) \]",o)
    meas=[]
    for ch in o.split("/Type /Viewport")[:-1]:
        cc=re.findall(r"/X \[ << /C ([\d.]+)",ch); meas.append(float(cc[-1]) if cc else None)
    # bbox follows or precedes? collect each viewport dict text
    vpd=[]
    for m in re.finditer(r"<< (?:(?!<< /Measure).)*?/Type /Viewport.*?>>|<< /BBox.*?/Type /Viewport",o): pass
    out=dict(dr=dr,words=words,rot=p.rotation,rect=tuple(p.rect),mb=tuple(p.mediabox),
             derot=tuple(p.rotation_matrix), obj=o[o.find('/VP'):o.find('/VP')+3000])
    pickle.dump(out,open(c,"wb")); return out

def viewports(s):
    import pymupdf as fitz
    o=s['obj']; out=[]
    for ch in re.findall(r"<<((?:(?!/Type /Viewport).)*?/Type /Viewport(?:(?!<<\s*/(?:Measure|BBox)).)*?)>>",o):
        pass
    # simpler: split dicts on '/Type /Viewport'
    parts=o.split('/Type /Viewport')
    for k in range(len(parts)-1):
        seg=parts[k].split('>> <<')[-1] + parts[k+1].split('>> <<')[0]
        bb=re.findall(r"/BBox \[ ([\d. -]+) \]",seg); c=re.findall(r"/X \[ << /C ([\d.]+)",seg)
        if bb and c:
            x0,y0,x1,y1=map(float,bb[0].split())
            M=fitz.Matrix(*s['derot']); H=s['mb'][3]
            # PDF user space (y up) -> unrotated top-left -> rotated
            r=fitz.Rect(min(x0,x1),H-max(y0,y1),max(x0,x1),H-min(y0,y1))*M
            out.append(dict(C=float(c[0]),clip=r))
    return out

def disp(s):
    """drawings with displayed-page rects/items (rotation applied)"""
    import pymupdf as fitz
    M=fitz.Matrix(*s['derot'])
    for g in s['dr']:
        if 'D' in g: continue
        g['D']=g['rect']*M
        its=[]
        for it in g['items']:
            if it[0]=='l': its.append(('l',it[1]*M,it[2]*M))
            elif it[0]=='re': its.append(('re',it[1]*M))
            elif it[0]=='qu': its.append(('qu',it[1]*M))
            elif it[0]=='c': its.append(('c',it[1]*M,it[2]*M,it[3]*M,it[4]*M))
        g['Di']=its
    return s
