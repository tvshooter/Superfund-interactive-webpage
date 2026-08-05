"""Build the Houston DMA brownfield + Superfund dataset.

Pulls straight from EPA's public hosted feature services and clips the results
to the 20 counties of the Nielsen Houston television market using Census
TIGERweb county boundaries.

Outputs (all written into web/data/):
  counties.geojson  county outlines for the DMA
  superfund.geojson NPL Superfund sites
  brownfields.geojson  EPA Brownfields (ACRES) properties
  meta.json         counts, field lists, source URLs, build timestamp

Also writes data-report.txt at the repo root: a human-readable dump of the
field names and a couple of sample records, so the popup/table code can be
written against the real schema.

Runs on a GitHub Actions runner (open outbound internet).
"""

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "web", "data")

TIMEOUT = 120
UA = {"User-Agent": "houston-dma-site-map/1.0 (public data mapping)"}

# The 20 counties Nielsen assigns to the Houston, TX DMA.
DMA_COUNTIES = [
    "Austin", "Brazoria", "Calhoun", "Chambers", "Colorado", "Fort Bend",
    "Galveston", "Grimes", "Harris", "Jackson", "Liberty", "Matagorda",
    "Montgomery", "Polk", "San Jacinto", "Trinity", "Walker", "Waller",
    "Washington", "Wharton",
]

# Bounding box that comfortably contains all 20 counties (lon/lat).
BBOX = (-97.4, 27.9, -94.0, 31.5)

EPA_AGOL = "https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services"
SUPERFUND_SERVICE = (
    f"{EPA_AGOL}/Superfund_National_Priorities_List_%28NPL%29_Sites_with_Status_Information"
    "/FeatureServer"
)
BROWNFIELDS_SERVICE = f"{EPA_AGOL}/Brownfields/FeatureServer"
TIGERWEB_COUNTIES = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
    "State_County/MapServer/1"
)

CTX = ssl.create_default_context()


def fetch(url, params=None, retries=4):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001 - network flakiness, retry
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET failed after {retries} tries: {url}\n  {last!r}")


def inventory(service_url):
    """List every layer in a feature service with its geometry type and count."""
    svc = fetch(service_url, {"f": "json"})
    layers = (svc.get("layers") or []) + (svc.get("tables") or [])
    if not layers:
        raise RuntimeError(f"no layers in {service_url}: {json.dumps(svc)[:400]}")
    out = []
    for lyr in layers:
        lid = lyr["id"]
        try:
            meta = fetch(f"{service_url}/{lid}", {"f": "json"})
        except Exception as exc:  # noqa: BLE001
            print(f"    layer {lid}: metadata failed {exc!r}")
            continue
        out.append({
            "id": lid,
            "name": meta.get("name"),
            "geometryType": meta.get("geometryType"),
            "fields": [(f["name"], f.get("type"), f.get("alias"))
                       for f in meta.get("fields", [])],
        })
        print(f"    layer {lid}: {meta.get('name')!r} "
              f"geom={meta.get('geometryType')} fields={len(meta.get('fields', []))}")
    return out


def pick_layer(layers, prefer_substrings):
    """Choose the point layer whose name best matches the preferred keywords."""
    points = [l for l in layers if l["geometryType"] == "esriGeometryPoint"]
    pool = points or layers
    for sub in prefer_substrings:
        for lyr in pool:
            if sub.lower() in (lyr["name"] or "").lower():
                return lyr
    return pool[0]


def query_all(layer_url, where="1=1", geometry=True, page=1000, use_bbox=True):
    """Page through an ArcGIS layer, returning a list of GeoJSON features."""
    params = {
        "where": where,
        "outFields": "*",
        "returnGeometry": "true" if geometry else "false",
        "outSR": "4326",
        "f": "geojson",
    }
    if use_bbox:
        params.update({
            "geometry": json.dumps({
                "xmin": BBOX[0], "ymin": BBOX[1], "xmax": BBOX[2], "ymax": BBOX[3],
                "spatialReference": {"wkid": 4326},
            }),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        })

    features, offset = [], 0
    while True:
        data = fetch(layer_url + "/query", dict(
            params, resultOffset=str(offset), resultRecordCount=str(page)))
        if "error" in data:
            raise RuntimeError(f"query error: {json.dumps(data['error'])[:400]}")
        batch = data.get("features") or []
        features.extend(batch)
        exceeded = data.get("properties", {}).get("exceededTransferLimit") or \
            data.get("exceededTransferLimit")
        print(f"    +{len(batch)} (total {len(features)}) exceeded={exceeded}")
        if len(batch) < page and not exceeded:
            break
        if not batch:
            break
        offset += len(batch)
        if offset > 200000:
            raise RuntimeError("runaway pagination")
    return features


# ---------------------------------------------------------------- geometry --

def _rings(geom):
    """Yield polygon rings (list of [x, y]) from a GeoJSON Polygon/MultiPolygon."""
    if not geom:
        return
    if geom["type"] == "Polygon":
        yield geom["coordinates"]
    elif geom["type"] == "MultiPolygon":
        for poly in geom["coordinates"]:
            yield poly


def _in_ring(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y):
            xint = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xint:
                inside = not inside
        j = i
    return inside


def point_in_polygon(x, y, geom):
    for poly in _rings(geom):
        if not poly:
            continue
        if _in_ring(x, y, poly[0]):
            if not any(_in_ring(x, y, hole) for hole in poly[1:]):
                return True
    return False


def bounds_of(geom):
    xs, ys = [], []
    for poly in _rings(geom):
        for pt in poly[0]:
            xs.append(pt[0])
            ys.append(pt[1])
    return (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)


# ------------------------------------------------------------------- build --

def get_counties():
    print("Counties: querying TIGERweb")
    meta = fetch(TIGERWEB_COUNTIES, {"f": "json"})
    field_names = [f["name"] for f in meta.get("fields", [])]
    print(f"  county fields: {field_names}")
    feats = query_all(TIGERWEB_COUNTIES)

    wanted = {c.lower() for c in DMA_COUNTIES}
    keep = []
    for f in feats:
        props = f.get("properties") or {}
        state = str(props.get("STATE") or props.get("STATEFP") or "")
        name = str(props.get("BASENAME") or props.get("NAME") or "")
        # BASENAME is the bare county name; NAME may include " County".
        bare = name.replace(" County", "").strip()
        if bare.lower() in wanted and (state in ("48", "") or state == "48"):
            props["dma_county"] = bare
            keep.append(f)

    found = sorted({f["properties"]["dma_county"] for f in keep})
    missing = sorted(set(DMA_COUNTIES) - set(found))
    print(f"  matched {len(keep)} county features -> {len(found)} counties")
    print(f"  found: {found}")
    if missing:
        print(f"  !! MISSING: {missing}")
    return keep, found, missing


def assign_county(features, counties):
    """Tag each point with the DMA county containing it; drop the rest."""
    boxes = [(bounds_of(c["geometry"]), c["geometry"],
              c["properties"]["dma_county"]) for c in counties]
    kept, dropped = [], 0
    for f in features:
        geom = f.get("geometry")
        if not geom or geom.get("type") != "Point" or not geom.get("coordinates"):
            dropped += 1
            continue
        x, y = geom["coordinates"][0], geom["coordinates"][1]
        if x is None or y is None:
            dropped += 1
            continue
        hit = None
        for (minx, miny, maxx, maxy), cgeom, cname in boxes:
            if minx <= x <= maxx and miny <= y <= maxy and point_in_polygon(x, y, cgeom):
                hit = cname
                break
        if hit:
            f["properties"]["dma_county"] = hit
            f["geometry"]["coordinates"] = [round(x, 6), round(y, 6)]
            kept.append(f)
        else:
            dropped += 1
    print(f"  inside DMA: {len(kept)}   outside/no-geometry: {dropped}")
    return kept


def collect(name, service_url, prefer):
    print(f"\n{name}: {service_url}")
    layers = inventory(service_url)
    chosen = pick_layer(layers, prefer)
    print(f"  -> using layer {chosen['id']} {chosen['name']!r}")
    feats = query_all(f"{service_url}/{chosen['id']}")
    return feats, chosen["fields"], chosen["id"], chosen["name"], layers


def simplify_counties(counties, tolerance=0.004):
    """Cheap vertex thinning so the outline file stays small."""
    def thin(ring):
        if len(ring) < 40:
            return ring
        out = [ring[0]]
        for pt in ring[1:-1]:
            px, py = out[-1][0], out[-1][1]
            if abs(pt[0] - px) > tolerance or abs(pt[1] - py) > tolerance:
                out.append([round(pt[0], 5), round(pt[1], 5)])
        out.append(ring[-1])
        return out if len(out) > 3 else ring

    for c in counties:
        g = c["geometry"]
        if g["type"] == "Polygon":
            g["coordinates"] = [thin(r) for r in g["coordinates"]]
        elif g["type"] == "MultiPolygon":
            g["coordinates"] = [[thin(r) for r in poly] for poly in g["coordinates"]]
        c["properties"] = {"dma_county": c["properties"]["dma_county"]}
    return counties


def write_geojson(path, features):
    with open(path, "w") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh)
    print(f"  wrote {path} ({len(features)} features, "
          f"{os.path.getsize(path) / 1024:.0f} KB)")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    report = []

    counties, found, missing = get_counties()
    if not counties:
        print("FATAL: no county boundaries resolved")
        return 1

    sf_feats, sf_fields, sf_lid, sf_name, sf_layers = collect(
        "Superfund NPL", SUPERFUND_SERVICE, ["npl", "superfund", "site"])
    bf_feats, bf_fields, bf_lid, bf_name, bf_layers = collect(
        "Brownfields", BROWNFIELDS_SERVICE,
        ["propert", "acres", "brownfield"])

    print("\nClipping Superfund to DMA counties")
    sf_in = assign_county(sf_feats, counties)
    print("Clipping Brownfields to DMA counties")
    bf_in = assign_county(bf_feats, counties)

    counties = simplify_counties(counties)

    write_geojson(os.path.join(OUT_DIR, "counties.geojson"), counties)
    write_geojson(os.path.join(OUT_DIR, "superfund.geojson"), sf_in)
    write_geojson(os.path.join(OUT_DIR, "brownfields.geojson"), bf_in)

    meta = {
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dma": "Houston, TX (Nielsen DMA)",
        "counties": DMA_COUNTIES,
        "counties_missing": missing,
        "counts": {
            "superfund": len(sf_in),
            "brownfields": len(bf_in),
            "superfund_in_bbox": len(sf_feats),
            "brownfields_in_bbox": len(bf_feats),
        },
        "sources": {
            "superfund": {"service": SUPERFUND_SERVICE, "layer": sf_lid, "name": sf_name},
            "brownfields": {"service": BROWNFIELDS_SERVICE, "layer": bf_lid, "name": bf_name},
            "counties": {"service": TIGERWEB_COUNTIES},
        },
        "fields": {
            "superfund": [f[0] for f in sf_fields],
            "brownfields": [f[0] for f in bf_fields],
        },
    }
    with open(os.path.join(OUT_DIR, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)

    # Human-readable schema report for building the UI against.
    report.append("HOUSTON DMA SITE DATA REPORT")
    report.append(f"built {meta['built_utc']}")
    report.append(f"counties found: {found}")
    report.append(f"counties missing: {missing}")
    report.append(f"counts: {json.dumps(meta['counts'])}")
    report.append("\nLAYER INVENTORY (what each EPA service offers)")
    for label, layers in (("Superfund service", sf_layers),
                          ("Brownfields service", bf_layers)):
        report.append(f"  {label}:")
        for lyr in layers:
            report.append(f"    [{lyr['id']}] {lyr['name']!r} "
                          f"geom={lyr['geometryType']} fields={len(lyr['fields'])}")
    report.append(f"  chosen: superfund=[{sf_lid}] {sf_name!r}  "
                  f"brownfields=[{bf_lid}] {bf_name!r}")
    for label, fields, feats in (("SUPERFUND", sf_fields, sf_in),
                                 ("BROWNFIELDS", bf_fields, bf_in)):
        report.append("\n" + "=" * 70)
        report.append(f"{label} FIELDS")
        report.append("=" * 70)
        for n, t, a in fields:
            report.append(f"  {n}  ({t})  alias={a!r}")
        report.append(f"\n{label} SAMPLE RECORDS")
        for f in feats[:3]:
            report.append(json.dumps(f["properties"], indent=2, default=str))
        # value distributions for likely-categorical fields
        report.append(f"\n{label} VALUE COUNTS (fields with <=25 distinct values)")
        if feats:
            keys = list(feats[0]["properties"].keys())
            for k in keys:
                vals = {}
                for f in feats:
                    v = f["properties"].get(k)
                    vals[v] = vals.get(v, 0) + 1
                    if len(vals) > 25:
                        break
                if len(vals) <= 25:
                    report.append(f"  {k}: {json.dumps({str(a): b for a, b in vals.items()})}")

    with open(os.path.join(ROOT, "data-report.txt"), "w") as fh:
        fh.write("\n".join(report))
    print("\nwrote data-report.txt")
    print(json.dumps(meta["counts"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
