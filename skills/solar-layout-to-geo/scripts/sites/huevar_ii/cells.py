import os, numpy as np, collections
import pymupdf as fitz
from PIL import Image, ImageDraw
from scipy import ndimage
"""Rasterise the dashed tracker-group outlines and block outlines of Huévar II p. 199 into cells (cells.npy)."""
dr=fitz.open(os.environ.get("HUEVAR2_PDF", "huevar2.pdf"))[198].get_drawings()
Z=2.0; W,H=int(2384*Z),int(1684*Z)
im=Image.new("L",(W,H),0); g=ImageDraw.Draw(im)
nd=0;no=0
for x in dr:
    r=x['rect']; f=tuple(round(v,3) for v in (x.get('fill') or ()))
    if x['type'] in('f','fs') and f==(0,0,0) and len(x['items'])<=6 and 0.6<min(r.width,r.height)<0.95 and 2.6<max(r.width,r.height)<3.6:
        g.rectangle([r.x0*Z-1,r.y0*Z-1,r.x1*Z+1,r.y1*Z+1],fill=255); nd+=1
    elif x['type'] in('f','fs') and f and max(f)-min(f)>0.3 and max(r.width,r.height)>150:
        pts=[]
        for it in x['items']:
            if it[0]=='l': pts+= [(it[1].x*Z,it[1].y*Z),(it[2].x*Z,it[2].y*Z)]
        for i in range(0,len(pts)-1,2): g.line([pts[i],pts[i+1]],fill=255,width=3)
        no+=1
M=np.array(im)>0
M=ndimage.binary_dilation(M,iterations=2)
lab,n=ndimage.label(~M)
print("dashes",nd,"outlines",no,"cells",n)
np.save("cells.npy",lab.astype(np.int32))
Image.fromarray((M*255).astype(np.uint8)).resize((W//4,H//4)).save("cellmask.png")
