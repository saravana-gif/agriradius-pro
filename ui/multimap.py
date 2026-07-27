"""Multi-layer comparison view.

Renders each ticked overlay layer in its own Leaflet panel in a grid,
with synced OR independent pan/zoom (synced follows the top-left master
panel), a cap on how many panels show, a full-screen button, and a
translucent info overlay (layer name + measured stat) on each map.

It reuses the SAME per-layer tile-URL functions the single map uses,
so what you see here matches the main map exactly.
"""

import json

import streamlit as st
import streamlit.components.v1 as components

# Overlay (tile) layers that can be compared, in display order.
TILE_LAYERS = [
    ("dynamic_world", "Dynamic World land cover"),
    ("cropland_confidence", "Cropland confidence"),
    ("paddy", "Paddy (radar)"),
    ("plantation", "Plantations (coconut/arecanut)"),
    ("banana", "Banana (likely)"),
    ("maize", "Maize / kharif"),
    ("worldcereal", "WorldCereal cropland (ESA)"),
    ("aquaculture", "Aquaculture ponds"),
    ("soil_ph", "Soil pH"),
    ("soil_oc", "Soil organic carbon"),
    ("soil_n", "Soil nitrogen"),
]

SAT = "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"


def _tile_url(layer_id, lat, lon, radius, year):
    """Compute a layer's XYZ tile URL (reuses the app's own functions,
    which are cached, so repeat views are free)."""
    from core import usage as _u
    _u.bump("earth_engine")

    if layer_id == "dynamic_world":
        from gee.dynamic_world import get_tile_url
        return get_tile_url(lat, lon, radius, year)
    if layer_id == "cropland_confidence":
        from gee.worldcover import confidence_tile_url
        return confidence_tile_url(lat, lon, radius, year)
    if layer_id == "paddy":
        from gee.paddy import paddy_tile_url
        return paddy_tile_url(lat, lon, radius, year)
    if layer_id == "plantation":
        from gee.plantation import plantation_tile_url
        return plantation_tile_url(lat, lon, radius, year)
    if layer_id == "banana":
        from gee.plantation import banana_tile_url
        return banana_tile_url(lat, lon, radius, year)
    if layer_id == "maize":
        from gee.maize import maize_tile_url
        return maize_tile_url(lat, lon, radius, year)
    if layer_id == "worldcereal":
        from gee.worldcereal import worldcereal_tile_url
        return worldcereal_tile_url(lat, lon, radius)
    if layer_id == "aquaculture":
        from gee.aquaculture import aquaculture_tile_url
        return aquaculture_tile_url(lat, lon, radius, year)
    if layer_id in ("soil_ph", "soil_oc", "soil_n"):
        from gee.soil import soil_tile_url
        return soil_tile_url(lat, lon, radius, layer_id)
    return None


def _stat_for(layer_id):
    """Short measured stat to show on the panel, if we have it."""
    ss = st.session_state
    try:
        if layer_id == "plantation" and ss.get("plantation_stats"):
            p = ss.plantation_stats
            return (f"{p['plantation_ac']:,.0f} ac "
                    f"({p['plantation_pct']}% of area)")
        if layer_id == "paddy" and ss.get("paddy_stats"):
            p = ss.paddy_stats
            return f"{p['paddy_ac']:,.0f} ac ({p['paddy_pct']}%)"
        if layer_id == "cropland_confidence" and ss.get("crosscheck"):
            c = ss.crosscheck
            return (f"{c['confirmed_ac']:,.0f} ac confirmed "
                    f"({c['agreement_pct']}% agree)")
    except Exception:
        return ""
    return ""


def multimap_view():
    ss = st.session_state
    vis = ss.layer_visibility
    lat, lon, radius, year = ss.lat, ss.lon, ss.radius, ss.year
    op = float(ss.get("overlay_opacity", 0.6))

    selected = [(lid, lbl) for lid, lbl in TILE_LAYERS if vis.get(lid)]

    st.caption(
        "Compare layers side by side. Tick overlay layers in the sidebar, "
        "then choose how many panels to show. In the map toolbar: toggle "
        "**synced zoom** (all panels follow the top-left master) or make "
        "them independent, and use **⛶ Full screen**. Key figures show "
        "on a translucent badge on each map.")

    if not selected:
        st.info(
            "Tick one or more overlay layers in the sidebar "
            "(Dynamic World, Plantations, Paddy, Maize, Soil, …) — "
            "they'll appear here as side-by-side maps.")
        return

    cap = min(12, len(selected))
    if cap <= 1:
        maxn = cap
    else:
        maxn = st.slider(
            "Max panels to show", 1, cap, min(4, cap),
            help="How many of your ticked layers to render side by side. "
                 "Each panel is a live Earth Engine layer, so more panels "
                 "= more compute; raise it as far as you need.")
    show = selected[:maxn]
    if len(selected) > maxn:
        st.caption(f"Showing {maxn} of {len(selected)} ticked layers — "
                   f"raise the cap to see more.")

    op = st.slider(
        "Overlay opacity", 0.1, 1.0,
        float(ss.get("overlay_opacity", 0.6)), 0.05,
        help="Turn this up to make sparse detection layers (plantation, "
             "paddy, maize) easier to spot over the satellite image.")

    st.caption(
        "Tip: full-cover layers (Dynamic World, Cropland Confidence, "
        "Soil) paint the whole area; detection layers (plantation, "
        "paddy, maize, banana) only colour the pixels they flag, so "
        "they look sparse — zoom in or raise opacity to see them.")

    layers = []
    with st.spinner("Rendering comparison maps (first time is slower)…"):
        for lid, lbl in show:
            try:
                url = _tile_url(lid, lat, lon, radius, year)
            except Exception as e:
                from core import usage as _u
                _u.note_error("earth_engine", e)
                url = None
            layers.append({
                "name": lbl if url else lbl + " (unavailable)",
                "url": url or "",
                "stat": _stat_for(lid) if url else "",
            })

    if not any(l["url"] for l in layers):
        st.warning("Couldn't render any layers (Earth Engine may be "
                   "busy). Try fewer panels or Refresh.")
        return

    n = len(layers)
    cols = (1 if n == 1 else 2 if n <= 4 else 3 if n <= 9 else 4)
    rows = (n + cols - 1) // cols
    height = 78 + rows * 372

    cfg = {
        "lat": lat, "lon": lon,
        "radius_m": (radius * 1000
                     if ss.get("mode") == "Area (radius)" else 0),
        "zoom": int(ss.get("map_zoom", 11)),
        "opacity": op, "cols": cols, "rows": rows,
        "sat": SAT, "layers": layers,
    }

    components.html(
        _HTML.replace("__CFG__", json.dumps(cfg)),
        height=height, scrolling=False)


_HTML = """
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  #wrap{font-family:Inter,system-ui,sans-serif;}
  #bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 8px;}
  .btn{background:linear-gradient(120deg,#16A34A,#0891B2);color:#fff;border:0;
       border-radius:9px;padding:7px 13px;cursor:pointer;font-weight:600;font-size:13px;}
  .btn.off{background:#64748B;}
  #hint{color:#64748B;font-size:12px;}
  #grid{display:grid;gap:8px;}
  .panel{position:relative;border-radius:12px;overflow:hidden;border:1px solid #d5dee6;
         box-shadow:0 6px 18px rgba(15,23,42,.08);}
  .panel .m{width:100%;height:360px;}
  .ovl{position:absolute;top:8px;left:8px;z-index:500;background:rgba(11,31,58,.60);
       color:#fff;padding:6px 10px;border-radius:9px;font-size:12px;max-width:82%;
       line-height:1.25;box-shadow:0 2px 8px rgba(0,0,0,.25);}
  .ovl b{display:block;font-size:12.5px;letter-spacing:.01em;}
  .ovl .s{color:#9FE7C9;font-family:'JetBrains Mono',monospace;font-size:11px;}
  .master{position:absolute;top:8px;right:8px;z-index:500;background:rgba(6,182,212,.85);
          color:#04283a;font-weight:700;font-size:10px;padding:3px 8px;border-radius:999px;}
  #grid.has-expanded .panel{display:none;}
  #grid.has-expanded .panel.expanded{display:block;grid-column:1 / -1;}
  :fullscreen #grid{height:calc(100vh - 60px);}
</style>
<div id="wrap">
  <div id="bar">
    <button class="btn" id="syncBtn">&#128279; Synced zoom: ON</button>
    <button class="btn" id="fsBtn">&#9974; Full screen</button>
    <span id="hint">Synced: all panels follow the top-left master. Double-click any map to expand it full / restore.</span>
  </div>
  <div id="grid"></div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.sync@0.2.4/L.Map.Sync.js"></script>
<script>
(function(){
  var CFG = __CFG__;
  var grid = document.getElementById('grid');
  grid.style.gridTemplateColumns = 'repeat(' + CFG.cols + ',1fr)';
  var maps = [];
  CFG.layers.forEach(function(ly, i){
    var panel = document.createElement('div'); panel.className = 'panel';
    var md = document.createElement('div'); md.className = 'm'; md.id = 'm' + i;
    var ov = document.createElement('div'); ov.className = 'ovl';
    ov.innerHTML = '<b>' + ly.name + '</b>' + (ly.stat ? '<span class="s">' + ly.stat + '</span>' : '');
    panel.appendChild(md); panel.appendChild(ov);
    if(i === 0){ var mb = document.createElement('div'); mb.className='master'; mb.textContent='MASTER'; panel.appendChild(mb); }
    grid.appendChild(panel);
    var map = L.map('m' + i, {center:[CFG.lat, CFG.lon], zoom:CFG.zoom, zoomControl:(i===0), doubleClickZoom:false});
    L.tileLayer(CFG.sat, {maxZoom:22, maxNativeZoom:20}).addTo(map);
    if(ly.url){ L.tileLayer(ly.url, {opacity:CFG.opacity, maxZoom:22, minZoom:1, maxNativeZoom:16, zIndex:400}).addTo(map); }
    if(CFG.radius_m > 0){ L.circle([CFG.lat, CFG.lon], {radius:CFG.radius_m, color:'#22D3EE', weight:2, fill:false}).addTo(map); }
    map.on('dblclick', function(){ toggleExpand(i); });
    maps.push(map);
  });

  function toggleExpand(idx){
    var panels = Array.prototype.slice.call(document.querySelectorAll('.panel'));
    var p = panels[idx];
    var expanding = !p.classList.contains('expanded');
    panels.forEach(function(x){ x.classList.remove('expanded'); });
    document.getElementById('grid').classList.toggle('has-expanded', expanding);
    var fs = !!document.fullscreenElement;
    if(expanding){
      p.classList.add('expanded');
      p.querySelector('.m').style.height = (fs ? (window.innerHeight - 70) : 640) + 'px';
    } else {
      var h = (fs ? Math.floor((window.innerHeight - 70) / CFG.rows) : 360) + 'px';
      document.querySelectorAll('.m').forEach(function(el){ el.style.height = h; });
    }
    setTimeout(function(){ maps.forEach(function(m){ m.invalidateSize(); }); }, 160);
  }
  var synced = false;
  function setSync(on){
    for(var i=0;i<maps.length;i++){ for(var j=0;j<maps.length;j++){ if(i!==j){ try{ on ? maps[i].sync(maps[j]) : maps[i].unsync(maps[j]); }catch(e){} } } }
    synced = on;
    var b = document.getElementById('syncBtn');
    b.innerHTML = on ? '&#128279; Synced zoom: ON' : '&#128275; Synced zoom: OFF';
    b.className = on ? 'btn' : 'btn off';
    // On enabling, snap everyone to the master's view.
    if(on && maps.length){ var c = maps[0].getCenter(), z = maps[0].getZoom(); maps.forEach(function(m,k){ if(k>0) m.setView(c, z); }); }
  }
  setTimeout(function(){ setSync(true); }, 350);
  document.getElementById('syncBtn').onclick = function(){ setSync(!synced); };
  document.getElementById('fsBtn').onclick = function(){
    var w = document.getElementById('wrap');
    if(!document.fullscreenElement){ (w.requestFullscreen || w.webkitRequestFullscreen || function(){}).call(w); }
    else { document.exitFullscreen && document.exitFullscreen(); }
  };
  function resize(){
    var fs = !!document.fullscreenElement;
    var h = fs ? Math.floor((window.innerHeight - 70) / CFG.rows) + 'px' : '360px';
    document.querySelectorAll('.m').forEach(function(el){ el.style.height = h; });
    setTimeout(function(){ maps.forEach(function(m){ m.invalidateSize(); }); }, 200);
  }
  document.addEventListener('fullscreenchange', resize);
  setTimeout(function(){ maps.forEach(function(m){ m.invalidateSize(); }); }, 500);
})();
</script>
"""
