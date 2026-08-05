"""Inventory TCEQ's open-data catalog for remediation-related layers.

Writes tceq-probe.txt (committed by the workflow) rather than printing
everything, so the full result survives job-log truncation.
"""

import json
import os
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tceq-probe.txt")
UA = {"User-Agent": "houston-dma-site-map/1.0 (data discovery)"}
TIMEOUT = 120

BBOX = (-97.4, 27.9, -94.0, 31.5)

KEYWORDS = [
    "brownfield", "voluntary", "vcp", "cleanup", "clean up", "superfund",
    "remediation", "corrective", "dry clean", "petroleum storage", "leaking",
    "lpst", "solid waste", "landfill", "innocent owner", "state site",
]

CATALOGS = [
    "https://gis-tceq.opendata.arcgis.com/api/feed/dcat-us/1.1.json",
    "https://gis-tceq.opendata.arcgis.com/api/search/v1/collections/dataset/items?limit=250",
]

out = []


def log(s=""):
    print(s)
    out.append(str(s))


def get(url, params=None):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def get_json(url, params=None):
    return json.loads(get(url, params))


def interesting(title):
    t = (title or "").lower()
    return any(k in t for k in KEYWORDS)


def describe_layer(url):
    """Print fields + Houston-bbox count for an ArcGIS layer URL."""
    try:
        meta = get_json(url, {"f": "json"})
    except Exception as exc:  # noqa: BLE001
        log(f"      metadata failed: {exc!r}")
        return
    log(f"      name={meta.get('name')!r} geom={meta.get('geometryType')}")
    if "fields" in meta:
        log("      fields: " + ", ".join(f["name"] for f in meta["fields"]))
    try:
        geom = json.dumps({
            "xmin": BBOX[0], "ymin": BBOX[1], "xmax": BBOX[2], "ymax": BBOX[3],
            "spatialReference": {"wkid": 4326},
        })
        cnt = get_json(url + "/query", {
            "where": "1=1", "geometry": geom, "geometryType": "esriGeometryEnvelope",
            "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
            "returnCountOnly": "true", "f": "json",
        })
        log(f"      count in Houston bbox: {cnt}")
        sample = get_json(url + "/query", {
            "where": "1=1", "geometry": geom, "geometryType": "esriGeometryEnvelope",
            "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*", "resultRecordCount": "1", "outSR": "4326",
            "returnGeometry": "true", "f": "geojson",
        })
        log("      sample: " + json.dumps(sample)[:1200])
    except Exception as exc:  # noqa: BLE001
        log(f"      query failed: {exc!r}")


def main():
    services = set()

    for cat in CATALOGS:
        log("\n" + "=" * 78)
        log(f"CATALOG {cat}")
        log("=" * 78)
        try:
            data = get_json(cat)
        except Exception as exc:  # noqa: BLE001
            log(f"  FAILED: {exc!r}")
            continue

        items = data.get("dataset") or data.get("features") or []
        log(f"  {len(items)} datasets")
        for it in items:
            props = it.get("properties", it)
            title = props.get("title") or it.get("title")
            if not interesting(title):
                continue
            log(f"\n  * {title}")
            dists = it.get("distribution") or props.get("distribution") or []
            for d in dists:
                url = d.get("accessURL") or d.get("downloadURL") or d.get("href")
                fmt = d.get("format") or d.get("title")
                if url and ("FeatureServer" in url or "MapServer" in url):
                    log(f"      [{fmt}] {url}")
                    services.add(url.split("?")[0])
            # Hub v1 search results carry the service url differently
            for key in ("url", "serviceUrl"):
                u = props.get(key)
                if u and ("FeatureServer" in u or "MapServer" in u):
                    log(f"      [{key}] {u}")
                    services.add(u.split("?")[0])

    log("\n" + "=" * 78)
    log("CANDIDATE SERVICES — details")
    log("=" * 78)
    for url in sorted(services):
        log(f"\n  {url}")
        # A bare service URL needs a layer id appended; a layer URL already has one.
        tail = url.rstrip("/").split("/")[-1]
        if tail.isdigit():
            describe_layer(url)
        else:
            try:
                svc = get_json(url, {"f": "json"})
                for lyr in (svc.get("layers") or []):
                    log(f"    layer {lyr.get('id')}: {lyr.get('name')}")
                    describe_layer(f"{url.rstrip('/')}/{lyr.get('id')}")
            except Exception as exc:  # noqa: BLE001
                log(f"    service failed: {exc!r}")

    with open(OUT, "w") as fh:
        fh.write("\n".join(out))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
