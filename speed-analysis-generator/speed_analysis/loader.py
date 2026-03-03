"""GeoJSON loading and DataFrame construction for TomTom Speed Profiles."""

import json

import numpy as np
import pandas as pd
from shapely.geometry import shape

from .config import RoadConfig

P85_IDX = 16
P95_IDX = 18


def _load_geojson(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_segments(data, direction, day_type, config: RoadConfig,
                    carriage="", tratto=""):
    """Parse a single GeoJSON file into (segments_df, summaries_df, header).

    Handles both single-dateRange and multi-dateRange files.
    """
    features = data["features"]
    header = features[0]["properties"]
    segments = features[1:]

    rows = []
    cumul = 0.0
    for idx, feat in enumerate(segments):
        props = feat["properties"]
        geom = shape(feat["geometry"])
        seg_dist = props["distance"]
        for tr in props["segmentTimeResults"]:
            hour = tr["timeSet"] - config.timeset_offset
            # Determine day_type for this row
            if config.multi_daterange:
                dt = config.daterange_map.get(
                    tr["dateRange"], f"DR{tr['dateRange']}")
            else:
                dt = day_type

            sp = tr["speedPercentiles"]
            row = {
                "day_type": dt,
                "direction": direction,
                "seg_idx": idx,
                "segmentId": props["segmentId"],
                "streetName": props.get("streetName", config.road_name),
                "frc": props["frc"],
                "speedLimit": props["speedLimit"],
                "seg_distance": seg_dist,
                "cum_dist_start": cumul,
                "cum_dist_mid": cumul + seg_dist / 2,
                "cum_dist_end": cumul + seg_dist,
                "hour": hour,
                "harm_avg_speed": tr["harmonicAverageSpeed"],
                "avg_speed": tr["averageSpeed"],
                "median_speed": tr["medianSpeed"],
                "std_speed": tr.get("standardDeviationSpeed", np.nan),
                "avg_tt": tr["averageTravelTime"],
                "median_tt": tr["medianTravelTime"],
                "std_tt": tr.get("travelTimeStandardDeviation", np.nan),
                "tt_ratio": tr["travelTimeRatio"],
                "sample_size": tr["sampleSize"],
                "norm_sample": tr["normalizedSampleSize"],
                "p5": sp[0], "p15": sp[2], "p25": sp[4], "p50": sp[9],
                "p75": sp[14], "p85": sp[P85_IDX],
                "p90": sp[17], "p95": sp[P95_IDX],
                "geometry": geom,
            }
            if carriage:
                row["carriage"] = carriage
            if tratto:
                row["tratto"] = tratto
            rows.append(row)
        cumul += seg_dist

    # Route-level summaries
    sum_rows = []
    for s in header.get("summaries", []):
        hour = s["timeSet"] - config.timeset_offset
        if config.multi_daterange:
            dt = config.daterange_map.get(
                s["dateRange"], f"DR{s['dateRange']}")
        else:
            dt = day_type

        ssp = s.get("speedPercentiles", [])
        sr = {
            "day_type": dt,
            "direction": direction,
            "hour": hour,
            "route_dist": s["distance"],
            "harm_avg_speed": s["harmonicAverageSpeed"],
            "avg_tt": s["averageTravelTime"],
            "median_tt": s["medianTravelTime"],
            "pti": s["planningTimeIndex"],
            "route_p85": ssp[P85_IDX] if len(ssp) > P85_IDX else np.nan,
            "route_p95": ssp[P95_IDX] if len(ssp) > P95_IDX else np.nan,
        }
        if carriage:
            sr["carriage"] = carriage
        sum_rows.append(sr)

    return pd.DataFrame(rows), pd.DataFrame(sum_rows), header


def load_all_data(config: RoadConfig):
    """Load all GeoJSON files according to config.

    Returns (segments_df, summaries_df, headers_dict).
    """
    all_seg, all_sum = [], []
    headers = {}

    for fe in config.files:
        data = _load_geojson(fe.path)
        seg_df, sum_df, hdr = _parse_segments(
            data, fe.direction, fe.day_type, config,
            carriage=fe.carriage, tratto=fe.tratto,
        )
        all_seg.append(seg_df)
        all_sum.append(sum_df)
        headers[(fe.day_type, fe.direction)] = hdr

    segments = pd.concat(all_seg, ignore_index=True)
    summaries = pd.concat(all_sum, ignore_index=True)

    # For carriage-based roads with tratti, fix cumulative distances
    if config.has_carriages:
        segments = _fix_lateral_distances(segments, config)

    return segments, summaries, headers


def _fix_lateral_distances(segments, config: RoadConfig):
    """For multi-carriage roads, ensure progressive distance is continuous
    across concatenated tratti within each carriage."""
    for carriage, info in config.carriages.items():
        tratti = info.get("tratti", [])
        if len(tratti) <= 1:
            continue

        cumul_offset = 0.0
        idx_offset = 0
        for tratto in tratti:
            mask = ((segments.get("carriage", "") == carriage) &
                    (segments.get("tratto", "") == tratto))
            if hasattr(mask, "sum") and mask.sum() == 0:
                continue

            segments.loc[mask, "cum_dist_start"] += cumul_offset
            segments.loc[mask, "cum_dist_mid"] += cumul_offset
            segments.loc[mask, "cum_dist_end"] += cumul_offset

            max_end = segments.loc[mask, "cum_dist_end"].max()
            cumul_offset = max_end

            # Fix seg_idx to be continuous
            current_max = segments.loc[mask, "seg_idx"].max()
            segments.loc[mask, "seg_idx"] += idx_offset
            idx_offset += current_max + 1

    return segments
