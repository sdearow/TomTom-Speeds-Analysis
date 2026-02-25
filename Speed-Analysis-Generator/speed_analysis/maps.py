"""Interactive Folium maps and static contextily maps for speed analysis."""

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import geopandas as gpd
import folium
import branca.colormap as cm
import contextily as cx

from .config import RoadConfig
from .charts import fig_to_base64


# ================================================================
# HELPER FUNCTIONS
# ================================================================

def _build_speed_gdf(segments, day_type, direction, value_col,
                     hour_filter=None, agg_func="mean"):
    """Aggregate segment speeds and return a GeoDataFrame in EPSG:4326."""
    sub = segments[(segments["day_type"] == day_type)
                   & (segments["direction"] == direction)]
    if hour_filter is not None:
        sub = sub[sub["hour"].isin(hour_filter)]
    agg = sub.groupby("seg_idx").agg({
        value_col: agg_func, "geometry": "first",
        "cum_dist_start": "first", "cum_dist_mid": "first",
        "seg_distance": "first", "streetName": "first",
        "speedLimit": "first",
        "avg_speed": "mean", "p85": "mean", "std_speed": "mean",
    }).reset_index()
    return gpd.GeoDataFrame(agg, geometry="geometry", crs="EPSG:4326")


def _add_basemap(ax, crs="EPSG:4326"):
    try:
        cx.add_basemap(ax, crs=crs, source=cx.providers.CartoDB.Positron,
                        zoom=16, attribution=False)
        return True
    except Exception:
        pass
    try:
        cx.add_basemap(ax, crs=crs, source=cx.providers.OpenStreetMap.Mapnik,
                        zoom=16, attribution=False)
        return True
    except Exception:
        pass
    ax.set_facecolor("#eef0f4")
    ax.grid(True, alpha=0.25, linestyle="--", color="#888", zorder=0)
    ax.tick_params(labelsize=7, colors="#555")
    ax.ticklabel_format(useOffset=False, style="plain")
    for spine in ax.spines.values():
        spine.set_edgecolor("#999")
        spine.set_linewidth(0.8)
    return False


def _annotate_segments(ax, gdf, value_col):
    total_dist = gdf["cum_dist_start"].max() + gdf["seg_distance"].max()
    interval = 500 if total_dist > 1500 else 250
    for target_m in range(0, int(total_dist) + interval, interval):
        candidates = gdf.loc[(gdf["cum_dist_start"] <= target_m)
                              & (gdf["cum_dist_start"] + gdf["seg_distance"] >= target_m)]
        if candidates.empty:
            continue
        row = candidates.iloc[0]
        d = row["seg_distance"]
        frac = (target_m - row["cum_dist_start"]) / d if d > 0 else 0.0
        frac = max(0.0, min(1.0, frac))
        pt = row["geometry"].interpolate(frac, normalized=True)
        label = f"{target_m} m" if target_m < 1000 else f"{target_m/1000:.1f} km"
        ax.annotate(label, xy=(pt.x, pt.y), fontsize=7, fontweight="bold",
                    color="#1a237e", ha="left", va="bottom",
                    xytext=(5, 5), textcoords="offset points",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white",
                              ec="#1a237e", alpha=0.85, lw=0.5),
                    zorder=5)
        ax.plot(pt.x, pt.y, "o", color="#1a237e", markersize=4, zorder=5)

    start_pt = list(gdf.iloc[0]["geometry"].coords)[0]
    end_pt = list(gdf.iloc[-1]["geometry"].coords)[-1]
    ax.plot(start_pt[0], start_pt[1], "^", color="green", markersize=10,
            zorder=6, label="Inizio")
    ax.plot(end_pt[0], end_pt[1], "v", color="red", markersize=10,
            zorder=6, label="Fine")

    vals = gdf[value_col]
    metric_label = "V85" if "p85" in value_col else "Vel. media"
    stats_text = (f"{metric_label}: media={vals.mean():.1f}, "
                  f"max={vals.max():.1f}, min={vals.min():.1f} km/h")
    ax.text(0.02, 0.02, stats_text, transform=ax.transAxes, fontsize=8,
            va="bottom", ha="left",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.9))
    ax.legend(loc="upper right", fontsize=8)


def _add_folium_progressive(m, gdf, interval_m=None):
    total_dist = gdf["cum_dist_start"].max() + gdf["seg_distance"].max()
    if interval_m is None:
        interval_m = 500 if total_dist > 1500 else 250
    for target_m in range(0, int(total_dist) + interval_m, interval_m):
        candidates = gdf.loc[(gdf["cum_dist_start"] <= target_m)
                              & (gdf["cum_dist_start"] + gdf["seg_distance"] >= target_m)]
        if candidates.empty:
            continue
        row = candidates.iloc[0]
        d = row["seg_distance"]
        frac = (target_m - row["cum_dist_start"]) / d if d > 0 else 0.0
        frac = max(0.0, min(1.0, frac))
        pt = row["geometry"].interpolate(frac, normalized=True)
        label = f"{target_m} m" if target_m < 1000 else f"{target_m/1000:.1f} km"
        folium.Marker(
            [pt.y, pt.x],
            icon=folium.DivIcon(
                html=(f'<div style="font-size:10px;font-weight:bold;background:white;'
                      f'padding:2px 5px;border:1px solid #1a237e;border-radius:3px;'
                      f'white-space:nowrap;box-shadow:1px 1px 3px rgba(0,0,0,.3);'
                      f'color:#1a237e;">{label}</div>'),
                icon_size=(70, 22), icon_anchor=(35, 11)),
        ).add_to(m)

    sc = list(gdf.iloc[0]["geometry"].coords)[0]
    ec = list(gdf.iloc[-1]["geometry"].coords)[-1]
    folium.Marker([sc[1], sc[0]], icon=folium.Icon(color="green"),
                  popup="Inizio (0 m)").add_to(m)
    folium.Marker([ec[1], ec[0]], icon=folium.Icon(color="red"),
                  popup=f"Fine ({total_dist:.0f} m)").add_to(m)


# ================================================================
# FOLIUM MAP BUILDERS
# ================================================================

def make_folium_map(gdf, value_col, title, vmin=20, vmax=80,
                     reverse_cmap=False, speed_limit=50):
    clat = gdf.geometry.centroid.y.mean()
    clon = gdf.geometry.centroid.x.mean()
    m = folium.Map(location=[clat, clon], zoom_start=15,
                   tiles="CartoDB positron")

    colors = (["green", "yellow", "red"] if not reverse_cmap
              else ["red", "yellow", "green"])
    cmap_obj = cm.LinearColormap(colors=colors, vmin=vmin, vmax=vmax,
                                  caption=f"{title} (km/h)")

    for _, row in gdf.iterrows():
        coords = [[c[1], c[0]] for c in row.geometry.coords]
        popup_html = (
            f"<b>{row['streetName']}</b><br>"
            f"Progr.: {row['cum_dist_start']:.0f} m<br>"
            f"Vel. media: {row['avg_speed']:.1f} km/h<br>"
            f"V85: {row['p85']:.1f} km/h<br>"
            f"Dev. std: {row['std_speed']:.1f} km/h<br>"
            f"Limite: {row['speedLimit']} km/h<br>"
            f"Lungh.: {row['seg_distance']:.0f} m"
        )
        folium.PolyLine(coords, weight=10, color=cmap_obj(row[value_col]),
                        opacity=0.9,
                        popup=folium.Popup(popup_html, max_width=280)).add_to(m)
    cmap_obj.add_to(m)
    _add_folium_progressive(m, gdf)

    # Stats box
    vals = gdf[value_col]
    metric = "V85" if "p85" in value_col else ("Dev. Std." if "std" in value_col else "Vel. media")
    html = (
        f'<div style="position:fixed;bottom:30px;left:10px;z-index:9999;'
        f'background:white;padding:10px 14px;border-radius:6px;'
        f'box-shadow:0 2px 8px rgba(0,0,0,.3);font-family:sans-serif;'
        f'font-size:12px;max-width:320px;line-height:1.5;">'
        f'<b style="color:#1a237e;">{title}</b><br>'
        f'{metric}: media={vals.mean():.1f}, max={vals.max():.1f}, '
        f'min={vals.min():.1f} km/h<br>'
        f'<span style="color:#c00;">&#9644;</span> Limite {speed_limit} km/h'
        f'</div>'
    )
    m.get_root().html.add_child(folium.Element(html))
    return m


def make_folium_map_combined(gdfs, value_col, title, vmin=20, vmax=80,
                               reverse_cmap=False, speed_limit=50):
    """Folium map with multiple directions as layer groups."""
    all_lats, all_lons = [], []
    for _, gdf in gdfs:
        all_lats.extend(gdf.geometry.centroid.y.tolist())
        all_lons.extend(gdf.geometry.centroid.x.tolist())
    clat, clon = np.mean(all_lats), np.mean(all_lons)
    m = folium.Map(location=[clat, clon], zoom_start=14,
                   tiles="CartoDB positron")

    colors = (["green", "yellow", "red"] if not reverse_cmap
              else ["red", "yellow", "green"])
    cmap_obj = cm.LinearColormap(colors=colors, vmin=vmin, vmax=vmax,
                                  caption=f"{title} (km/h)")

    for dir_label, gdf in gdfs:
        fg = folium.FeatureGroup(name=f"Dir. {dir_label}")
        for _, row in gdf.iterrows():
            coords = [[c[1], c[0]] for c in row.geometry.coords]
            popup_html = (
                f"<b>Dir. {dir_label} \u2014 {row['streetName']}</b><br>"
                f"Progr.: {row['cum_dist_start']:.0f} m<br>"
                f"Vel. media: {row['avg_speed']:.1f} km/h<br>"
                f"V85: {row['p85']:.1f} km/h<br>"
                f"Dev. std: {row['std_speed']:.1f} km/h<br>"
                f"Limite: {row['speedLimit']} km/h<br>"
                f"Lungh.: {row['seg_distance']:.0f} m"
            )
            folium.PolyLine(coords, weight=10, color=cmap_obj(row[value_col]),
                            opacity=0.9,
                            popup=folium.Popup(popup_html, max_width=300)).add_to(fg)
        sc = list(gdf.iloc[0]["geometry"].coords)[0]
        ec = list(gdf.iloc[-1]["geometry"].coords)[-1]
        folium.Marker([sc[1], sc[0]], icon=folium.Icon(color="green"),
                      popup=f"Inizio Dir. {dir_label}").add_to(fg)
        folium.Marker([ec[1], ec[0]], icon=folium.Icon(color="red"),
                      popup=f"Fine Dir. {dir_label}").add_to(fg)
        fg.add_to(m)

    cmap_obj.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)

    # Stats box
    stats_lines = [f'<b style="color:#1a237e;">{title}</b><br>']
    for dir_label, gdf in gdfs:
        vals = gdf[value_col]
        metric = "V85" if "p85" in value_col else ("Dev. Std." if "std" in value_col else "Vel. media")
        stats_lines.append(
            f'<b>{dir_label}</b>: {metric} media={vals.mean():.1f}, '
            f'max={vals.max():.1f}, min={vals.min():.1f} km/h<br>')
    stats_lines.append(
        f'<span style="color:#c00;">&#9644;</span> Limite {speed_limit} km/h')
    html = (
        f'<div style="position:fixed;bottom:30px;left:10px;z-index:9999;'
        f'background:white;padding:10px 14px;border-radius:6px;'
        f'box-shadow:0 2px 8px rgba(0,0,0,.3);font-family:sans-serif;'
        f'font-size:12px;max-width:360px;line-height:1.5;">'
        + "".join(stats_lines) + '</div>')
    m.get_root().html.add_child(folium.Element(html))
    return m


# ================================================================
# GENERATE ALL INTERACTIVE MAPS
# ================================================================

def generate_interactive_maps(segments, seg_stats, config: RoadConfig):
    """Generate all interactive Folium maps. Returns dict of filename→filename."""
    maps_dir = config.output_dir / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)
    map_files = {}
    limit = config.speed_limit
    primary_dt = config.day_types[0] if config.day_types else "Feriali"

    configs = [
        ("avg_speed", None,                  "Velocit\u00e0 Media (24h)",    "avg_speed_24h", "mean", 20, 80, False),
        ("p85",       None,                  "V85 (24h)",                    "v85_24h",       "mean", 20, 80, False),
        ("avg_speed", config.night_hours,    "Velocit\u00e0 Media Notturna", "avg_speed_night", "mean", 20, 80, False),
        ("p85",       config.night_hours,    "V85 Notturno",                "v85_night",     "mean", 20, 80, False),
        ("p85",       None,                  "V85 Massimo (ora peggiore)",  "max_v85",       "max",  20, 90, False),
    ]

    dt_slug = primary_dt.lower().replace(" ", "_").replace(".", "")

    # Individual direction maps
    for direction in config.directions:
        dir_slug = direction.lower().replace(" ", "_")
        for vcol, hfilter, label, prefix, agg, vmin, vmax, rev in configs:
            period = "22\u201305" if hfilter is not None else "tutte le ore"
            title = f"{label} \u2014 {primary_dt} Dir. {direction} ({period})"
            fname = f"{prefix}_{dt_slug}_{dir_slug}.html"
            sub = (segments[segments["hour"].isin(hfilter)]
                   if hfilter is not None else segments)
            gdf = _build_speed_gdf(sub, primary_dt, direction, vcol, agg_func=agg)
            if gdf.empty:
                continue
            m = make_folium_map(gdf, vcol, title, vmin, vmax, rev, limit)
            m.save(str(maps_dir / fname))
            map_files[fname] = fname

    # Combined maps (all directions on one map)
    for vcol, hfilter, label, prefix, agg, vmin, vmax, rev in configs:
        period = "22\u201305" if hfilter is not None else "tutte le ore"
        title = f"{label} \u2014 {primary_dt} ({period})"
        fname = f"{prefix}_{dt_slug}_combined.html"
        sub = (segments[segments["hour"].isin(hfilter)]
               if hfilter is not None else segments)
        gdfs = []
        for direction in config.directions:
            gdf = _build_speed_gdf(sub, primary_dt, direction, vcol, agg_func=agg)
            if not gdf.empty:
                gdfs.append((direction, gdf))
        if not gdfs:
            continue
        m = make_folium_map_combined(gdfs, vcol, title, vmin, vmax, rev, limit)
        m.save(str(maps_dir / fname))
        map_files[fname] = fname

    # Secondary day_type V85 maps (if available)
    for dt in config.day_types[1:]:
        dt_s = dt.lower().replace(" ", "_").replace(".", "")
        for direction in config.directions:
            dir_slug = direction.lower().replace(" ", "_")
            title = f"V85 (24h) \u2014 {dt} Dir. {direction}"
            fname = f"v85_24h_{dt_s}_{dir_slug}.html"
            gdf = _build_speed_gdf(segments, dt, direction, "p85", agg_func="mean")
            if gdf.empty:
                continue
            m = make_folium_map(gdf, "p85", title, 20, 80, False, limit)
            m.save(str(maps_dir / fname))
            map_files[fname] = fname

    # Variability maps
    for direction in config.directions:
        dir_slug = direction.lower().replace(" ", "_")
        title = f"Variabilit\u00e0 \u2014 {primary_dt} Dir. {direction}"
        fname = f"std_{dt_slug}_{dir_slug}.html"
        gdf = _build_speed_gdf(segments, primary_dt, direction, "std_speed", agg_func="mean")
        if gdf.empty:
            continue
        m = make_folium_map(gdf, "std_speed", title, 5, 22, True, limit)
        m.save(str(maps_dir / fname))
        map_files[fname] = fname

    # Progressive distance maps
    for direction in config.directions:
        dir_slug = direction.lower().replace(" ", "_")
        sub = segments[(segments["day_type"] == primary_dt)
                       & (segments["direction"] == direction)]
        si = sub.drop_duplicates("seg_idx").sort_values("seg_idx")
        if si.empty:
            continue
        clat = si.geometry.apply(lambda g: g.centroid.y).mean()
        clon = si.geometry.apply(lambda g: g.centroid.x).mean()
        m = folium.Map(location=[clat, clon], zoom_start=15,
                       tiles="CartoDB positron")
        for _, row in si.iterrows():
            coords = [[c[1], c[0]] for c in row["geometry"].coords]
            folium.PolyLine(coords, weight=6, color="#1a237e", opacity=.8).add_to(m)
        _add_folium_progressive(m, si, interval_m=250)
        fname = f"progressive_{dir_slug}.html"
        m.save(str(maps_dir / fname))
        map_files[fname] = fname

    # Top-10 V85 maps
    for direction in config.directions:
        dir_slug = direction.lower().replace(" ", "_")
        sub = segments[(segments["day_type"] == primary_dt)
                       & (segments["direction"] == direction)]
        si = sub.drop_duplicates("seg_idx").sort_values("seg_idx")
        if si.empty:
            continue
        top = seg_stats[
            (seg_stats["day_type"] == primary_dt)
            & (seg_stats["direction"] == direction)
        ].nlargest(10, "max_v85")
        top_set = set(top["seg_idx"].values)
        clat = si.geometry.apply(lambda g: g.centroid.y).mean()
        clon = si.geometry.apply(lambda g: g.centroid.x).mean()
        m = folium.Map(location=[clat, clon], zoom_start=15,
                       tiles="CartoDB positron")
        for _, row in si.iterrows():
            coords = [[c[1], c[0]] for c in row["geometry"].coords]
            is_top = row["seg_idx"] in top_set
            folium.PolyLine(
                coords,
                weight=10 if is_top else 4,
                color="#e41a1c" if is_top else "#aaaaaa",
                opacity=0.9 if is_top else 0.4,
            ).add_to(m)
        for rank, (_, row) in enumerate(top.iterrows(), 1):
            match = si[si["seg_idx"] == row["seg_idx"]]
            if match.empty:
                continue
            c = match.iloc[0]["geometry"].centroid
            folium.Marker(
                [c.y, c.x],
                icon=folium.DivIcon(
                    html=(f'<div style="font-size:11px;background:#e41a1c;color:white;'
                          f'padding:2px 6px;border-radius:50%;text-align:center;'
                          f'width:24px;height:24px;line-height:20px;font-weight:bold;'
                          f'box-shadow:1px 1px 3px rgba(0,0,0,.4);">{rank}</div>'),
                    icon_size=(24, 24), icon_anchor=(12, 12)),
                popup=(f"<b>#{rank}</b><br>Progr.: {row['cum_dist_start']:.0f} m<br>"
                       f"V85 max: {row['max_v85']:.0f} km/h<br>"
                       f"Vel. media: {row['all_avg_speed']:.1f} km/h"),
            ).add_to(m)
        fname = f"top10_v85_{dt_slug}_{dir_slug}.html"
        m.save(str(maps_dir / fname))
        map_files[fname] = fname

    return map_files


# ================================================================
# STATIC MAPS
# ================================================================

def generate_static_speed_map(segments, day_type, direction, value_col,
                               config: RoadConfig,
                               hour_filter=None, title="", fname="map.png",
                               agg_func="mean"):
    static_dir = config.output_dir / "static_maps"
    static_dir.mkdir(parents=True, exist_ok=True)
    limit = config.speed_limit

    gdf = _build_speed_gdf(segments, day_type, direction, value_col,
                            hour_filter, agg_func=agg_func)
    if gdf.empty:
        return None

    fig, ax = plt.subplots(figsize=(10, 12))
    norm = mcolors.TwoSlopeNorm(vmin=20, vcenter=limit, vmax=80)
    cmap = plt.cm.RdYlGn_r

    gdf.plot(ax=ax, color="#d0d0d0", linewidth=9, zorder=1, alpha=0.8)
    gdf.plot(ax=ax, column=value_col, cmap=cmap, norm=norm,
             linewidth=5, legend=False, zorder=2)
    has_tiles = _add_basemap(ax, crs="EPSG:4326")
    if has_tiles:
        ax.set_axis_off()
    else:
        ax.set_xlabel("Longitudine", fontsize=9)
        ax.set_ylabel("Latitudine", fontsize=9)
    _annotate_segments(ax, gdf, value_col)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, shrink=0.5, pad=0.03, aspect=30)
    cbar.set_label("km/h", fontsize=10)
    cbar.ax.axhline(y=limit, color="black", linewidth=1.5, linestyle="--")
    cbar.ax.text(1.3, limit, f"Limite {limit}",
                 transform=cbar.ax.get_yaxis_transform(),
                 va="center", fontsize=8, color="black")
    ax.set_title(title, fontsize=13, fontweight="bold", pad=12)
    fig.tight_layout()

    out_path = static_dir / fname
    fig.savefig(str(out_path), dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(out_path)


def generate_static_speed_map_sidebyside(segments, day_type, directions,
                                          value_col, config: RoadConfig,
                                          hour_filter=None, title="",
                                          fname="map_sidebyside.png",
                                          agg_func="mean"):
    static_dir = config.output_dir / "static_maps"
    static_dir.mkdir(parents=True, exist_ok=True)
    limit = config.speed_limit
    n = len(directions)

    gdfs = []
    for direction in directions:
        gdf = _build_speed_gdf(segments, day_type, direction, value_col,
                                hour_filter, agg_func=agg_func)
        gdfs.append((direction, gdf))

    fig, axes = plt.subplots(1, n, figsize=(10 * n, 12))
    if n == 1:
        axes = [axes]
    norm = mcolors.TwoSlopeNorm(vmin=20, vcenter=limit, vmax=80)
    cmap = plt.cm.RdYlGn_r

    for ax, (dir_label, gdf) in zip(axes, gdfs):
        if gdf.empty:
            continue
        gdf.plot(ax=ax, color="#d0d0d0", linewidth=9, zorder=1, alpha=0.8)
        gdf.plot(ax=ax, column=value_col, cmap=cmap, norm=norm,
                 linewidth=5, legend=False, zorder=2)
        has_tiles = _add_basemap(ax, crs="EPSG:4326")
        _annotate_segments(ax, gdf, value_col)
        if has_tiles:
            ax.set_axis_off()
        ax.set_title(f"Dir. {dir_label}", fontsize=12, fontweight="bold")

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=list(axes), shrink=0.5, pad=0.02, aspect=30)
    cbar.set_label("km/h", fontsize=10)
    cbar.ax.axhline(y=limit, color="black", linewidth=1.5, linestyle="--")
    cbar.ax.text(1.3, limit, f"Limite {limit}",
                 transform=cbar.ax.get_yaxis_transform(),
                 va="center", fontsize=8, color="black")
    fig.suptitle(title, fontsize=14, fontweight="bold", y=1.01)
    fig.tight_layout()

    out_path = static_dir / fname
    fig.savefig(str(out_path), dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(out_path)


def generate_all_static_maps(segments, config: RoadConfig):
    """Generate static maps: individual, side-by-side, and max V85."""
    paths = []
    primary_dt = config.day_types[0] if config.day_types else "Feriali"
    dt_slug = primary_dt.lower().replace(" ", "_").replace(".", "")

    map_configs = [
        ("avg_speed", None,              "Velocit\u00e0 Media (24h)",    "avg_speed_24h", "mean"),
        ("p85",       None,              "V85 (24h)",                    "v85_24h",       "mean"),
        ("avg_speed", config.night_hours, "Velocit\u00e0 Media Notturna", "avg_speed_night", "mean"),
        ("p85",       config.night_hours, "V85 Notturno",                "v85_night",     "mean"),
    ]

    for direction in config.directions:
        dir_slug = direction.lower().replace(" ", "_")
        for vcol, hfilter, label, prefix, agg in map_configs:
            period = "22\u201305" if hfilter is not None else "tutte le ore"
            title = f"{label} \u2014 {primary_dt} Dir. {direction} ({period})"
            fname = f"{prefix}_{dt_slug}_{dir_slug}.png"
            p = generate_static_speed_map(
                segments, primary_dt, direction, vcol, config,
                hour_filter=hfilter, title=title, fname=fname, agg_func=agg)
            if p:
                paths.append(p)
                print(f"  - {fname}")

    for vcol, hfilter, label, prefix, agg in map_configs:
        period = "22\u201305" if hfilter is not None else "tutte le ore"
        title = f"{label} \u2014 {primary_dt} ({period})"
        fname = f"{prefix}_{dt_slug}_sidebyside.png"
        p = generate_static_speed_map_sidebyside(
            segments, primary_dt, config.directions, vcol, config,
            hour_filter=hfilter, title=title, fname=fname, agg_func=agg)
        if p:
            paths.append(p)
            print(f"  - {fname}")

    # Max V85
    for direction in config.directions:
        dir_slug = direction.lower().replace(" ", "_")
        title = f"V85 Massimo (ora peggiore) \u2014 {primary_dt} Dir. {direction}"
        fname = f"max_v85_{dt_slug}_{dir_slug}.png"
        p = generate_static_speed_map(
            segments, primary_dt, direction, "p85", config,
            hour_filter=None, title=title, fname=fname, agg_func="max")
        if p:
            paths.append(p)
            print(f"  - {fname}")

    title = f"V85 Massimo (ora peggiore) \u2014 {primary_dt}"
    fname = f"max_v85_{dt_slug}_sidebyside.png"
    p = generate_static_speed_map_sidebyside(
        segments, primary_dt, config.directions, "p85", config,
        hour_filter=None, title=title, fname=fname, agg_func="max")
    if p:
        paths.append(p)
        print(f"  - {fname}")

    return paths
