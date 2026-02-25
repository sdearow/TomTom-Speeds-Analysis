#!/usr/bin/env python3
"""
Speed Analysis Generator — Generate speed analysis reports from TomTom GeoJSON data.

Usage:
    python generate_report.py /path/to/geojson/folder [--output /path/to/output]
                                                       [--speed-limit 50]
                                                       [--road-name "My Road"]

The script auto-detects road name, directions, day types, and speed limits
from the GeoJSON files. Use the optional flags to override auto-detected values.
"""

import argparse
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")


def main():
    parser = argparse.ArgumentParser(
        description="Generate speed analysis report from TomTom GeoJSON files.")
    parser.add_argument("data_path",
                        help="Path to folder containing .geojson files")
    parser.add_argument("--output", "-o", default=None,
                        help="Output directory (default: <data_path>/output)")
    parser.add_argument("--speed-limit", type=int, default=None,
                        help="Override auto-detected speed limit (km/h)")
    parser.add_argument("--road-name", default=None,
                        help="Override auto-detected road name")
    parser.add_argument("--no-static-maps", action="store_true",
                        help="Skip static map generation (faster)")
    parser.add_argument("--no-docx", action="store_true",
                        help="Skip Word report generation")
    args = parser.parse_args()

    data_path = Path(args.data_path).resolve()
    if not data_path.exists():
        print(f"Error: {data_path} does not exist")
        sys.exit(1)

    # Import here to avoid slow startup for --help
    from speed_analysis.config import auto_detect
    from speed_analysis.loader import load_all_data
    from speed_analysis.stats import segment_peak_stats
    from speed_analysis.charts import generate_all_charts
    from speed_analysis.maps import generate_interactive_maps, generate_all_static_maps
    from speed_analysis.report_html import build_summary_tables, generate_html_report
    from speed_analysis.report_docx import generate_word_report

    # Auto-detect configuration
    print("Auto-rilevamento configurazione...")
    config = auto_detect(str(data_path), args.output)

    # Apply overrides
    if args.speed_limit is not None:
        config.speed_limit = args.speed_limit
    if args.road_name is not None:
        config.road_name = args.road_name

    print(f"  Strada:         {config.road_name}")
    print(f"  Direzioni:      {', '.join(config.directions)}")
    print(f"  Tipi giorno:    {', '.join(config.day_types)}")
    print(f"  Limite vel.:    {config.speed_limit} km/h")
    print(f"  TimeSet offset: {config.timeset_offset}")
    print(f"  Multi-dateRange: {config.multi_daterange}")
    print(f"  File GeoJSON:   {len(config.files)}")
    print(f"  Periodo:        {config.date_description}")
    if config.has_carriages:
        print(f"  Carreggiate:    {', '.join(config.carriages.keys())}")
    print(f"  Output:         {config.output_dir}")
    print()

    # Load data
    print("Caricamento dati...")
    segments, summaries, headers = load_all_data(config)
    print(f"  {len(segments)} righe segmento, {len(summaries)} righe sommario")

    # Statistics
    print("Calcolo statistiche per segmento...")
    seg_stats = segment_peak_stats(segments, config)

    # Create output directories
    config.output_dir.mkdir(parents=True, exist_ok=True)

    # Generate charts
    print("Generazione grafici...")
    charts = generate_all_charts(segments, summaries, config)

    # Generate static maps
    static_map_paths = []
    if not args.no_static_maps:
        print("Generazione mappe statiche (contextily)...")
        static_map_paths = generate_all_static_maps(segments, config)
        print(f"  {len(static_map_paths)} mappe statiche generate")

    # Generate interactive maps
    print("Generazione mappe interattive...")
    map_files = generate_interactive_maps(segments, seg_stats, config)
    print(f"  {len(map_files)} mappe interattive generate")

    # Build tables
    print("Costruzione tabelle...")
    tables = build_summary_tables(segments, summaries, seg_stats, config)

    # Generate HTML report
    print("Assemblaggio report HTML...")
    html = generate_html_report(charts, map_files, tables, config)
    road_slug = config.road_name.lower().replace(" ", "_")[:30]
    report_path = config.output_dir / f"report_{road_slug}.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Generate Word report
    docx_path = None
    if not args.no_docx:
        print("Assemblaggio report Word (.docx)...")
        docx_path = generate_word_report(charts, tables, static_map_paths, config)
        print(f"  DOCX: {docx_path}")

    # Export CSV
    csv_path = config.output_dir / "dati_segmenti.csv"
    segments.drop(columns=["geometry"]).to_csv(csv_path, index=False)

    print(f"\nReport HTML:  {report_path}")
    if docx_path:
        print(f"Report DOCX:  {docx_path}")
    print(f"Dati CSV:     {csv_path}")
    print(f"Mappe:        {config.output_dir / 'maps'}")
    print("\nDone!")


if __name__ == "__main__":
    main()
