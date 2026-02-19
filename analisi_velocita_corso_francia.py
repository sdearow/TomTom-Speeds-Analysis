#!/usr/bin/env python3
"""
Analisi della Distribuzione delle Velocità — Corso Francia, Roma
Dati TomTom Speed Profiles — Febbraio 2026

Genera un report HTML completo con grafici e mappe interattive.
"""

# ================================================================
# SECTION 1 — IMPORTS & CONFIGURATION
# ================================================================

import json
import os
import base64
import io
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.lines import Line2D
import folium
from folium.features import GeoJsonPopup, GeoJsonTooltip
import branca.colormap as cm
from shapely.geometry import shape

warnings.filterwarnings("ignore")

# — Paths —
BASE_DIR = Path(__file__).resolve().parent
DATA_FILES = {
    ("Feriali", "Centro"): BASE_DIR / "Corso Francia_Feriali" / "Corso Francia_Dir. Centro_1.geojson",
    ("Feriali", "GRA"):    BASE_DIR / "Corso Francia_Feriali" / "Corso Francia_Dir. GRA_2.geojson",
    ("Festivi", "Centro"): BASE_DIR / "Corso Francia_Festivi" / "Corso Francia_Dir.Centro_1.geojson",
    ("Festivi", "GRA"):    BASE_DIR / "Corso Francia_Festivi" / "Corso Francia_Dir. GRA_2.geojson",
}
OUTPUT_DIR = BASE_DIR / "output"
MAPS_DIR = OUTPUT_DIR / "maps"

# — Analysis parameters —
SPEED_LIMIT = 50          # km/h (posted limit on Corso di Francia)
NIGHT_HOURS = list(range(0, 6)) + [22, 23]  # 22:00–05:59
AM_PEAK = [7, 8]          # 07:00–08:59
PM_PEAK = [17, 18]        # 17:00–18:59
MIDDAY = [12, 13]         # 12:00–13:59

# Percentile indices inside the 19-element speedPercentiles array
# p5=0, p10=1, p15=2, p20=3, p25=4, p30=5, p35=6, p40=7, p45=8,
# p50=9, p55=10, p60=11, p65=12, p70=13, p75=14, p80=15, p85=16, p90=17, p95=18
P85_IDX = 16
P95_IDX = 18
P15_IDX = 2

# — Visual style —
plt.rcParams.update({
    "figure.dpi": 140,
    "savefig.dpi": 140,
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.labelsize": 10,
})

COLORS = {
    ("Feriali", "Centro"): "#1f77b4",
    ("Feriali", "GRA"):    "#ff7f0e",
    ("Festivi", "Centro"): "#2ca02c",
    ("Festivi", "GRA"):    "#d62728",
}
LABELS = {
    ("Feriali", "Centro"): "Feriali → Centro",
    ("Feriali", "GRA"):    "Feriali → GRA",
    ("Festivi", "Centro"): "Festivi → Centro",
    ("Festivi", "GRA"):    "Festivi → GRA",
}

HOUR_SHORT = [f"{h}" for h in range(24)]


# ================================================================
# SECTION 2 — DATA LOADING & PARSING
# ================================================================

def load_geojson(filepath):
    """Load a single GeoJSON file and return parsed dict."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_segments(data, day_type, direction):
    """
    Parse segment-level data from a GeoJSON FeatureCollection.

    Returns
    -------
    seg_df : pd.DataFrame   — one row per (segment, hour)
    sum_df : pd.DataFrame   — one row per hour (route-level summary)
    header : dict            — raw header properties
    """
    features = data["features"]
    header = features[0]["properties"]
    segments = features[1:]

    # --- segment rows ---
    rows = []
    cumul = 0.0
    for idx, feat in enumerate(segments):
        props = feat["properties"]
        geom = shape(feat["geometry"])
        seg_dist = props["distance"]       # metres

        for tr in props["segmentTimeResults"]:
            hour = tr["timeSet"] - 2       # timeSet 2 → hour 0, … 25 → hour 23
            sp = tr["speedPercentiles"]     # 19 values

            rows.append({
                "day_type":       day_type,
                "direction":      direction,
                "seg_idx":        idx,
                "segmentId":      props["segmentId"],
                "streetName":     props["streetName"],
                "frc":            props["frc"],
                "speedLimit":     props["speedLimit"],
                "seg_distance":   seg_dist,
                "cum_dist_start": cumul,
                "cum_dist_mid":   cumul + seg_dist / 2,
                "cum_dist_end":   cumul + seg_dist,
                "hour":           hour,
                "harm_avg_speed": tr["harmonicAverageSpeed"],
                "avg_speed":      tr["averageSpeed"],
                "median_speed":   tr["medianSpeed"],
                "std_speed":      tr["standardDeviationSpeed"],
                "avg_tt":         tr["averageTravelTime"],
                "median_tt":      tr["medianTravelTime"],
                "std_tt":         tr["travelTimeStandardDeviation"],
                "tt_ratio":       tr["travelTimeRatio"],
                "sample_size":    tr["sampleSize"],
                "norm_sample":    tr["normalizedSampleSize"],
                "p5":  sp[0],  "p15": sp[2],  "p25": sp[4],
                "p50": sp[9],  "p75": sp[14], "p85": sp[16],
                "p90": sp[17], "p95": sp[18],
                "geometry":       geom,
            })

        cumul += seg_dist

    # --- route-level summaries ---
    sum_rows = []
    for s in header["summaries"]:
        hour = s["timeSet"] - 2
        ssp = s.get("speedPercentiles", [])
        sum_rows.append({
            "day_type":       day_type,
            "direction":      direction,
            "hour":           hour,
            "route_dist":     s["distance"],
            "harm_avg_speed": s["harmonicAverageSpeed"],
            "avg_tt":         s["averageTravelTime"],
            "median_tt":      s["medianTravelTime"],
            "pti":            s["planningTimeIndex"],
            "route_p85":      ssp[P85_IDX] if len(ssp) > P85_IDX else np.nan,
            "route_p95":      ssp[P95_IDX] if len(ssp) > P95_IDX else np.nan,
        })

    seg_df = pd.DataFrame(rows)
    sum_df = pd.DataFrame(sum_rows)
    return seg_df, sum_df, header


def load_all_data():
    """Load all four GeoJSON files, return combined DataFrames."""
    all_seg, all_sum = [], []
    headers = {}
    for (dt, dr), path in DATA_FILES.items():
        data = load_geojson(path)
        seg_df, sum_df, hdr = parse_segments(data, dt, dr)
        all_seg.append(seg_df)
        all_sum.append(sum_df)
        headers[(dt, dr)] = hdr

    segments = pd.concat(all_seg, ignore_index=True)
    summaries = pd.concat(all_sum, ignore_index=True)
    return segments, summaries, headers


# ================================================================
# SECTION 3 — ANALYSIS FUNCTIONS
# ================================================================

def compute_exceedance(df, speed_col, limit=SPEED_LIMIT):
    """
    For each (day_type, direction, hour), compute the % of segments
    where `speed_col` exceeds `limit`.
    """
    df = df.copy()
    df["exceeds"] = df[speed_col] > limit
    result = (
        df.groupby(["day_type", "direction", "hour"])["exceeds"]
        .mean() * 100
    ).reset_index()
    result.columns = ["day_type", "direction", "hour", "pct_exceed"]
    return result


def hourly_means(df, value_col):
    """Mean of `value_col` per (day_type, direction, hour)."""
    return (
        df.groupby(["day_type", "direction", "hour"])[value_col]
        .mean()
        .reset_index()
    )


def segment_peak_stats(df):
    """
    For each segment, compute summary stats across key periods.
    Returns a DataFrame with one row per (day_type, direction, seg_idx).
    """
    def _agg(sub):
        return pd.Series({
            "night_avg_speed":  sub.loc[sub["hour"].isin(NIGHT_HOURS), "avg_speed"].mean(),
            "night_v85":        sub.loc[sub["hour"].isin(NIGHT_HOURS), "p85"].mean(),
            "am_avg_speed":     sub.loc[sub["hour"].isin(AM_PEAK), "avg_speed"].mean(),
            "am_v85":           sub.loc[sub["hour"].isin(AM_PEAK), "p85"].mean(),
            "pm_avg_speed":     sub.loc[sub["hour"].isin(PM_PEAK), "avg_speed"].mean(),
            "pm_v85":           sub.loc[sub["hour"].isin(PM_PEAK), "p85"].mean(),
            "midday_avg_speed": sub.loc[sub["hour"].isin(MIDDAY), "avg_speed"].mean(),
            "midday_v85":       sub.loc[sub["hour"].isin(MIDDAY), "p85"].mean(),
            "all_avg_speed":    sub["avg_speed"].mean(),
            "all_v85":          sub["p85"].mean(),
            "all_std":          sub["std_speed"].mean(),
            "max_v85":          sub["p85"].max(),
            "max_avg_speed":    sub["avg_speed"].max(),
            "cum_dist_mid":     sub["cum_dist_mid"].iloc[0],
            "seg_distance":     sub["seg_distance"].iloc[0],
            "streetName":       sub["streetName"].iloc[0],
            "speedLimit":       sub["speedLimit"].iloc[0],
        })

    return (
        df.groupby(["day_type", "direction", "seg_idx"])
        .apply(_agg, include_groups=False)
        .reset_index()
    )


# ================================================================
# SECTION 4 — CHART GENERATION
# ================================================================

def fig_to_base64(fig):
    """Convert a matplotlib Figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def chart_speed_by_hour(summaries):
    """Line chart: route-level harmonic average speed by hour."""
    fig, ax = plt.subplots(figsize=(10, 5))
    for key in LABELS:
        sub = summaries[(summaries["day_type"] == key[0]) & (summaries["direction"] == key[1])]
        sub = sub.sort_values("hour")
        ax.plot(sub["hour"], sub["harm_avg_speed"],
                color=COLORS[key], label=LABELS[key], linewidth=2, marker="o", markersize=3)
    ax.axhline(SPEED_LIMIT, color="red", linestyle="--", linewidth=1, alpha=0.7, label=f"Limite {SPEED_LIMIT} km/h")
    ax.set_xlabel("Ora del giorno")
    ax.set_ylabel("Velocità media armonica (km/h)")
    ax.set_title("Velocità Media di Percorrenza per Ora del Giorno")
    ax.set_xticks(range(24))
    ax.set_xticklabels(HOUR_SHORT, fontsize=8)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(-0.5, 23.5)
    return fig_to_base64(fig)


def chart_v85_by_hour(segments):
    """Line chart: average V85 across segments by hour."""
    hmeans = hourly_means(segments, "p85")
    fig, ax = plt.subplots(figsize=(10, 5))
    for key in LABELS:
        sub = hmeans[(hmeans["day_type"] == key[0]) & (hmeans["direction"] == key[1])]
        sub = sub.sort_values("hour")
        ax.plot(sub["hour"], sub["p85"],
                color=COLORS[key], label=LABELS[key], linewidth=2, marker="o", markersize=3)
    ax.axhline(SPEED_LIMIT, color="red", linestyle="--", linewidth=1, alpha=0.7, label=f"Limite {SPEED_LIMIT} km/h")
    ax.set_xlabel("Ora del giorno")
    ax.set_ylabel("V85 medio dei segmenti (km/h)")
    ax.set_title("85° Percentile della Velocità (V85) per Ora del Giorno")
    ax.set_xticks(range(24))
    ax.set_xticklabels(HOUR_SHORT, fontsize=8)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(-0.5, 23.5)
    return fig_to_base64(fig)


def chart_heatmaps(segments):
    """
    Speed heatmaps: hour (y) × segment position (x).
    Returns dict of {label: base64_png}.
    """
    results = {}
    for key in LABELS:
        sub = segments[(segments["day_type"] == key[0]) & (segments["direction"] == key[1])]
        n_segs = sub["seg_idx"].nunique()
        pivot = sub.pivot_table(index="hour", columns="seg_idx", values="avg_speed", aggfunc="mean")
        pivot = pivot.reindex(index=range(24))

        fig, ax = plt.subplots(figsize=(max(10, n_segs * 0.2), 7))
        norm = mcolors.TwoSlopeNorm(vmin=15, vcenter=SPEED_LIMIT, vmax=90)
        cmap = plt.cm.RdYlGn  # red=slow, green=fast
        im = ax.imshow(pivot.values, aspect="auto", cmap=cmap, norm=norm,
                        interpolation="nearest", origin="upper")
        ax.set_xlabel("Segmento (posizione lungo il percorso)")
        ax.set_ylabel("Ora del giorno")
        ax.set_yticks(range(24))
        ax.set_yticklabels(HOUR_SHORT, fontsize=7)
        xtick_step = max(1, n_segs // 15)
        ax.set_xticks(range(0, n_segs, xtick_step))
        ax.set_title(f"Velocità Media per Segmento e Ora — {LABELS[key]}")
        cbar = fig.colorbar(im, ax=ax, shrink=0.8, label="km/h")
        results[LABELS[key]] = fig_to_base64(fig)
    return results


def chart_exceedance(segments):
    """Bar chart: % segments exceeding speed limit by hour."""
    exc_avg = compute_exceedance(segments, "avg_speed")
    exc_v85 = compute_exceedance(segments, "p85")

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    for key in LABELS:
        sub = exc_avg[(exc_avg["day_type"] == key[0]) & (exc_avg["direction"] == key[1])]
        sub = sub.sort_values("hour")
        axes[0].plot(sub["hour"], sub["pct_exceed"],
                     color=COLORS[key], label=LABELS[key], linewidth=2, marker="o", markersize=3)

    axes[0].set_title("Segmenti con Velocità Media > 50 km/h")
    axes[0].set_xlabel("Ora del giorno")
    axes[0].set_ylabel("% segmenti che superano il limite")
    axes[0].set_xticks(range(24))
    axes[0].set_xticklabels(HOUR_SHORT, fontsize=7)
    axes[0].legend(fontsize=7)
    axes[0].grid(True, alpha=0.3)
    axes[0].set_xlim(-0.5, 23.5)
    axes[0].set_ylim(0, 105)

    for key in LABELS:
        sub = exc_v85[(exc_v85["day_type"] == key[0]) & (exc_v85["direction"] == key[1])]
        sub = sub.sort_values("hour")
        axes[1].plot(sub["hour"], sub["pct_exceed"],
                     color=COLORS[key], label=LABELS[key], linewidth=2, marker="o", markersize=3)

    axes[1].set_title("Segmenti con V85 > 50 km/h")
    axes[1].set_xlabel("Ora del giorno")
    axes[1].set_xticks(range(24))
    axes[1].set_xticklabels(HOUR_SHORT, fontsize=7)
    axes[1].legend(fontsize=7)
    axes[1].grid(True, alpha=0.3)
    axes[1].set_xlim(-0.5, 23.5)

    fig.suptitle("Tasso di Superamento del Limite di Velocità per Ora", fontsize=13, y=1.02)
    fig.tight_layout()
    return fig_to_base64(fig)


def chart_v85_spatial(segments):
    """V85 along the corridor at key time periods. One chart per direction."""
    results = {}
    periods = {
        "Notte (22–05)": NIGHT_HOURS,
        "Punta mattina (07–08)": AM_PEAK,
        "Mezzog. (12–13)": MIDDAY,
        "Punta sera (17–18)": PM_PEAK,
    }
    period_colors = ["#7570b3", "#d95f02", "#1b9e77", "#e7298a"]

    for direction in ["Centro", "GRA"]:
        fig, ax = plt.subplots(figsize=(12, 5))
        sub = segments[(segments["day_type"] == "Feriali") & (segments["direction"] == direction)]

        for (pname, phours), pcol in zip(periods.items(), period_colors):
            psub = sub[sub["hour"].isin(phours)]
            profile = psub.groupby("seg_idx").agg(
                v85=("p85", "mean"),
                dist=("cum_dist_mid", "first"),
            ).sort_values("dist")
            ax.plot(profile["dist"], profile["v85"],
                    color=pcol, label=pname, linewidth=1.8)

        ax.axhline(SPEED_LIMIT, color="red", linestyle="--", linewidth=1, alpha=0.7)
        ax.fill_between(ax.get_xlim(), SPEED_LIMIT, 100, alpha=0.05, color="red")
        ax.set_xlabel("Distanza lungo il percorso (m)")
        ax.set_ylabel("V85 (km/h)")
        ax.set_title(f"Profilo Spaziale V85 — Feriali Dir. {direction}")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        results[direction] = fig_to_base64(fig)

    return results


def chart_speed_variability(segments):
    """Heatmap of speed std deviation + spatial profile."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    for col_idx, direction in enumerate(["Centro", "GRA"]):
        sub = segments[(segments["day_type"] == "Feriali") & (segments["direction"] == direction)]
        n_segs = sub["seg_idx"].nunique()

        # Heatmap
        pivot = sub.pivot_table(index="hour", columns="seg_idx", values="std_speed", aggfunc="mean")
        pivot = pivot.reindex(index=range(24))
        ax = axes[0, col_idx]
        im = ax.imshow(pivot.values, aspect="auto", cmap="YlOrRd",
                        vmin=0, vmax=25, interpolation="nearest", origin="upper")
        ax.set_ylabel("Ora")
        ax.set_yticks(range(0, 24, 2))
        ax.set_yticklabels([HOUR_SHORT[h] for h in range(0, 24, 2)], fontsize=7)
        ax.set_xlabel("Segmento")
        ax.set_title(f"Dev. Std. Velocità — Dir. {direction}")
        fig.colorbar(im, ax=ax, shrink=0.7, label="km/h")

        # Spatial profile (average across all hours)
        ax2 = axes[1, col_idx]
        profile = sub.groupby("seg_idx").agg(
            std_mean=("std_speed", "mean"),
            std_max=("std_speed", "max"),
            dist=("cum_dist_mid", "first"),
        ).sort_values("dist")
        ax2.fill_between(profile["dist"], 0, profile["std_max"], alpha=0.2, color="orange", label="Max orario")
        ax2.plot(profile["dist"], profile["std_mean"], color="darkorange", linewidth=2, label="Media giornaliera")
        ax2.set_xlabel("Distanza (m)")
        ax2.set_ylabel("Dev. Std. (km/h)")
        ax2.set_title(f"Variabilità Spaziale — Dir. {direction}")
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=0.3)

    fig.suptitle("Variabilità delle Velocità (Dev. Std.) — Feriali", fontsize=13, y=1.01)
    fig.tight_layout()
    return fig_to_base64(fig)


def chart_night_analysis(segments):
    """Night vs day speed distributions + spatial profile."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # 1. Histogram: night vs day speeds (all directions, Feriali)
    fer = segments[segments["day_type"] == "Feriali"]
    night = fer[fer["hour"].isin(NIGHT_HOURS)]["avg_speed"]
    day = fer[~fer["hour"].isin(NIGHT_HOURS)]["avg_speed"]

    axes[0].hist(day, bins=40, alpha=0.6, color="#1f77b4", label="Diurno (06–21)", density=True)
    axes[0].hist(night, bins=40, alpha=0.6, color="#9467bd", label="Notturno (22–05)", density=True)
    axes[0].axvline(SPEED_LIMIT, color="red", linestyle="--", linewidth=1, label=f"Limite {SPEED_LIMIT}")
    axes[0].set_xlabel("Velocità media (km/h)")
    axes[0].set_ylabel("Densità")
    axes[0].set_title("Distribuzione Velocità: Notte vs Giorno")
    axes[0].legend(fontsize=8)

    # 2. Night V85 spatial profile per direction
    for direction, col in [("Centro", "#1f77b4"), ("GRA", "#ff7f0e")]:
        sub = fer[(fer["direction"] == direction) & (fer["hour"].isin(NIGHT_HOURS))]
        profile = sub.groupby("seg_idx").agg(
            v85=("p85", "mean"), dist=("cum_dist_mid", "first")
        ).sort_values("dist")
        axes[1].plot(profile["dist"], profile["v85"], color=col, linewidth=2, label=f"Dir. {direction}")

    axes[1].axhline(SPEED_LIMIT, color="red", linestyle="--", linewidth=1, alpha=0.7)
    axes[1].set_xlabel("Distanza (m)")
    axes[1].set_ylabel("V85 notturno (km/h)")
    axes[1].set_title("V85 Notturno lungo il Percorso (Feriali)")
    axes[1].legend(fontsize=8)
    axes[1].grid(True, alpha=0.3)

    # 3. Night avg speed spatial profile per direction
    for direction, col in [("Centro", "#1f77b4"), ("GRA", "#ff7f0e")]:
        sub = fer[(fer["direction"] == direction) & (fer["hour"].isin(NIGHT_HOURS))]
        profile = sub.groupby("seg_idx").agg(
            avg=("avg_speed", "mean"), dist=("cum_dist_mid", "first")
        ).sort_values("dist")
        axes[2].plot(profile["dist"], profile["avg"], color=col, linewidth=2, label=f"Dir. {direction}")

    axes[2].axhline(SPEED_LIMIT, color="red", linestyle="--", linewidth=1, alpha=0.7)
    axes[2].set_xlabel("Distanza (m)")
    axes[2].set_ylabel("Velocità media notturna (km/h)")
    axes[2].set_title("Velocità Media Notturna lungo il Percorso (Feriali)")
    axes[2].legend(fontsize=8)
    axes[2].grid(True, alpha=0.3)

    fig.tight_layout()
    return fig_to_base64(fig)


def chart_weekday_weekend(segments):
    """Weekday vs weekend comparison charts."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    for col_idx, direction in enumerate(["Centro", "GRA"]):
        # Row 0: Avg speed by hour
        ax = axes[0, col_idx]
        for dt, ls in [("Feriali", "-"), ("Festivi", "--")]:
            sub = segments[(segments["day_type"] == dt) & (segments["direction"] == direction)]
            hmean = sub.groupby("hour")["avg_speed"].mean().reset_index().sort_values("hour")
            ax.plot(hmean["hour"], hmean["avg_speed"],
                    color=COLORS[(dt, direction)], linestyle=ls, linewidth=2,
                    label=f"{dt}", marker="o", markersize=3)
        ax.axhline(SPEED_LIMIT, color="red", linestyle="--", linewidth=1, alpha=0.7)
        ax.set_title(f"Velocità Media — Dir. {direction}")
        ax.set_xlabel("Ora")
        ax.set_ylabel("km/h")
        ax.set_xticks(range(24))
        ax.set_xticklabels(HOUR_SHORT, fontsize=7)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

        # Row 1: V85 by hour
        ax2 = axes[1, col_idx]
        for dt, ls in [("Feriali", "-"), ("Festivi", "--")]:
            sub = segments[(segments["day_type"] == dt) & (segments["direction"] == direction)]
            hmean = sub.groupby("hour")["p85"].mean().reset_index().sort_values("hour")
            ax2.plot(hmean["hour"], hmean["p85"],
                     color=COLORS[(dt, direction)], linestyle=ls, linewidth=2,
                     label=f"{dt}", marker="o", markersize=3)
        ax2.axhline(SPEED_LIMIT, color="red", linestyle="--", linewidth=1, alpha=0.7)
        ax2.set_title(f"V85 — Dir. {direction}")
        ax2.set_xlabel("Ora")
        ax2.set_ylabel("km/h")
        ax2.set_xticks(range(24))
        ax2.set_xticklabels(HOUR_SHORT, fontsize=7)
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=0.3)

    fig.suptitle("Confronto Feriali vs Festivi", fontsize=13, y=1.01)
    fig.tight_layout()
    return fig_to_base64(fig)


# ================================================================
# SECTION 5 — MAP GENERATION
# ================================================================

def _seg_geodataframe(segments, day_type, direction, value_col, agg="mean"):
    """Build a GeoDataFrame with one row per segment, aggregated across hours."""
    sub = segments[(segments["day_type"] == day_type) & (segments["direction"] == direction)]
    agg_dict = {
        value_col: agg,
        "geometry": "first",
        "cum_dist_mid": "first",
        "streetName": "first",
        "speedLimit": "first",
        "seg_distance": "first",
        "avg_speed": "mean",
        "p85": "mean",
        "std_speed": "mean",
    }
    grouped = sub.groupby("seg_idx").agg(agg_dict).reset_index()
    gdf = gpd.GeoDataFrame(grouped, geometry="geometry", crs="EPSG:4326")
    return gdf


def make_folium_map(gdf, value_col, title, colormap_name="RdYlGn",
                    vmin=None, vmax=None, reverse_cmap=False):
    """Create a Folium map with segments colored by value_col."""
    center_lat = gdf.geometry.centroid.y.mean()
    center_lon = gdf.geometry.centroid.x.mean()
    m = folium.Map(location=[center_lat, center_lon], zoom_start=15, tiles="CartoDB positron")

    vals = gdf[value_col]
    if vmin is None:
        vmin = vals.min()
    if vmax is None:
        vmax = vals.max()

    colormap = cm.LinearColormap(
        colors=["green", "yellow", "red"] if not reverse_cmap else ["red", "yellow", "green"],
        vmin=vmin, vmax=vmax,
        caption=f"{title} (km/h)"
    )

    for _, row in gdf.iterrows():
        coords = list(row.geometry.coords)
        latlngs = [[c[1], c[0]] for c in coords]
        color = colormap(row[value_col])
        popup_html = (
            f"<b>{row['streetName']}</b><br>"
            f"Vel. media: {row['avg_speed']:.1f} km/h<br>"
            f"V85: {row['p85']:.1f} km/h<br>"
            f"Dev. std: {row['std_speed']:.1f} km/h<br>"
            f"Limite: {row['speedLimit']} km/h<br>"
            f"Lungh.: {row['seg_distance']:.0f} m"
        )
        folium.PolyLine(
            latlngs, weight=6, color=color, opacity=0.85,
            popup=folium.Popup(popup_html, max_width=250),
        ).add_to(m)

    colormap.add_to(m)
    return m


def generate_maps(segments):
    """Generate all Folium maps, save to files, return paths."""
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    map_files = {}

    configs = [
        # (filename, day_type, direction, value_col, agg, title, cmap, vmin, vmax, reverse)
        ("v85_feriali_centro.html", "Feriali", "Centro", "p85", "mean",
         "V85 Medio — Feriali Dir. Centro", "RdYlGn", 20, 80, False),
        ("v85_feriali_gra.html", "Feriali", "GRA", "p85", "mean",
         "V85 Medio — Feriali Dir. GRA", "RdYlGn", 20, 80, False),
        ("v85_festivi_centro.html", "Festivi", "Centro", "p85", "mean",
         "V85 Medio — Festivi Dir. Centro", "RdYlGn", 20, 80, False),
        ("v85_festivi_gra.html", "Festivi", "GRA", "p85", "mean",
         "V85 Medio — Festivi Dir. GRA", "RdYlGn", 20, 80, False),
        ("std_feriali_centro.html", "Feriali", "Centro", "std_speed", "mean",
         "Variabilità (Std Dev) — Feriali Dir. Centro", "YlOrRd", 5, 22, True),
        ("std_feriali_gra.html", "Feriali", "GRA", "std_speed", "mean",
         "Variabilità (Std Dev) — Feriali Dir. GRA", "YlOrRd", 5, 22, True),
        # Night speeds: filter night hours first
        ("night_v85_feriali_centro.html", "Feriali", "Centro", "p85", "mean",
         "V85 Notturno — Feriali Dir. Centro", "RdYlGn", 30, 90, False),
        ("night_v85_feriali_gra.html", "Feriali", "GRA", "p85", "mean",
         "V85 Notturno — Feriali Dir. GRA", "RdYlGn", 30, 90, False),
    ]

    for cfg in configs:
        fname, dt, dr, vcol, agg, title, cmap_name, vmin, vmax, rev = cfg

        if "night" in fname:
            sub = segments[segments["hour"].isin(NIGHT_HOURS)]
        else:
            sub = segments

        gdf = _seg_geodataframe(sub, dt, dr, vcol, agg)
        m = make_folium_map(gdf, vcol, title, cmap_name, vmin, vmax, rev)
        path = MAPS_DIR / fname
        m.save(str(path))
        map_files[fname] = str(path)

    return map_files


# ================================================================
# SECTION 6 — HTML REPORT
# ================================================================

def build_summary_tables(segments, summaries, seg_stats):
    """Build summary data for the report."""
    tables = {}

    # Table 1: Route overview
    overview_rows = []
    for key in LABELS:
        dt, dr = key
        sub_sum = summaries[(summaries["day_type"] == dt) & (summaries["direction"] == dr)]
        sub_seg = segments[(segments["day_type"] == dt) & (segments["direction"] == dr)]
        n_segs = sub_seg["seg_idx"].nunique()
        route_dist = sub_sum["route_dist"].iloc[0]
        mean_speed = sub_sum["harm_avg_speed"].mean()
        peak_speed_am = sub_sum[sub_sum["hour"].isin(AM_PEAK)]["harm_avg_speed"].mean()
        peak_speed_pm = sub_sum[sub_sum["hour"].isin(PM_PEAK)]["harm_avg_speed"].mean()
        night_speed = sub_sum[sub_sum["hour"].isin(NIGHT_HOURS)]["harm_avg_speed"].mean()

        overview_rows.append({
            "Percorso": LABELS[key],
            "Distanza (m)": f"{route_dist:.0f}",
            "N. Segmenti": n_segs,
            "Vel. Media 24h (km/h)": f"{mean_speed:.1f}",
            "Vel. Punta AM (km/h)": f"{peak_speed_am:.1f}",
            "Vel. Punta PM (km/h)": f"{peak_speed_pm:.1f}",
            "Vel. Notturna (km/h)": f"{night_speed:.1f}",
        })
    tables["overview"] = pd.DataFrame(overview_rows)

    # Table 2: Speed exceedance summary
    exc_rows = []
    for key in LABELS:
        dt, dr = key
        sub = segments[(segments["day_type"] == dt) & (segments["direction"] == dr)]
        pct_avg_exceed = (sub["avg_speed"] > SPEED_LIMIT).mean() * 100
        pct_v85_exceed = (sub["p85"] > SPEED_LIMIT).mean() * 100
        max_v85 = sub["p85"].max()
        max_avg = sub["avg_speed"].max()
        exc_rows.append({
            "Percorso": LABELS[key],
            "% osserv. Vel.Media > 50": f"{pct_avg_exceed:.1f}%",
            "% osserv. V85 > 50": f"{pct_v85_exceed:.1f}%",
            "V85 massimo (km/h)": f"{max_v85:.0f}",
            "Vel. Media massima (km/h)": f"{max_avg:.1f}",
        })
    tables["exceedance"] = pd.DataFrame(exc_rows)

    # Table 3: Top 5 fastest segments (by max V85) — Feriali Centro
    st = seg_stats[
        (seg_stats["day_type"] == "Feriali") & (seg_stats["direction"] == "Centro")
    ].nlargest(5, "max_v85")
    tables["top_fast_centro"] = st[["seg_idx", "streetName", "max_v85", "all_avg_speed", "all_std", "speedLimit"]].copy()
    tables["top_fast_centro"].columns = ["Seg.", "Via", "V85 Max (km/h)", "Vel. Media (km/h)", "Dev. Std. (km/h)", "Limite"]

    st2 = seg_stats[
        (seg_stats["day_type"] == "Feriali") & (seg_stats["direction"] == "GRA")
    ].nlargest(5, "max_v85")
    tables["top_fast_gra"] = st2[["seg_idx", "streetName", "max_v85", "all_avg_speed", "all_std", "speedLimit"]].copy()
    tables["top_fast_gra"].columns = ["Seg.", "Via", "V85 Max (km/h)", "Vel. Media (km/h)", "Dev. Std. (km/h)", "Limite"]

    return tables


def df_to_html_table(df):
    """Convert a DataFrame to a styled HTML table string."""
    return df.to_html(index=False, classes="data-table", border=0)


def generate_html_report(charts, map_files, tables, segments):
    """Assemble the full HTML report."""

    map_iframes = ""
    map_sections = [
        ("v85_feriali_centro.html", "V85 Medio — Feriali Dir. Centro"),
        ("v85_feriali_gra.html", "V85 Medio — Feriali Dir. GRA"),
        ("v85_festivi_centro.html", "V85 Medio — Festivi Dir. Centro"),
        ("v85_festivi_gra.html", "V85 Medio — Festivi Dir. GRA"),
        ("std_feriali_centro.html", "Variabilità Velocità — Feriali Dir. Centro"),
        ("std_feriali_gra.html", "Variabilità Velocità — Feriali Dir. GRA"),
        ("night_v85_feriali_centro.html", "V85 Notturno — Feriali Dir. Centro"),
        ("night_v85_feriali_gra.html", "V85 Notturno — Feriali Dir. GRA"),
    ]
    for fname, mtitle in map_sections:
        map_iframes += f"""
        <h3>{mtitle}</h3>
        <iframe src="maps/{fname}" width="100%" height="500" frameborder="0"
                style="border:1px solid #ddd; border-radius:4px; margin-bottom:20px;"></iframe>
        """

    # Heatmap images
    heatmap_imgs = ""
    for label, b64 in charts["heatmaps"].items():
        heatmap_imgs += f"""
        <h3>{label}</h3>
        <img src="data:image/png;base64,{b64}" alt="{label}" style="max-width:100%;">
        """

    v85_spatial_imgs = ""
    for direction, b64 in charts["v85_spatial"].items():
        v85_spatial_imgs += f"""
        <h3>Dir. {direction}</h3>
        <img src="data:image/png;base64,{b64}" alt="V85 Spatial {direction}" style="max-width:100%;">
        """

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Analisi Velocità — Corso Francia, Roma</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6; color: #333; background: #f9f9f9;
            max-width: 1200px; margin: 0 auto; padding: 20px;
        }}
        header {{
            background: linear-gradient(135deg, #1a237e, #283593);
            color: white; padding: 40px; border-radius: 8px;
            margin-bottom: 30px; text-align: center;
        }}
        header h1 {{ font-size: 2em; margin-bottom: 8px; }}
        header h2 {{ font-size: 1.3em; font-weight: 300; opacity: 0.9; }}
        header p {{ margin-top: 12px; opacity: 0.8; font-size: 0.95em; }}
        nav {{
            background: white; padding: 20px 30px; border-radius: 8px;
            margin-bottom: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        nav h3 {{ margin-bottom: 10px; color: #1a237e; }}
        nav ol {{ padding-left: 20px; }}
        nav li {{ margin-bottom: 4px; }}
        nav a {{ color: #1565c0; text-decoration: none; }}
        nav a:hover {{ text-decoration: underline; }}
        section {{
            background: white; padding: 30px; border-radius: 8px;
            margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h2 {{ color: #1a237e; border-bottom: 2px solid #e8eaf6; padding-bottom: 8px; margin-bottom: 20px; }}
        h3 {{ color: #283593; margin: 20px 0 10px 0; }}
        img {{ max-width: 100%; height: auto; border-radius: 4px; margin: 10px 0; }}
        .data-table {{
            width: 100%; border-collapse: collapse; margin: 15px 0;
            font-size: 0.9em;
        }}
        .data-table th {{
            background: #1a237e; color: white; padding: 10px 12px;
            text-align: left; font-weight: 600;
        }}
        .data-table td {{ padding: 8px 12px; border-bottom: 1px solid #e0e0e0; }}
        .data-table tr:nth-child(even) {{ background: #f5f5f5; }}
        .data-table tr:hover {{ background: #e8eaf6; }}
        .insight-box {{
            background: #e8f5e9; border-left: 4px solid #4caf50;
            padding: 15px 20px; margin: 15px 0; border-radius: 0 4px 4px 0;
        }}
        .warning-box {{
            background: #fff3e0; border-left: 4px solid #ff9800;
            padding: 15px 20px; margin: 15px 0; border-radius: 0 4px 4px 0;
        }}
        .critical-box {{
            background: #ffebee; border-left: 4px solid #f44336;
            padding: 15px 20px; margin: 15px 0; border-radius: 0 4px 4px 0;
        }}
        .chart-caption {{
            text-align: center; font-style: italic; color: #666;
            font-size: 0.9em; margin-top: -5px; margin-bottom: 20px;
        }}
        footer {{
            text-align: center; padding: 20px; color: #999; font-size: 0.85em;
        }}
    </style>
</head>
<body>

<header>
    <h1>Analisi della Distribuzione delle Velocit&agrave;</h1>
    <h2>Corso Francia &mdash; Roma</h2>
    <p>Dati TomTom Speed Profiles &bull; Periodo: 1–15 Febbraio 2026<br>
       Report generato automaticamente</p>
</header>

<nav>
    <h3>Indice</h3>
    <ol>
        <li><a href="#intro">Introduzione e Metodologia</a></li>
        <li><a href="#overview">Panoramica dei Dati</a></li>
        <li><a href="#temporal">Profili Temporali di Velocit&agrave;</a></li>
        <li><a href="#exceedance">Superamento del Limite di Velocit&agrave;</a></li>
        <li><a href="#v85">Analisi V85 (85&deg; Percentile)</a></li>
        <li><a href="#variability">Variabilit&agrave; delle Velocit&agrave;</a></li>
        <li><a href="#spatial">Profili Spaziali nelle Ore di Punta</a></li>
        <li><a href="#night">Analisi delle Velocit&agrave; Notturne</a></li>
        <li><a href="#comparison">Confronto Feriali vs Festivi</a></li>
        <li><a href="#maps">Mappe Interattive</a></li>
        <li><a href="#conclusions">Conclusioni e Raccomandazioni</a></li>
    </ol>
</nav>

<!-- 1. INTRODUCTION -->
<section id="intro">
    <h2>1. Introduzione e Metodologia</h2>
    <p>Il presente report analizza la distribuzione delle velocit&agrave; veicolari lungo
    <strong>Corso di Francia</strong> a Roma, utilizzando i dati TomTom Speed Profiles relativi
    al periodo <strong>1–15 febbraio 2026</strong>.</p>

    <p>L'analisi si basa su quattro dataset distinti che coprono:</p>
    <ul>
        <li><strong>Giorni Feriali</strong> (luned&igrave;–venerd&igrave;) — Direzione Centro e Direzione GRA</li>
        <li><strong>Giorni Festivi</strong> (sabato–domenica) — Direzione Centro e Direzione GRA</li>
    </ul>

    <p>Le metriche principali analizzate includono:</p>
    <ul>
        <li><strong>Velocit&agrave; media armonica</strong> — rappresentativa della velocit&agrave; di percorrenza</li>
        <li><strong>V85 (85&deg; percentile)</strong> — la velocit&agrave; non superata dall'85% dei veicoli, metrica chiave per la sicurezza stradale</li>
        <li><strong>Deviazione standard</strong> — misura della dispersione delle velocit&agrave;</li>
        <li><strong>Tasso di superamento</strong> — percentuale di segmenti con velocit&agrave; superiore al limite di 50 km/h</li>
    </ul>

    <p>Il limite di velocit&agrave; vigente su Corso di Francia &egrave; di <strong>50 km/h</strong>,
    con alcuni segmenti terminali (Viale Maresciallo Pilsudski) con limite di 40 km/h.</p>
</section>

<!-- 2. OVERVIEW -->
<section id="overview">
    <h2>2. Panoramica dei Dati</h2>
    <p>La tabella seguente riassume le caratteristiche principali di ciascun percorso analizzato.</p>
    {df_to_html_table(tables['overview'])}

    <h3>Riepilogo Superamento Limiti</h3>
    {df_to_html_table(tables['exceedance'])}
</section>

<!-- 3. TEMPORAL PROFILES -->
<section id="temporal">
    <h2>3. Profili Temporali di Velocit&agrave;</h2>

    <h3>Velocit&agrave; Media Armonica per Ora del Giorno</h3>
    <img src="data:image/png;base64,{charts['speed_by_hour']}" alt="Velocità media per ora">
    <p class="chart-caption">Figura 1 — Velocit&agrave; media armonica di percorrenza dell'intero itinerario per ogni ora del giorno.</p>

    <h3>V85 Medio per Ora del Giorno</h3>
    <img src="data:image/png;base64,{charts['v85_by_hour']}" alt="V85 per ora">
    <p class="chart-caption">Figura 2 — 85&deg; percentile della velocit&agrave; mediato su tutti i segmenti per ogni ora.</p>

    <h3>Mappe di Calore: Velocit&agrave; per Segmento e Ora</h3>
    {heatmap_imgs}
    <p class="chart-caption">Figure 3–6 — Mappe di calore della velocit&agrave; media per ciascun segmento (asse x) e ora (asse y).
    Il verde indica velocit&agrave; elevate (flusso libero), il rosso velocit&agrave; ridotte (congestione).</p>
</section>

<!-- 4. EXCEEDANCE -->
<section id="exceedance">
    <h2>4. Superamento del Limite di Velocit&agrave;</h2>
    <img src="data:image/png;base64,{charts['exceedance']}" alt="Tasso di superamento">
    <p class="chart-caption">Figura 7 — Percentuale di segmenti con velocit&agrave; superiore a 50 km/h per ora del giorno.
    Pannello sinistro: velocit&agrave; media; pannello destro: V85.</p>
</section>

<!-- 5. V85 ANALYSIS -->
<section id="v85">
    <h2>5. Analisi V85 (85&deg; Percentile)</h2>
    <p>Il V85 &egrave; la velocit&agrave; non superata dall'85% degli utenti. Viene utilizzato
    come parametro di riferimento per la verifica dell'adeguatezza del limite di velocit&agrave;
    e per la progettazione stradale.</p>

    {v85_spatial_imgs}
    <p class="chart-caption">Figure 8–9 — Profilo spaziale del V85 lungo il percorso nelle diverse fasce orarie (Feriali).</p>

    <h3>Segmenti con V85 pi&ugrave; Elevato — Dir. Centro (Feriali)</h3>
    {df_to_html_table(tables['top_fast_centro'])}

    <h3>Segmenti con V85 pi&ugrave; Elevato — Dir. GRA (Feriali)</h3>
    {df_to_html_table(tables['top_fast_gra'])}
</section>

<!-- 6. VARIABILITY -->
<section id="variability">
    <h2>6. Variabilit&agrave; delle Velocit&agrave;</h2>
    <p>Un'elevata variabilit&agrave; delle velocit&agrave; (deviazione standard) indica segmenti
    dove convivono veicoli a velocit&agrave; molto diverse, condizione che aumenta il rischio
    di incidenti.</p>

    <img src="data:image/png;base64,{charts['variability']}" alt="Variabilità velocità">
    <p class="chart-caption">Figure 10–13 — Mappe di calore (sopra) e profili spaziali (sotto) della deviazione standard
    della velocit&agrave; per le due direzioni (Feriali).</p>
</section>

<!-- 7. SPATIAL PROFILES (V85 already covered) -->
<section id="spatial">
    <h2>7. Profili Spaziali nelle Ore di Punta</h2>
    <p>I profili spaziali del V85 nelle ore di punta sono mostrati nella Sezione 5 sopra.
    In questa sezione si evidenziano le differenze tra le fasce orarie:</p>
    <ul>
        <li><strong>Notte (22–05)</strong>: velocit&agrave; generalmente pi&ugrave; elevate per il minor traffico</li>
        <li><strong>Punta mattina (07–08)</strong>: rallentamenti nella direzione Centro</li>
        <li><strong>Mezzog. (12–13)</strong>: condizioni intermedie</li>
        <li><strong>Punta sera (17–18)</strong>: rallentamenti nella direzione GRA</li>
    </ul>
</section>

<!-- 8. NIGHT ANALYSIS -->
<section id="night">
    <h2>8. Analisi delle Velocit&agrave; Notturne</h2>
    <p>Le ore notturne (22:00–05:59) presentano volumi di traffico ridotti e velocit&agrave;
    tendenzialmente pi&ugrave; elevate. Questa condizione, combinata con la ridotta visibilit&agrave;,
    pu&ograve; rappresentare un fattore di rischio significativo.</p>

    <img src="data:image/png;base64,{charts['night']}" alt="Analisi notturna">
    <p class="chart-caption">Figure 14–16 — Distribuzione delle velocit&agrave; diurne vs notturne (sinistra);
    profilo V85 notturno (centro); profilo velocit&agrave; media notturna (destra).</p>
</section>

<!-- 9. WEEKDAY vs WEEKEND -->
<section id="comparison">
    <h2>9. Confronto Feriali vs Festivi</h2>
    <img src="data:image/png;base64,{charts['weekday_weekend']}" alt="Confronto feriali-festivi">
    <p class="chart-caption">Figure 17–20 — Confronto delle velocit&agrave; medie (sopra) e V85 (sotto)
    tra giorni feriali e festivi per le due direzioni.</p>
</section>

<!-- 10. MAPS -->
<section id="maps">
    <h2>10. Mappe Interattive</h2>
    <p>Le mappe seguenti mostrano la distribuzione spaziale delle velocit&agrave; lungo Corso Francia.
    Cliccare su ciascun segmento per visualizzare le statistiche dettagliate.</p>
    {map_iframes}
</section>

<!-- 11. CONCLUSIONS -->
<section id="conclusions">
    <h2>11. Conclusioni e Raccomandazioni</h2>
    <div class="insight-box">
        <strong>Risultati Principali:</strong>
        <ul>
            <li>L'analisi copre circa 2.2–2.6 km di Corso Francia in entrambe le direzioni</li>
            <li>Il limite di velocit&agrave; di 50 km/h viene frequentemente superato, specialmente nelle ore notturne</li>
            <li>Il V85 supera il limite in una percentuale significativa di segmenti in tutte le fasce orarie</li>
            <li>La direzione GRA e la direzione Centro mostrano profili di velocit&agrave; asimmetrici nelle ore di punta</li>
        </ul>
    </div>
    <div class="warning-box">
        <strong>Aree di Attenzione:</strong>
        <ul>
            <li>I segmenti con elevata variabilit&agrave; di velocit&agrave; richiedono particolare attenzione per la sicurezza</li>
            <li>Le velocit&agrave; notturne significativamente superiori al limite suggeriscono la necessit&agrave; di misure di moderazione del traffico</li>
            <li>I giorni festivi presentano velocit&agrave; generalmente pi&ugrave; elevate rispetto ai feriali</li>
        </ul>
    </div>
    <p><em>Nota: questo report &egrave; stato generato automaticamente a partire dai dati TomTom Speed Profiles.
    Si raccomanda un'interpretazione contestualizzata dei risultati da parte di tecnici qualificati.</em></p>
</section>

<footer>
    <p>Report generato con dati TomTom Speed Profiles &mdash; Corso Francia, Roma &mdash; Febbraio 2026</p>
</footer>

</body>
</html>"""

    return html


# ================================================================
# SECTION 7 — MAIN
# ================================================================

def main():
    print("Caricamento dati...")
    segments, summaries, headers = load_all_data()

    print("Calcolo statistiche per segmento...")
    seg_stats = segment_peak_stats(segments)

    print("Creazione directory output...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MAPS_DIR.mkdir(parents=True, exist_ok=True)

    print("Generazione grafici...")
    charts = {}
    charts["speed_by_hour"] = chart_speed_by_hour(summaries)
    print("  - Velocità media per ora")
    charts["v85_by_hour"] = chart_v85_by_hour(segments)
    print("  - V85 per ora")
    charts["heatmaps"] = chart_heatmaps(segments)
    print("  - Mappe di calore")
    charts["exceedance"] = chart_exceedance(segments)
    print("  - Superamento limiti")
    charts["v85_spatial"] = chart_v85_spatial(segments)
    print("  - Profili spaziali V85")
    charts["variability"] = chart_speed_variability(segments)
    print("  - Variabilità velocità")
    charts["night"] = chart_night_analysis(segments)
    print("  - Analisi notturna")
    charts["weekday_weekend"] = chart_weekday_weekend(segments)
    print("  - Confronto feriali/festivi")

    print("Generazione mappe interattive...")
    map_files = generate_maps(segments)
    print(f"  - {len(map_files)} mappe generate")

    print("Costruzione tabelle di sintesi...")
    tables = build_summary_tables(segments, summaries, seg_stats)

    print("Assemblaggio report HTML...")
    html = generate_html_report(charts, map_files, tables, segments)
    report_path = OUTPUT_DIR / "report_corso_francia.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Also export segment data as CSV for further analysis
    csv_path = OUTPUT_DIR / "dati_segmenti.csv"
    segments.drop(columns=["geometry"]).to_csv(csv_path, index=False)
    print(f"  - Dati CSV esportati: {csv_path}")

    print(f"\nReport completato: {report_path}")
    print(f"Mappe interattive: {MAPS_DIR}")


if __name__ == "__main__":
    main()
