"""Auto-detection and configuration for TomTom Speed Profiles analysis."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Default colour palette (tab10)
_PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf",
]


@dataclass
class FileEntry:
    path: Path
    direction: str
    day_type: str  # folder-derived day_type (for single-dateRange files)
    carriage: str = ""
    tratto: str = ""


@dataclass
class RoadConfig:
    road_name: str
    data_path: Path
    output_dir: Path

    files: list = field(default_factory=list)
    directions: list = field(default_factory=list)
    day_types: list = field(default_factory=list)
    speed_limit: int = 50

    # timeSet → hour conversion
    timeset_offset: int = 2

    # Multi-dateRange mode (e.g. Via Colombo: 4 seasons per file)
    multi_daterange: bool = False
    daterange_map: dict = field(default_factory=dict)

    # Time periods
    night_hours: list = field(default_factory=lambda: list(range(0, 6)) + [22, 23])
    am_peak: list = field(default_factory=lambda: [7, 8])
    pm_peak: list = field(default_factory=lambda: [17, 18])
    midday: list = field(default_factory=lambda: [12, 13])

    # Carriages (for multi-carriage roads like Via Colombo)
    carriages: dict = field(default_factory=dict)
    has_carriages: bool = False

    # Auto-generated colors and labels
    colors: dict = field(default_factory=dict)
    labels: dict = field(default_factory=dict)

    # Date period description
    date_description: str = ""

    # Percentile indices
    p85_idx: int = 16
    p95_idx: int = 18


def _parse_filename(filename: str):
    """Extract direction, carriage, and tratto from a TomTom GeoJSON filename.

    Handles patterns like:
      - "Corso Francia_Dir. Centro_1.geojson"
      - "Centrale_Dir. Ostia_1.geojson"
      - "Laterale_Dir. Ostia_Tratto Pontina-Mezzocammino_3.geojson"
      - "Laterale_Dir. Centro_Svincolo Via di Malafede_6.geojson"
    """
    stem = Path(filename).stem

    # Try to find direction: "Dir. XXX" or "Dir.XXX"
    dir_match = re.search(r"Dir\.?\s*([^_]+)", stem)
    direction = dir_match.group(1).strip() if dir_match else ""

    # Try to find tratto: "Tratto XXX" or anything after direction that's not a number
    tratto = ""
    tratto_match = re.search(r"Tratto\s+([^_]+)", stem)
    if tratto_match:
        tratto = tratto_match.group(1).strip()
    else:
        # Check for non-standard sub-sections (e.g. "Svincolo Via di Malafede")
        if dir_match:
            after_dir = stem[dir_match.end():]
            # Remove trailing _N (file index)
            after_dir = re.sub(r"_\d+$", "", after_dir).strip("_ ")
            if after_dir and not after_dir.isdigit():
                tratto = after_dir

    # Try to find carriage: known patterns before "Dir."
    carriage = ""
    if dir_match:
        before_dir = stem[:dir_match.start()].strip("_ ")
        # Check for carriage indicators
        lower = before_dir.lower()
        if "centrale" in lower or "laterale" in lower or "lat" in lower:
            carriage = before_dir

    return direction, carriage, tratto


def _detect_timeset_offset(header: dict) -> int:
    """Detect timeSet offset from the header's timeSets or summaries."""
    time_sets = header.get("timeSets", [])
    if time_sets:
        min_id = min(ts.get("@id", ts.get("id", 999)) for ts in time_sets)
        return min_id

    summaries = header.get("summaries", [])
    if summaries:
        min_ts = min(s["timeSet"] for s in summaries)
        return min_ts

    return 2  # default


def _clean_daterange_name(name: str) -> str:
    """Remove common road-name prefixes from dateRange name.

    e.g. 'Cristoforo Colombo_Invernale_Feriale' → 'Invernale Feriale'
    """
    # Split on underscore, remove parts that look like road name components
    parts = name.split("_")
    if len(parts) <= 1:
        return name
    # Heuristic: the last 1-2 parts are the day type, the first parts are road name
    # Try to detect where the road name ends by looking for common day-type keywords
    day_keywords = {"feriale", "festivo", "festiva", "feriali", "festivi",
                    "invernale", "estiva", "estivo", "primaverile", "autunnale",
                    "weekend", "weekday", "winter", "summer"}
    first_dt_idx = None
    for i, part in enumerate(parts):
        if part.lower().strip() in day_keywords:
            first_dt_idx = i
            break
    if first_dt_idx is not None and first_dt_idx > 0:
        return " ".join(parts[first_dt_idx:])
    return name


def _detect_day_type_from_daterange(dr: dict) -> str:
    """Infer a human-readable day_type from a dateRange entry."""
    name = dr.get("name", "")
    if name:
        return _clean_daterange_name(name)

    excluded = set(dr.get("excludedDaysOfWeek", []))
    weekend = {"SATURDAY", "SUNDAY"}
    weekdays = {"MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"}

    if excluded == weekend:
        return "Feriali"
    elif excluded == weekdays:
        return "Festivi"
    elif excluded:
        return f"Custom ({','.join(sorted(excluded)[:2])}...)"
    return "Tutti"


def _detect_date_description(header: dict) -> str:
    """Build a date period description from dateRanges."""
    drs = header.get("dateRanges", [])
    if not drs:
        return ""
    dates = []
    for dr in drs:
        f, t = dr.get("from", ""), dr.get("to", "")
        if f and t:
            dates.append((f, t))
    if not dates:
        return ""
    min_date = min(d[0] for d in dates)
    max_date = max(d[1] for d in dates)
    return f"{min_date} / {max_date}"


def _assign_colors(day_types, directions):
    """Auto-assign colors for (day_type, direction) combinations."""
    colors = {}
    labels = {}
    idx = 0
    for dt in day_types:
        for dr in directions:
            colors[(dt, dr)] = _PALETTE[idx % len(_PALETTE)]
            labels[(dt, dr)] = f"{dt} \u2192 {dr}"
            idx += 1
    return colors, labels


def auto_detect(data_path: str, output_dir: str = None) -> RoadConfig:
    """Scan a folder of TomTom GeoJSON files and auto-detect configuration.

    Handles two modes:
    1. Simple: files in day-type subfolders (e.g. Feriali/, Festivi/)
       Each file has 1 dateRange.
    2. Multi-dateRange: files in a single folder, each with N dateRanges.
    """
    data_path = Path(data_path).resolve()
    if output_dir:
        out = Path(output_dir).resolve()
    else:
        out = data_path / "output"

    # Follow symlinks when scanning
    geojson_files = sorted(data_path.rglob("*.geojson"))
    if not geojson_files:
        # Fallback: try with glob on resolved path
        geojson_files = sorted(
            p.resolve() for p in data_path.rglob("*")
            if p.suffix.lower() == ".geojson"
        )
    if not geojson_files:
        raise FileNotFoundError(f"No .geojson files found in {data_path}")

    # Read all headers
    file_infos = []
    road_name = ""
    first_header = None
    all_speed_limits = []

    for gf in geojson_files:
        with open(gf, "r", encoding="utf-8") as fp:
            data = json.load(fp)

        header = data["features"][0]["properties"]
        if first_header is None:
            first_header = header

        # Road name — prefer streetName from first segment (cleaner),
        # fallback to routeName from header
        if not road_name:
            # Try streetName from first real segment
            if len(data["features"]) > 1:
                sn = data["features"][1]["properties"].get("streetName", "")
                if sn:
                    road_name = sn
            if not road_name:
                rn = header.get("routeName", "")
                if rn:
                    # Clean direction patterns from routeName
                    road_name = re.sub(r"_Dir\.?\s*\w+", "", rn).strip("_ ")

        # Parse filename
        direction, carriage, tratto = _parse_filename(gf.name)

        # Collect speed limits from segments
        for feat in data["features"][1:]:
            sl = feat["properties"].get("speedLimit", 0)
            dist = feat["properties"].get("distance", 0)
            if sl > 0:
                all_speed_limits.append((sl, dist))

        # Determine day_type from folder or dateRanges
        date_ranges = header.get("dateRanges", [])
        multi_dr = len(date_ranges) > 1

        # Folder-based day_type (for single-dateRange files)
        folder_name = gf.parent.name
        if not multi_dr and folder_name != data_path.name:
            # Check if folder name contains day-type info
            fl = folder_name.lower()
            if "ferial" in fl:
                folder_day_type = "Feriali"
            elif "festiv" in fl:
                folder_day_type = "Festivi"
            else:
                folder_day_type = folder_name
        elif not multi_dr and date_ranges:
            folder_day_type = _detect_day_type_from_daterange(date_ranges[0])
        else:
            folder_day_type = ""

        file_infos.append({
            "path": gf,
            "direction": direction,
            "carriage": carriage,
            "tratto": tratto,
            "day_type": folder_day_type,
            "header": header,
            "multi_dr": multi_dr,
            "date_ranges": date_ranges,
        })

    # Detect timeSet offset
    timeset_offset = _detect_timeset_offset(first_header)

    # Detect multi-dateRange mode
    multi_daterange = any(fi["multi_dr"] for fi in file_infos)

    # Build daterange_map for multi-dateRange mode
    daterange_map = {}
    if multi_daterange:
        for fi in file_infos:
            for dr in fi["date_ranges"]:
                dr_id = dr.get("@id", dr.get("id"))
                if dr_id is not None and dr_id not in daterange_map:
                    daterange_map[dr_id] = _detect_day_type_from_daterange(dr)

    # Detect speed limit (weighted mode)
    if all_speed_limits:
        limit_totals = {}
        for sl, dist in all_speed_limits:
            limit_totals[sl] = limit_totals.get(sl, 0) + dist
        speed_limit = max(limit_totals, key=limit_totals.get)
    else:
        speed_limit = 50

    # Build file entries
    files = []
    directions_set = []
    day_types_set = []
    carriages_dict = {}

    for fi in file_infos:
        fe = FileEntry(
            path=fi["path"],
            direction=fi["direction"],
            day_type=fi["day_type"],
            carriage=fi["carriage"],
            tratto=fi["tratto"],
        )
        files.append(fe)

        if fi["direction"] and fi["direction"] not in directions_set:
            directions_set.append(fi["direction"])

        if fi["day_type"] and fi["day_type"] not in day_types_set:
            day_types_set.append(fi["day_type"])

        # Track carriages
        if fi["carriage"]:
            c = fi["carriage"]
            if c not in carriages_dict:
                carriages_dict[c] = {"directions": [], "tratti": []}
            if fi["direction"] and fi["direction"] not in carriages_dict[c]["directions"]:
                carriages_dict[c]["directions"].append(fi["direction"])
            if fi["tratto"] and fi["tratto"] not in carriages_dict[c]["tratti"]:
                carriages_dict[c]["tratti"].append(fi["tratto"])

    # For multi-dateRange, day_types come from daterange_map
    if multi_daterange and daterange_map:
        day_types_set = list(dict.fromkeys(daterange_map.values()))

    has_carriages = bool(carriages_dict)

    # If no road_name detected, use folder name
    if not road_name:
        road_name = data_path.name

    # Colors and labels
    colors, labels = _assign_colors(day_types_set, directions_set)

    # Date description
    date_desc = _detect_date_description(first_header)

    config = RoadConfig(
        road_name=road_name,
        data_path=data_path,
        output_dir=out,
        files=files,
        directions=directions_set,
        day_types=day_types_set,
        speed_limit=speed_limit,
        timeset_offset=timeset_offset,
        multi_daterange=multi_daterange,
        daterange_map=daterange_map,
        carriages=carriages_dict,
        has_carriages=has_carriages,
        colors=colors,
        labels=labels,
        date_description=date_desc,
    )
    return config
