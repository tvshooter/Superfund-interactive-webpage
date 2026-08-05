# Contaminated Sites in the Houston TV Market

An interactive map of federal and state contaminated-site programs across the
20 counties of the Nielsen Houston DMA: EPA **Superfund (National Priorities
List)** sites, EPA **brownfield properties**, and TCEQ's **voluntary cleanup**
and **brownfield site assessment** programs.

Current data — **1,225 sites**:

| Layer | Count |
| --- | --- |
| Superfund (NPL) | 22 |
| Deleted from NPL | 3 |
| EPA brownfields | 192 |
| TCEQ brownfields (BSA) | 28 |
| TCEQ voluntary cleanup (VCP) | 980 |

## Viewing it

The page is plain static HTML — everything it needs is in `web/`.

- **Locally:** `cd web && python3 -m http.server 8000`, then open
  <http://localhost:8000>. (Opening `index.html` straight off the disk will not
  work; browsers block the data files over `file://`.)
- **Shared link:** see *Publishing* below.

## Publishing (one-time setup)

A workflow deploys `web/` to GitHub Pages, but GitHub Pages has to be switched
on by a repo admin first — the Actions token isn't allowed to create the site.

1. Go to **Settings → Pages** in this repository.
2. Under **Build and deployment → Source**, choose **GitHub Actions**.
3. Run the **Deploy to GitHub Pages** workflow (Actions tab → *Run workflow*),
   or just push to the branch.

The published URL will be
`https://tvshooter.github.io/Superfund-interactive-webpage/`, which is what you
share with others.

## What's on the map

| Layer | What it is |
| --- | --- |
| Superfund (NPL) | Sites currently on EPA's National Priorities List |
| Deleted from NPL | Sites cleaned up and removed from the list — worth showing, since the contamination history is often still the story |
| EPA brownfield | Properties tracked in EPA's ACRES brownfields database |
| TCEQ brownfield | Sites in TCEQ's Brownfields Site Assessment program |
| TCEQ voluntary cleanup | Sites in TCEQ's Voluntary Cleanup Program — by far the largest layer, and the one that captures ordinary commercial contamination (old dry cleaners, gas stations, industrial parcels) |

Every marker links back to its EPA record. Filters (search, county, layer
toggles) apply to the map, the list and the **Export CSV** button together, so
you can pull a clean spreadsheet of, say, every site in Galveston County.

## Scope and caveats

Worth knowing before anything from this goes on air:

- **"Superfund" here means NPL sites.** EPA's SEMS database also tracks
  thousands of sites in assessment or screening that never reached the NPL;
  those are not on this map.
- **The EPA and TCEQ brownfield layers are different programs, and they
  overlap.** A property that took an EPA grant and also enrolled in a state
  program appears in both — the same address can carry both a blue and a green
  or violet marker. Neither list is a superset of the other.
- **A TCEQ voluntary cleanup listing is not a finding of danger.** Owners enroll
  voluntarily, often to clear a title for a sale, and many sites in the program
  have already received a certificate of completion. The layer shows where the
  program has been used, not where contamination is currently unaddressed.
- **TCEQ sites have no per-site public URL.** The agency's Central Registry has
  no stable deep link (I tested three URL patterns; all return generic pages),
  so popups show the TCEQ registry number — searchable in Central Registry —
  and link to the program page instead.
- Coordinates come from EPA and vary in precision. Some sites are plotted at a
  facility centroid or an address geocode rather than the contamination
  footprint, so a marker locates a site — it does not draw its boundary.
- County assignment is computed here by point-in-polygon against Census
  boundaries, not taken from EPA's own county field.

## Data sources

| Dataset | Source |
| --- | --- |
| Superfund NPL sites | [EPA — NPL Sites with Status Information](https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/Superfund_National_Priorities_List_%28NPL%29_Sites_with_Status_Information/FeatureServer) |
| Brownfields | [EPA Environmental Mapping — Brownfields (ACRES)](https://geopub.epa.gov/arcgis/rest/services/EMEF/efpoints/MapServer/5) |
| TCEQ voluntary cleanup | [TCEQ Public GIS — VCP](https://gisweb.tceq.texas.gov/arcgis/rest/services/Public/VCP/MapServer/0) |
| TCEQ brownfields | [TCEQ Public GIS — Brownfield](https://gisweb.tceq.texas.gov/arcgis/rest/services/Public/Brownfield/MapServer/0) |
| County boundaries | [Census TIGERweb](https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1) |

The Houston DMA is the 20 counties Nielsen assigns to the market: Austin,
Brazoria, Calhoun, Chambers, Colorado, Fort Bend, Galveston, Grimes, Harris,
Jackson, Liberty, Matagorda, Montgomery, Polk, San Jacinto, Trinity, Walker,
Waller, Washington and Wharton.

## Refreshing the data

TCEQ publishes several more remediation layers on the same server that are not
on this map — leaking petroleum storage tanks (~8,500 in the market), dry
cleaner remediation (~190), state Superfund (~55) and landfills. Adding one is a
few lines in `scripts/fetch_data.py`; `tceq-probe.txt` lists every layer with
its fields and local counts.

`scripts/fetch_data.py` pulls from the services above, clips to the DMA and
writes `web/data/*.geojson`. It runs automatically on the 1st of each month via
the **Build site data** workflow, which commits any changes. You can also run it
by hand from the Actions tab, or locally with `python3 scripts/fetch_data.py`.

`data-report.txt` is regenerated on each run: field lists, sample records and
value counts for both datasets, plus which EPA service each layer came from.

## Layout

```
web/index.html         the map (all markup, styles and script in one file)
web/data/              generated GeoJSON + meta.json
tceq-probe.txt         inventory of TCEQ's other remediation layers
web/vendor/            Leaflet, vendored so the page needs no CDN
scripts/fetch_data.py  the data build
data-report.txt        schema + samples from the last build
```
