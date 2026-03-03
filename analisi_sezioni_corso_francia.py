#!/usr/bin/env python3
"""
Analisi Velocità per Sezioni — Corso Francia Dir. GRA
Genera grafici velocità media armonica + V85 per 3 sezioni e mappa interattiva.
"""

import json
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import folium

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output_sezioni")
os.makedirs(OUTPUT_DIR, exist_ok=True)

FILES = {
    "Feriali": os.path.join(BASE_DIR, "Corso Francia_Feriali", "Corso Francia_Dir. GRA_2.geojson"),
    "Festivi": os.path.join(BASE_DIR, "Corso Francia_Festivi", "Corso Francia_Dir. GRA_2.geojson"),
}

# Sezioni definite per progressiva (km). Includiamo gli archi TomTom che si
# sovrappongono anche parzialmente alla finestra indicata.
SECTIONS = {
    "Sezione A (prog. 1.2–1.3 km)": {"km_start": 1.200, "km_end": 1.300},
    "Sezione B (prog. 1.5–1.6 km)": {"km_start": 1.500, "km_end": 1.600},
    "Sezione C (prog. ~2.2 km)":    {"km_start": 2.100, "km_end": 2.230},
}

P85_IDX = 16  # index inside speedPercentiles array


# ── helpers ────────────────────────────────────────────────────────────────

def load_geojson(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_segments(data):
    """Return list of dicts with per-hour speed data and cumulative distance."""
    features = data["features"]
    segments = features[1:]  # first feature is the header
    results = []
    cumul = 0.0
    for feat in segments:
        props = feat["properties"]
        dist = props["distance"]
        seg_info = {
            "segmentId": props["segmentId"],
            "streetName": props.get("streetName", ""),
            "distance": dist,
            "cum_start": cumul,
            "cum_end": cumul + dist,
            "coords": feat["geometry"]["coordinates"],
            "hours": {},
        }
        for tr in props["segmentTimeResults"]:
            hour = tr["timeSet"] - 2  # UTC+2 → local
            sp = tr["speedPercentiles"]
            seg_info["hours"][hour] = {
                "harm_avg": tr["harmonicAverageSpeed"],
                "p85": sp[P85_IDX] if len(sp) > P85_IDX else None,
            }
        results.append(seg_info)
        cumul += dist
    return results


def select_segments(segments, km_start, km_end):
    """Select segments that overlap with [km_start, km_end] (in km)."""
    start_m = km_start * 1000
    end_m = km_end * 1000
    selected = []
    for seg in segments:
        # overlap check
        if seg["cum_end"] > start_m and seg["cum_start"] < end_m:
            selected.append(seg)
    return selected


def compute_section_speeds(selected_segments):
    """
    Compute distance-weighted harmonic average and distance-weighted V85
    for each hour across the selected segments.

    Harmonic average (weighted): total_dist / sum(dist_i / speed_i)
    V85 (weighted): sum(dist_i * v85_i) / total_dist
    """
    hours_data = {}  # hour -> {"harm_avg": ..., "p85": ...}
    for h in range(24):
        total_dist = 0
        sum_time = 0      # sum(dist / speed) for harmonic avg
        sum_v85_w = 0     # sum(dist * v85) for weighted v85
        valid = True
        for seg in selected_segments:
            d = seg["distance"]
            hdata = seg["hours"].get(h)
            if hdata is None or hdata["harm_avg"] is None or hdata["harm_avg"] <= 0:
                valid = False
                break
            total_dist += d
            sum_time += d / hdata["harm_avg"]
            sum_v85_w += d * (hdata["p85"] if hdata["p85"] else 0)
        if valid and total_dist > 0:
            hours_data[h] = {
                "harm_avg": total_dist / sum_time,
                "p85": sum_v85_w / total_dist,
            }
        else:
            hours_data[h] = {"harm_avg": None, "p85": None}
    return hours_data


def make_chart(section_name, feriali_speeds, festivi_speeds, output_path):
    """
    Create a chart with 2 subplots (Feriali / Festivi).
    Each subplot has 2 curves: harmonic average and V85.
    """
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5), sharey=True)
    fig.suptitle(f"Corso Francia Dir. GRA — {section_name}", fontsize=13, fontweight="bold")

    for ax, (day_label, speeds, color_avg, color_85) in zip(
        axes,
        [
            ("Giorno Feriale", feriali_speeds, "#1f77b4", "#ff7f0e"),
            ("Giorno Festivo", festivi_speeds, "#2ca02c", "#d62728"),
        ],
    ):
        hours = list(range(24))
        harm = [speeds[h]["harm_avg"] for h in hours]
        v85  = [speeds[h]["p85"] for h in hours]

        ax.plot(hours, harm, marker="o", markersize=4, linewidth=2,
                color=color_avg, label="Media armonica")
        ax.plot(hours, v85,  marker="s", markersize=4, linewidth=2,
                color=color_85, label="V85")

        # speed limit reference
        ax.axhline(y=50, color="red", linestyle="--", linewidth=1, alpha=0.6, label="Limite 50 km/h")

        ax.set_title(day_label, fontsize=11)
        ax.set_xlabel("Ora del giorno")
        ax.set_xticks(hours)
        ax.set_xticklabels([f"{h}" for h in hours], fontsize=7)
        ax.set_xlim(-0.5, 23.5)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8, loc="lower left")

    axes[0].set_ylabel("Velocità (km/h)")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Grafico salvato: {output_path}")


def make_map(all_section_segments, output_path):
    """Create a folium map showing the three sections with different colors."""
    colors = ["blue", "green", "red"]
    section_names = list(all_section_segments.keys())

    # Compute center from all coordinates
    all_lats, all_lons = [], []
    for segs in all_section_segments.values():
        for seg in segs:
            for coord in seg["coords"]:
                lon, lat = coord[0], coord[1]
                all_lats.append(lat)
                all_lons.append(lon)

    center_lat = np.mean(all_lats)
    center_lon = np.mean(all_lons)

    m = folium.Map(location=[center_lat, center_lon], zoom_start=15,
                   tiles="CartoDB positron")

    for i, (sec_name, segs) in enumerate(all_section_segments.items()):
        color = colors[i % len(colors)]
        fg = folium.FeatureGroup(name=sec_name)
        for seg in segs:
            coords_latlon = [[c[1], c[0]] for c in seg["coords"]]
            folium.PolyLine(
                coords_latlon,
                color=color,
                weight=6,
                opacity=0.8,
                popup=f"{sec_name}<br>Arco: {seg['segmentId']}<br>"
                      f"Via: {seg['streetName']}<br>"
                      f"Lunghezza: {seg['distance']:.0f} m<br>"
                      f"Prog.: {seg['cum_start']/1000:.3f} – {seg['cum_end']/1000:.3f} km",
            ).add_to(fg)

        # Add label marker at midpoint of section
        mid_seg = segs[len(segs) // 2]
        mid_coord = mid_seg["coords"][len(mid_seg["coords"]) // 2]
        folium.Marker(
            [mid_coord[1], mid_coord[0]],
            icon=folium.DivIcon(html=f'<div style="font-size:11px;font-weight:bold;color:{color};'
                                     f'background:white;padding:2px 6px;border:2px solid {color};'
                                     f'border-radius:4px;white-space:nowrap;">{sec_name}</div>'),
        ).add_to(fg)
        fg.add_to(m)

    folium.LayerControl().add_to(m)
    m.save(output_path)
    print(f"  Mappa salvata: {output_path}")


# ── main ───────────────────────────────────────────────────────────────────

def main():
    print("Caricamento dati GeoJSON...")
    all_segments = {}
    for day_type, path in FILES.items():
        data = load_geojson(path)
        all_segments[day_type] = parse_segments(data)
        print(f"  {day_type}: {len(all_segments[day_type])} archi caricati")

    map_section_segs = {}  # for the map

    for sec_name, sec_def in SECTIONS.items():
        print(f"\n{'='*60}")
        print(f"  {sec_name}")
        print(f"{'='*60}")

        speeds_by_day = {}
        for day_type in ["Feriali", "Festivi"]:
            selected = select_segments(all_segments[day_type],
                                       sec_def["km_start"], sec_def["km_end"])
            print(f"\n  {day_type} — archi selezionati:")
            for seg in selected:
                print(f"    id={seg['segmentId']}  {seg['streetName']}  "
                      f"{seg['cum_start']/1000:.3f}–{seg['cum_end']/1000:.3f} km  "
                      f"({seg['distance']:.0f} m)")
            speeds_by_day[day_type] = compute_section_speeds(selected)

            # Save for map (use feriali segments as reference)
            if day_type == "Feriali":
                map_section_segs[sec_name] = selected

        # Generate chart
        safe_name = sec_name.replace(" ", "_").replace("(", "").replace(")", "").replace(".", "").replace("–", "-").replace("~", "")
        chart_path = os.path.join(OUTPUT_DIR, f"velocita_{safe_name}.png")
        make_chart(sec_name, speeds_by_day["Feriali"], speeds_by_day["Festivi"], chart_path)

    # Generate map
    print(f"\n{'='*60}")
    print("  Generazione mappa...")
    print(f"{'='*60}")
    map_path = os.path.join(OUTPUT_DIR, "mappa_sezioni.html")
    make_map(map_section_segs, map_path)

    print(f"\nTutti gli output salvati in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
