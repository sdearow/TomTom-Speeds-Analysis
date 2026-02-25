"""Statistics and aggregation functions for speed analysis."""

import numpy as np
import pandas as pd

from .config import RoadConfig


def hourly_means(df, value_col):
    """Mean of value_col per (day_type, direction, hour)."""
    return df.groupby(["day_type", "direction", "hour"])[value_col].mean().reset_index()


def compute_exceedance_by_km(df, speed_col, limit):
    """% of route-km where speed_col > limit, weighted by seg_distance."""
    df = df.copy()
    df["exceed_dist"] = np.where(df[speed_col] > limit, df["seg_distance"], 0.0)
    grp = df.groupby(["day_type", "direction", "hour"]).agg(
        exceed_m=("exceed_dist", "sum"), total_m=("seg_distance", "sum"),
    ).reset_index()
    grp["pct_km_exceed"] = grp["exceed_m"] / grp["total_m"] * 100
    return grp[["day_type", "direction", "hour", "pct_km_exceed"]]


def segment_peak_stats(df, config: RoadConfig):
    """Aggregate per-segment statistics across time periods."""
    nh = config.night_hours
    am = config.am_peak
    pm = config.pm_peak

    def _agg(sub):
        return pd.Series({
            "night_avg_speed": sub.loc[sub["hour"].isin(nh), "avg_speed"].mean(),
            "night_v85":       sub.loc[sub["hour"].isin(nh), "p85"].mean(),
            "am_avg_speed":    sub.loc[sub["hour"].isin(am), "avg_speed"].mean(),
            "am_v85":          sub.loc[sub["hour"].isin(am), "p85"].mean(),
            "pm_avg_speed":    sub.loc[sub["hour"].isin(pm), "avg_speed"].mean(),
            "pm_v85":          sub.loc[sub["hour"].isin(pm), "p85"].mean(),
            "all_avg_speed":   sub["avg_speed"].mean(),
            "all_v85":         sub["p85"].mean(),
            "all_std":         sub["std_speed"].mean(),
            "max_v85":         sub["p85"].max(),
            "max_avg_speed":   sub["avg_speed"].max(),
            "cum_dist_mid":    sub["cum_dist_mid"].iloc[0],
            "cum_dist_start":  sub["cum_dist_start"].iloc[0],
            "seg_distance":    sub["seg_distance"].iloc[0],
            "streetName":      sub["streetName"].iloc[0],
            "speedLimit":      sub["speedLimit"].iloc[0],
        })

    return df.groupby(["day_type", "direction", "seg_idx"]).apply(
        _agg, include_groups=False
    ).reset_index()
