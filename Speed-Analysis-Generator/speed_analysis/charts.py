"""Matplotlib chart generation for speed analysis reports."""

import base64
import io

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

from .config import RoadConfig
from .stats import hourly_means, compute_exceedance_by_km

plt.rcParams.update({
    "figure.dpi": 140, "savefig.dpi": 140,
    "font.family": "sans-serif", "font.size": 10,
    "axes.titlesize": 12, "axes.labelsize": 10,
})
HOUR_SHORT = [f"{h}" for h in range(24)]


def fig_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


# -- Temporal profiles --

def chart_speed_by_hour(summaries, config: RoadConfig):
    """Harmonic average speed by hour — one panel per day_type."""
    day_types = config.day_types
    n = len(day_types)
    fig, axes = plt.subplots(1, n, figsize=(7 * n, 5), sharey=True, squeeze=False)
    axes = axes[0]

    for ax, day_type in zip(axes, day_types):
        for direction in config.directions:
            key = (day_type, direction)
            sub = summaries[(summaries["day_type"] == day_type)
                            & (summaries["direction"] == direction)].sort_values("hour")
            ax.plot(sub["hour"], sub["harm_avg_speed"],
                    color=config.colors.get(key, "#333"),
                    label=f"Dir. {direction}", linewidth=2, marker="o", markersize=3)
        ax.set_xlabel("Ora")
        ax.set_title(f"Velocit\u00e0 Media Armonica \u2014 {day_type}")
        ax.set_xticks(range(24))
        ax.set_xticklabels(HOUR_SHORT, fontsize=7)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=.3)
        ax.set_xlim(-.5, 23.5)
    axes[0].set_ylabel("Velocit\u00e0 media armonica (km/h)")
    fig.suptitle("Velocit\u00e0 Media di Percorrenza per Ora", fontsize=13, y=1.02)
    fig.tight_layout()
    return fig_to_base64(fig)


def chart_v85_by_hour(segments, config: RoadConfig):
    """V85 by hour — one panel per day_type."""
    hmeans = hourly_means(segments, "p85")
    day_types = config.day_types
    n = len(day_types)
    fig, axes = plt.subplots(1, n, figsize=(7 * n, 5), sharey=True, squeeze=False)
    axes = axes[0]

    for ax, day_type in zip(axes, day_types):
        for direction in config.directions:
            key = (day_type, direction)
            sub = hmeans[(hmeans["day_type"] == day_type)
                         & (hmeans["direction"] == direction)].sort_values("hour")
            ax.plot(sub["hour"], sub["p85"],
                    color=config.colors.get(key, "#333"),
                    label=f"Dir. {direction}", linewidth=2, marker="o", markersize=3)
        ax.set_xlabel("Ora")
        ax.set_title(f"V85 Medio \u2014 {day_type}")
        ax.set_xticks(range(24))
        ax.set_xticklabels(HOUR_SHORT, fontsize=7)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=.3)
        ax.set_xlim(-.5, 23.5)
    axes[0].set_ylabel("V85 medio dei segmenti (km/h)")
    fig.suptitle("85\u00b0 Percentile della Velocit\u00e0 (V85) per Ora", fontsize=13, y=1.02)
    fig.tight_layout()
    return fig_to_base64(fig)


# -- Heatmaps --

def _make_heatmap_progressive(sub, value_col, title, cmap, norm, fig_ax=None):
    """Heatmap: progressive km (x) vs hour (y)."""
    seg_first = sub.drop_duplicates("seg_idx").sort_values("seg_idx")
    x_edges = np.concatenate([
        seg_first["cum_dist_start"].values,
        [seg_first["cum_dist_end"].values[-1]]
    ]) / 1000.0
    y_edges = np.arange(-0.5, 24.5, 1.0)

    pivot = sub.pivot_table(index="hour", columns="seg_idx",
                             values=value_col, aggfunc="mean")
    pivot = pivot.reindex(index=range(24), columns=seg_first["seg_idx"].values)

    if fig_ax is None:
        fig, ax = plt.subplots(figsize=(12, 7))
    else:
        fig, ax = fig_ax

    mesh = ax.pcolormesh(x_edges, y_edges, pivot.values,
                          cmap=cmap, norm=norm, shading="flat")
    ax.invert_yaxis()
    ax.set_xlabel("Progressiva (km)")
    ax.set_ylabel("Ora")
    ax.set_yticks(range(24))
    ax.set_yticklabels(HOUR_SHORT, fontsize=7)
    max_km = x_edges[-1]
    tick_iv = 0.25 if max_km < 2.0 else (0.5 if max_km < 5.0 else 1.0)
    xticks = np.arange(0, max_km + tick_iv, tick_iv)
    ax.set_xticks(xticks)
    ax.set_xticklabels([f"{x:.2f}" for x in xticks], fontsize=7)
    ax.set_title(title)
    fig.colorbar(mesh, ax=ax, shrink=0.75, label="km/h")
    return fig


def chart_heatmaps(segments, config: RoadConfig):
    """Speed heatmaps for each (day_type, direction) combination."""
    results = {}
    norm = mcolors.TwoSlopeNorm(vmin=15, vcenter=config.speed_limit, vmax=90)
    cmap = plt.cm.RdYlGn

    for dt in config.day_types:
        for dr in config.directions:
            key = (dt, dr)
            sub = segments[(segments["day_type"] == dt)
                           & (segments["direction"] == dr)]
            if sub.empty:
                continue
            label = config.labels.get(key, f"{dt} \u2192 {dr}")
            title = f"Velocit\u00e0 Media per Progressiva e Ora \u2014 {label}"
            fig = _make_heatmap_progressive(sub, "avg_speed", title, cmap, norm)
            results[label] = fig_to_base64(fig)
    return results


# -- Exceedance --

def chart_exceedance(segments, config: RoadConfig):
    """% of route-km exceeding speed limit by hour."""
    limit = config.speed_limit
    exc_avg = compute_exceedance_by_km(segments, "avg_speed", limit)
    exc_v85 = compute_exceedance_by_km(segments, "p85", limit)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    for dt in config.day_types:
        for dr in config.directions:
            key = (dt, dr)
            label = config.labels.get(key, f"{dt} \u2192 {dr}")
            color = config.colors.get(key, "#333")

            sub = exc_avg[(exc_avg["day_type"] == dt)
                          & (exc_avg["direction"] == dr)].sort_values("hour")
            axes[0].plot(sub["hour"], sub["pct_km_exceed"], color=color,
                         label=label, linewidth=2, marker="o", markersize=3)

            sub = exc_v85[(exc_v85["day_type"] == dt)
                          & (exc_v85["direction"] == dr)].sort_values("hour")
            axes[1].plot(sub["hour"], sub["pct_km_exceed"], color=color,
                         label=label, linewidth=2, marker="o", markersize=3)

    axes[0].set_title(f"Km con Velocit\u00e0 Media > {limit} km/h")
    axes[0].set_xlabel("Ora")
    axes[0].set_ylabel("% del percorso (km) oltre il limite")
    axes[0].set_xticks(range(24))
    axes[0].set_xticklabels(HOUR_SHORT, fontsize=7)
    axes[0].legend(fontsize=7)
    axes[0].grid(True, alpha=.3)
    axes[0].set_xlim(-.5, 23.5)
    axes[0].set_ylim(0, 105)

    axes[1].set_title(f"Km con V85 > {limit} km/h")
    axes[1].set_xlabel("Ora")
    axes[1].set_xticks(range(24))
    axes[1].set_xticklabels(HOUR_SHORT, fontsize=7)
    axes[1].legend(fontsize=7)
    axes[1].grid(True, alpha=.3)
    axes[1].set_xlim(-.5, 23.5)

    fig.suptitle("Superamento del Limite (pesato per km)", fontsize=13, y=1.02)
    fig.tight_layout()
    return fig_to_base64(fig)


# -- V85 spatial profiles --

def chart_v85_spatial(segments, config: RoadConfig):
    """V85 along corridor at key time periods, one chart per direction."""
    results = {}
    periods = {
        "Notte (22\u201305)": config.night_hours,
        "Punta mattina (07\u201308)": config.am_peak,
        "Mezzog. (12\u201313)": config.midday,
        "Punta sera (17\u201318)": config.pm_peak,
    }
    pcols = ["#7570b3", "#d95f02", "#1b9e77", "#e7298a"]

    # Use first day_type (typically weekday/Feriali)
    primary_dt = config.day_types[0] if config.day_types else "Feriali"

    for direction in config.directions:
        fig, ax = plt.subplots(figsize=(12, 5))
        sub = segments[(segments["day_type"] == primary_dt)
                       & (segments["direction"] == direction)]
        if sub.empty:
            plt.close(fig)
            continue
        for (pname, phours), pcol in zip(periods.items(), pcols):
            psub = sub[sub["hour"].isin(phours)]
            prof = psub.groupby("seg_idx").agg(
                v85=("p85", "mean"), dist=("cum_dist_mid", "first"),
            ).sort_values("dist")
            ax.plot(prof["dist"] / 1000, prof["v85"], color=pcol,
                    label=pname, linewidth=1.8)
        ax.set_xlabel("Progressiva (km)")
        ax.set_ylabel("V85 (km/h)")
        ax.set_title(f"Profilo Spaziale V85 \u2014 {primary_dt} Dir. {direction}")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=.3)
        results[direction] = fig_to_base64(fig)
    return results


# -- Speed variability --

def chart_speed_variability(segments, config: RoadConfig):
    """Std dev heatmaps + spatial profiles."""
    directions = config.directions
    n = len(directions)
    fig, axes = plt.subplots(2, n, figsize=(7 * n, 10), squeeze=False)
    norm = mcolors.Normalize(vmin=0, vmax=25)
    cmap = plt.cm.YlOrRd
    primary_dt = config.day_types[0] if config.day_types else "Feriali"

    for ci, direction in enumerate(directions):
        sub = segments[(segments["day_type"] == primary_dt)
                       & (segments["direction"] == direction)]
        if sub.empty:
            continue
        _make_heatmap_progressive(
            sub, "std_speed",
            f"Dev. Std. Velocit\u00e0 \u2014 Dir. {direction}",
            cmap, norm, fig_ax=(fig, axes[0, ci]))

        ax2 = axes[1, ci]
        prof = sub.groupby("seg_idx").agg(
            std_mean=("std_speed", "mean"), std_max=("std_speed", "max"),
            dist=("cum_dist_mid", "first"),
        ).sort_values("dist")
        dkm = prof["dist"] / 1000
        ax2.fill_between(dkm, 0, prof["std_max"], alpha=.2, color="orange",
                         label="Max orario")
        ax2.plot(dkm, prof["std_mean"], color="darkorange", lw=2,
                 label="Media giornaliera")
        ax2.set_xlabel("Progressiva (km)")
        ax2.set_ylabel("Dev. Std. (km/h)")
        ax2.set_title(f"Variabilit\u00e0 Spaziale \u2014 Dir. {direction}")
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=.3)

    fig.suptitle(f"Variabilit\u00e0 delle Velocit\u00e0 (Dev. Std.) \u2014 {primary_dt}",
                 fontsize=13, y=1.01)
    fig.tight_layout()
    return fig_to_base64(fig)


# -- Night analysis --

def chart_night_analysis(segments, config: RoadConfig):
    """Night vs day histograms + spatial profiles per direction."""
    directions = config.directions
    n = len(directions)
    fig, axes = plt.subplots(2, n, figsize=(7 * n, 10), squeeze=False)
    primary_dt = config.day_types[0] if config.day_types else "Feriali"
    fer = segments[segments["day_type"] == primary_dt]
    limit = config.speed_limit

    for ci, direction in enumerate(directions):
        sub_dir = fer[fer["direction"] == direction]
        if sub_dir.empty:
            continue
        night = sub_dir[sub_dir["hour"].isin(config.night_hours)]["avg_speed"]
        day = sub_dir[~sub_dir["hour"].isin(config.night_hours)]["avg_speed"]

        ax = axes[0, ci]
        ax.hist(day, bins=40, alpha=.6, color="#1f77b4",
                label="Diurno (06\u201321)", density=True)
        ax.hist(night, bins=40, alpha=.6, color="#9467bd",
                label="Notturno (22\u201305)", density=True)
        ax.axvline(limit, color="red", ls="--", lw=1,
                   label=f"Limite {limit}")
        ax.set_xlabel("Velocit\u00e0 media (km/h)")
        ax.set_ylabel("Densit\u00e0")
        ax.set_title(f"Distribuzione Notte vs Giorno \u2014 Dir. {direction}")
        ax.legend(fontsize=8)

        ax2 = axes[1, ci]
        sub_n = sub_dir[sub_dir["hour"].isin(config.night_hours)]
        prof = sub_n.groupby("seg_idx").agg(
            v85=("p85", "mean"), avg=("avg_speed", "mean"),
            dist=("cum_dist_mid", "first"),
        ).sort_values("dist")
        dkm = prof["dist"] / 1000
        ax2.plot(dkm, prof["v85"], color="#9467bd", lw=2, label="V85 notturno")
        ax2.plot(dkm, prof["avg"], color="#1f77b4", lw=2, label="Vel. media notturna")
        ax2.axhline(limit, color="red", ls="--", lw=1, alpha=.7)
        ax2.set_xlabel("Progressiva (km)")
        ax2.set_ylabel("Velocit\u00e0 (km/h)")
        ax2.set_title(f"Profilo Notturno \u2014 Dir. {direction}")
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=.3)

    fig.suptitle(f"Analisi delle Velocit\u00e0 Notturne ({primary_dt})", fontsize=13, y=1.01)
    fig.tight_layout()
    return fig_to_base64(fig)


# -- Weekday vs weekend --

def chart_weekday_weekend(segments, config: RoadConfig):
    """Compare day_types (e.g. Feriali vs Festivi)."""
    if len(config.day_types) < 2:
        return None

    directions = config.directions
    n = len(directions)
    fig, axes = plt.subplots(2, n, figsize=(7 * n, 10), squeeze=False)
    limit = config.speed_limit
    linestyles = ["-", "--", "-.", ":"]

    for ci, direction in enumerate(directions):
        ax = axes[0, ci]
        for di, dt in enumerate(config.day_types):
            sub = segments[(segments["day_type"] == dt)
                           & (segments["direction"] == direction)]
            hm = sub.groupby("hour")["avg_speed"].mean().reset_index().sort_values("hour")
            color = config.colors.get((dt, direction), "#333")
            ax.plot(hm["hour"], hm["avg_speed"], color=color,
                    ls=linestyles[di % len(linestyles)], lw=2, label=dt,
                    marker="o", markersize=3)
        ax.axhline(limit, color="red", ls="--", lw=1, alpha=.7)
        ax.set_title(f"Velocit\u00e0 Media \u2014 Dir. {direction}")
        ax.set_xlabel("Ora")
        ax.set_ylabel("km/h")
        ax.set_xticks(range(24))
        ax.set_xticklabels(HOUR_SHORT, fontsize=7)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=.3)

        ax2 = axes[1, ci]
        for di, dt in enumerate(config.day_types):
            sub = segments[(segments["day_type"] == dt)
                           & (segments["direction"] == direction)]
            hm = sub.groupby("hour")["p85"].mean().reset_index().sort_values("hour")
            color = config.colors.get((dt, direction), "#333")
            ax2.plot(hm["hour"], hm["p85"], color=color,
                     ls=linestyles[di % len(linestyles)], lw=2, label=dt,
                     marker="o", markersize=3)
        ax2.axhline(limit, color="red", ls="--", lw=1, alpha=.7)
        ax2.set_title(f"V85 \u2014 Dir. {direction}")
        ax2.set_xlabel("Ora")
        ax2.set_ylabel("km/h")
        ax2.set_xticks(range(24))
        ax2.set_xticklabels(HOUR_SHORT, fontsize=7)
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=.3)

    day_types_str = " vs ".join(config.day_types)
    fig.suptitle(f"Confronto {day_types_str}", fontsize=13, y=1.01)
    fig.tight_layout()
    return fig_to_base64(fig)


def generate_all_charts(segments, summaries, config: RoadConfig):
    """Generate all charts and return a dict of base64-encoded PNGs."""
    charts = {}

    print("  - Velocit\u00e0 media per ora")
    charts["speed_by_hour"] = chart_speed_by_hour(summaries, config)

    print("  - V85 per ora")
    charts["v85_by_hour"] = chart_v85_by_hour(segments, config)

    print("  - Mappe di calore (progressive)")
    charts["heatmaps"] = chart_heatmaps(segments, config)

    print("  - Superamento limiti (per km)")
    charts["exceedance"] = chart_exceedance(segments, config)

    print("  - Profili spaziali V85")
    charts["v85_spatial"] = chart_v85_spatial(segments, config)

    print("  - Variabilit\u00e0 velocit\u00e0 (progressive)")
    charts["variability"] = chart_speed_variability(segments, config)

    print("  - Analisi notturna (per direzione)")
    charts["night"] = chart_night_analysis(segments, config)

    if len(config.day_types) >= 2:
        dt_label = "/".join(config.day_types[:2])
        print(f"  - Confronto {dt_label}")
        charts["weekday_weekend"] = chart_weekday_weekend(segments, config)

    return charts
