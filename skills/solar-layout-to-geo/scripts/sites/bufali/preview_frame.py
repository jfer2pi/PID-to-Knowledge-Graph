import json, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from shapely.geometry import shape
import random, sys
O=sys.argv[1]
fig,ax=plt.subplots(figsize=(16,11),dpi=110)
def load(n):
    try: return json.load(open(f"{O}/gis/{n}.geojson"))["features"]
    except FileNotFoundError: return []
for f in load("fence"):
    g=shape(f["geometry"])
    for l in getattr(g,"geoms",[g]): ax.plot(*l.xy,color="c",lw=0.5)
random.seed(1)
for f in load("combiner_areas"):
    g=shape(f["geometry"]); c=(random.random(),random.random(),random.random())
    for pg in getattr(g,"geoms",[g]): ax.fill(*pg.exterior.xy,color=c,alpha=0.35,lw=0)
for f in load("inverter_areas"):
    g=shape(f["geometry"])
    for pg in getattr(g,"geoms",[g]): ax.plot(*pg.exterior.xy,color="k",lw=1.2)
for f in load("strings"):
    g=shape(f["geometry"]); ax.plot(*g.exterior.xy,color="0.3",lw=0.3)
for f in load("unassigned_structures"):
    g=shape(f["geometry"]); ax.fill(*g.exterior.xy,color="r")
for f in load("combiners"):
    x,y=f["geometry"]["coordinates"]; ax.plot(x,y,"bs",ms=3); ax.text(x,y,f["properties"]["id"][3:],fontsize=5,color="b")
for f in load("stations"):
    x,y=f["geometry"]["coordinates"]; ax.plot(x,y,"r^",ms=8); ax.text(x,y,f["properties"]["id"],fontsize=8,color="r")
for f in load("inverter_areas"):
    g=shape(f["geometry"]); c=g.representative_point(); ax.text(c.x,c.y,f["properties"].get("id",""),fontsize=9,weight="bold")
ax.set_aspect(1/0.79); ax.set_title(O.split("/")[-1]); plt.tight_layout(); plt.savefig(f"{O}/qa/preview.png")
