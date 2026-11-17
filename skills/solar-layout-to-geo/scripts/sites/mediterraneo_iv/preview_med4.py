import json, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from shapely.geometry import shape
import os
O=os.environ.get("MED4_OUT", "out/mediterraneo_iv")
L=lambda n: json.load(open(f"{O}/gis/{n}.geojson"))["features"]
cols=dict(zip(["CT4.1","CT4.2","CT4.3","CT4.4","CT4.5","CT4.6","CT4.7","CT4.8"],["tab:orange","tab:blue","gold","purple","deepskyblue","magenta","green","crimson"]))
fig,ax=plt.subplots(figsize=(15,15),dpi=100)
for f in L("structures"):
    g=shape(f["geometry"]); p=f["properties"]
    ax.fill(*g.exterior.xy,color=cols[p["station"]],alpha=0.35 if p["derived"] else 0.8,lw=0)
for f in L("inverter_areas"):
    g=shape(f["geometry"])
    for pg in getattr(g,"geoms",[g]): ax.plot(*pg.exterior.xy,color="k",lw=0.6)
for f in L("stations"):
    x,y=f["geometry"]["coordinates"]; ax.plot(x,y,"k^",ms=9); ax.text(x,y,f["properties"]["id"],fontsize=11,weight="bold")
for f in L("inverters"):
    x,y=f["geometry"]["coordinates"]; ax.text(x,y,f["properties"]["id"][-2:],fontsize=6)
ax.set_aspect(1/0.79); ax.set_title("Mediterráneo IV: structures by CT (pale = CT derived), CT4.6 inverter groups"); plt.tight_layout(); plt.savefig(f"{O}/qa/preview.png")
