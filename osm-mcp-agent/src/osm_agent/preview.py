"""Build a compact, self-contained HTML preview snippet for chat embeds.

The output is a small Leaflet map (~300×200 px) with markers/routes from
the FeatureCollection.  Designed to be rendered inside an <iframe> or
injected directly into a webview / chat bubble.

No server-side assets required: Leaflet + tiles from CDN.
"""
from __future__ import annotations

import json
from typing import Any

# Minimal inline HTML template — Leaflet from CDN, OSM tiles, auto-fit bounds.
_PREVIEW_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<style>
*{margin:0;padding:0;box-sizing:border-box}
#map{width:100%;height:200px;border-radius:8px}
.info{font:12px/1.4 system-ui,sans-serif;padding:6px 8px;max-height:60px;
  overflow:auto;color:#333}
.info b{color:#1a1a2e}
</style>
</head>
<body>
<div id="map"></div>
<div class="info">SUMMARY_PLACEHOLDER</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
(function(){
  var fc=FC_PLACEHOLDER;
  var map=L.map('map',{zoomControl:false,attributionControl:false});
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19}).addTo(map);
  var style={color:'#3388ff',weight:3,fillOpacity:0.5,radius:6};
  var layer=L.geoJSON(fc,{
    style:style,
    pointToLayer:function(f,ll){return L.circleMarker(ll,style)},
    onEachFeature:function(f,lyr){
      var p=f.properties||{};
      var t=[];for(var k in p){if(t.length<4)t.push('<b>'+k+'</b>: '+String(p[k]).slice(0,60));}
      if(t.length)lyr.bindPopup(t.join('<br>'));
    }
  }).addTo(map);
  var b=layer.getBounds();
  if(b.isValid())map.fitBounds(b.pad(0.15));
  else map.setView([45.46,9.19],5);
})();
</script>
</body>
</html>"""


def build_preview_html(
    feature_collection: dict[str, Any],
    summary: str = "",
) -> str | None:
    """Return a self-contained HTML snippet for chat preview.

    Parameters
    ----------
    feature_collection:
        A GeoJSON FeatureCollection dict.  If it has no features ``None``
        is returned (nothing to preview).
    summary:
        Short text to display below the map (HTML-escaped by caller or
        plain text).

    Returns
    -------
    A complete HTML document string (~2-10 KB) or ``None``.
    """
    features = feature_collection.get("features", [])
    if not features:
        return None

    fc_json = json.dumps(feature_collection, ensure_ascii=False)
    # Escape </script> inside JSON to avoid breaking the HTML
    fc_json = fc_json.replace("</", "<\\/")

    html = _PREVIEW_TEMPLATE.replace("FC_PLACEHOLDER", fc_json)
    # Build a short summary line from feature names
    if not summary:
        names = []
        for f in features[:5]:
            name = (f.get("properties") or {}).get("name", "")
            if name:
                names.append(name)
        summary = ", ".join(names) if names else f"{len(features)} result(s)"
        if len(features) > 5:
            summary += f" … +{len(features) - 5} more"

    # Sanitize summary for safe HTML insertion (no script injection)
    safe_summary = (
        summary
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    html = html.replace("SUMMARY_PLACEHOLDER", safe_summary)
    return html
