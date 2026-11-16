"""Where the route D scripts read and write. Override with environment variables."""
import os

SRC = os.environ.get("ROUTE_D_SRC", os.path.abspath("src"))          # the sheet PDFs
WORK = os.environ.get("ROUTE_D_WORK", os.path.abspath("work"))       # caches (cache/*.pkl, *.json)
RENDER = os.environ.get("ROUTE_D_RENDER", os.path.abspath("render"))  # debug images
OUT = os.environ.get("ROUTE_D_OUT", os.path.abspath("out/site"))     # deliverable folder
os.makedirs(os.path.join(WORK, "cache"), exist_ok=True)
os.makedirs(RENDER, exist_ok=True)
