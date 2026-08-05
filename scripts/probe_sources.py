"""Probe candidate EPA / Census data endpoints and report what they expose.

Run on a GitHub Actions runner (which has open outbound internet) so we can learn
the real service metadata -- layer ids, field names, sample records and record
counts inside the Houston DMA bounding box -- before writing the real fetcher.

Output is intentionally verbose but truncated so it stays readable in a job log.
"""

import json
import sys
import urllib.parse
import urllib.request

TIMEOUT = 90
UA = {"User-Agent": "houston-dma-site-map/0.1 (data discovery)"}

# Generous bounding box around the 20-county Houston DMA (lon/lat).
BBOX = (-97.2, 28.2, -94.0, 31.4)


def get(url, params=None):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def get_json(url, params=None):
    status, body = get(url, params)
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, {"__raw__": body[:600]}


def hr(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def describe_arcgis_service(root):
    hr(f"ARCGIS SERVICE: {root}")
    try:
        status, data = get_json(root, {"f": "json"})
    except Exception as exc:  # noqa: BLE001 - discovery script, report everything
        print(f"  FAILED: {exc!r}")
        return []
    print(f"  HTTP {status}")
    if "error" in data:
        print(f"  ERROR: {json.dumps(data['error'])[:400]}")
        return []
    layers = data.get("layers", []) + data.get("tables", [])
    for lyr in layers:
        print(f"  layer {lyr.get('id')}: {lyr.get('name')}")
    if not layers:
        print(f"  (no layers) keys={list(data)[:20]}")
    return [lyr.get("id") for lyr in layers]


def describe_layer(root, layer_id, sample=True):
    url = f"{root}/{layer_id}"
    hr(f"ARCGIS LAYER: {url}")
    try:
        status, data = get_json(url, {"f": "json"})
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED: {exc!r}")
        return
    print(f"  HTTP {status}  name={data.get('name')!r}  type={data.get('geometryType')}")
    if "error" in data:
        print(f"  ERROR: {json.dumps(data['error'])[:400]}")
        return
    fields = data.get("fields") or []
    print(f"  fields ({len(fields)}):")
    for f in fields:
        print(f"    - {f.get('name')} ({f.get('type')}) alias={f.get('alias')!r}")
    print(f"  maxRecordCount={data.get('maxRecordCount')} "
          f"supportsPagination={data.get('advancedQueryCapabilities', {}).get('supportsPagination')}")

    if not sample:
        return

    q = f"{url}/query"
    geom = json.dumps({
        "xmin": BBOX[0], "ymin": BBOX[1], "xmax": BBOX[2], "ymax": BBOX[3],
        "spatialReference": {"wkid": 4326},
    })
    common = {
        "geometry": geom,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "where": "1=1",
    }
    try:
        status, cnt = get_json(q, dict(common, returnCountOnly="true", f="json"))
        print(f"  COUNT in Houston bbox: {cnt}")
    except Exception as exc:  # noqa: BLE001
        print(f"  count failed: {exc!r}")
    try:
        status, feats = get_json(q, dict(
            common, outFields="*", returnGeometry="true", resultRecordCount="2",
            outSR="4326", f="geojson"))
        print("  SAMPLE (geojson, 2 features):")
        print(json.dumps(feats, indent=2)[:2500])
    except Exception as exc:  # noqa: BLE001
        print(f"  sample failed: {exc!r}")


def probe_url(label, url):
    hr(f"{label}: {url}")
    try:
        status, body = get(url)
        print(f"  HTTP {status}")
        print("  " + body[:1200].replace("\n", "\n  "))
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED: {exc!r}")


def main():
    # --- EPA "Environmental Mapping / efpoints" service: Superfund + Brownfields
    root = "https://geopub.epa.gov/arcgis/rest/services/EMEF/efpoints/MapServer"
    ids = describe_arcgis_service(root)
    for lid in ids[:12]:
        describe_layer(root, lid, sample=True)

    # --- EPA ArcGIS Online org: list hosted feature services
    hr("EPA ArcGIS Online org services (cJ9YHowT8TU7DUyn)")
    try:
        status, data = get_json(
            "https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services",
            {"f": "json"})
        print(f"  HTTP {status}")
        for svc in data.get("services", []):
            print(f"    {svc.get('name')}  ({svc.get('type')})")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED: {exc!r}")

    # --- Envirofacts REST (SEMS = Superfund, ACRES/BF = brownfields)
    for label, url in [
        ("Envirofacts SEMS active sites",
         "https://data.epa.gov/efservice/sems_active_sites/state_code/TX/JSON/rows/0:1"),
        ("Envirofacts SEMS site",
         "https://data.epa.gov/efservice/SEMS.ENVIROFACTS_SITE/state_code/TX/JSON/rows/0:1"),
        ("Envirofacts ACRES property",
         "https://data.epa.gov/efservice/ACRES.BF_PROPERTY/JSON/rows/0:1"),
    ]:
        probe_url(label, url)

    # --- Census county boundaries (for precise DMA clipping + map outlines)
    probe_url(
        "Census TIGERweb counties (TX sample)",
        "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/"
        "MapServer?f=json")

    print("\nDONE")


if __name__ == "__main__":
    sys.exit(main())
