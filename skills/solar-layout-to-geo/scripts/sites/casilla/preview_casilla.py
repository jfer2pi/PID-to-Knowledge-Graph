import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pickle, numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.ops import unary_union
A=pickle.load(open(os.path.join(os.environ.get('CASILLA_WORK', '.'), 'assembled.pkl'),'rb')); F=A['feats']
import build_casilla as B
feats,rows,tot,notes,anchor=B.main()
F=feats
allb=np.array([g.bounds for g,_ in F['trackers']]+[g.bounds for g,_ in F['site']])
x0,y0,x1,y1=allb[:,0].min()-30,allb[:,1].min()-30,allb[:,2].max()+30,allb[:,3].max()+70
S=0.9; Wd,Hd=int((x1-x0)*S),int((y1-y0)*S)
im=Image.new('RGB',(Wd,Hd),'white'); d=ImageDraw.Draw(im,'RGBA')
f=lambda x,y:((x-x0)*S,(y1-y)*S)
cols=[(220,20,60),(30,144,255),(34,139,34),(255,140,0),(148,0,211),(0,128,128),(205,92,92),(70,130,180),(120,160,30),(255,20,147),(110,80,40),(0,170,170),(200,170,0),(90,90,200)]
for g,p in F['site']:
    for ln in g.geoms: d.line([f(*c) for c in ln.coords], fill=(90,90,90,255), width=1)
for g,p in F['roads']:
    d.line([f(*c) for c in g.coords], fill=(170,170,170,255), width=1)
for g,p in F['station_areas']:
    k=int(p['id'][-2:])-1
    for q in getattr(g,'geoms',[g]): d.polygon([f(*c) for c in q.exterior.coords], fill=cols[k]+(45,), outline=cols[k]+(255,))
for g,p in F['trackers']:
    k=int(p['station'][-2:])-1; b=g.bounds
    d.rectangle([f(b[0],b[3]),f(b[2],b[1])], fill=cols[k]+(200,))
fb=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',14)
for g,p in F['stations']:
    u,v=f(g.x,g.y); d.rectangle([u-4,v-4,u+4,v+4],fill=(0,0,0,255)); d.text((u+6,v-16),p['id'],fill=(0,0,0,255),font=fb)
ax,ay=anchor['anchor_frame_m']; u,v=f(ax,ay); d.ellipse([u-7,v-7,u+7,v+7],outline=(255,0,0,255),width=3); d.text((u+9,v+2),'printed coordinate (provisional anchor)',fill=(255,0,0,255),font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',12))
d.text((12,8),f"Casilla Solar PV: {tot['trackers']:,} trackers (2P, 84 modules), {tot['strings']:,} strings of 28 (derived), 14 CT; shaded = station areas",fill=(0,0,0,255),font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13))
u,v=20,Hd-25; d.line([u,v,u+200*S,v],fill=(0,0,0,255),width=3); d.text((u,v-16),'200 m',fill=(0,0,0,255))
d.polygon([(Wd-30,40),(Wd-38,62),(Wd-22,62)],fill=(0,0,0,255)); d.text((Wd-35,18),'N',fill=(0,0,0,255),font=fb)
im.convert('RGB').save(os.path.join(os.environ.get('CASILLA_OUT', 'out/casilla'), 'qa/preview.jpg'),quality=88)
