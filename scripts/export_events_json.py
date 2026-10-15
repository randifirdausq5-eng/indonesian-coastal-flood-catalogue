#!/usr/bin/env python3
"""
export_events_json.py
---------------------
Converts the v3c coastal flood catalogue (with coastal-snapped coordinates and
scientific regional overrides/exclusions) into optimized JSON and JS payloads
for the INDO-COASTFLOOD interactive web dashboard.

Features:
  - Reads data/processed/rob_events_v3c.csv and data/processed/rob_places_latlon.csv
  - Applies scientific filters from src.regions (drop_excluded, apply_event_overrides, apply_region_overrides)
  - Exports clean, structured data/events.json for web fetch
  - Exports data/events.js (window.ROB_EVENTS) for zero-CORS local file:// viewing
  - Exports data/summary.json with aggregated metadata
"""

import sys
import os
import json
import argparse
from pathlib import Path
import pandas as pd

# Add repo root to sys.path to import src.regions if needed
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from src.regions import drop_excluded, apply_event_overrides, apply_region_overrides
    HAS_REGIONS_MODULE = True
except ImportError:
    HAS_REGIONS_MODULE = False
    print("Notice: src.regions module not found, continuing without custom overrides.")


def export_catalogue(events_csv: Path, places_csv: Path, out_dir: Path, apply_exclusions: bool = True):
    out_dir.mkdir(parents=True, exist_ok=True)

    if not events_csv.is_file():
        raise FileNotFoundError(f"Events CSV not found at {events_csv}")
    if not places_csv.is_file():
        raise FileNotFoundError(f"Places CSV not found at {places_csv}")

    print(f"[1/4] Reading events from {events_csv.name}...")
    df_events = pd.read_csv(events_csv)
    raw_count = len(df_events)

    # Apply scientific overrides & exclusions if available
    if HAS_REGIONS_MODULE and apply_exclusions:
        print("[2/4] Applying scientific exclusions & place/region overrides from src.regions...")
        df_events = drop_excluded(df_events)
        print(f"      Filtered {raw_count} raw events down to {len(df_events)} verified coastal flood events.")
    elif HAS_REGIONS_MODULE:
        df_events = apply_region_overrides(apply_event_overrides(df_events))

    print(f"[3/4] Reading places coordinates from {places_csv.name}...")
    df_places = pd.read_csv(places_csv)
    places_clean = df_places.drop_duplicates(subset=['place', 'province'])

    # Merge on place & province
    merged = df_events.merge(
        places_clean[['place', 'province', 'lat', 'lon', 'regency']],
        on=['place', 'province'],
        how='left'
    )

    # Fallback merge on place name only for any unmatched province strings
    missing = merged['lat'].isna()
    if missing.sum() > 0:
        print(f"      Resolving {missing.sum()} places with province fallback...")
        places_by_place = df_places.drop_duplicates(subset=['place'])
        fallback_lookup = places_by_place.set_index('place')[['lat', 'lon', 'regency']]
        for idx in merged[missing].index:
            p = merged.loc[idx, 'place']
            if p in fallback_lookup.index:
                merged.loc[idx, 'lat'] = fallback_lookup.loc[p, 'lat']
                merged.loc[idx, 'lon'] = fallback_lookup.loc[p, 'lon']
                merged.loc[idx, 'regency'] = fallback_lookup.loc[p, 'regency']

    # Drop any remaining un-geocoded events
    unlocated = merged['lat'].isna().sum()
    if unlocated > 0:
        print(f"      Warning: Dropping {unlocated} events without valid coastal coordinates.")
        merged = merged.dropna(subset=['lat', 'lon'])

    # Sort descending by date (newest first)
    merged = merged.sort_values(by='date_start', ascending=False)

    # Human-readable labels mapping
    region_display_map = {
        'java_north': 'Pantura Jawa',
        'java_south': 'Jawa Selatan',
        'sumatra_east': 'Sumatera Timur',
        'sumatra_west': 'Sumatera Barat',
        'kalimantan': 'Kalimantan',
        'east_indo': 'Indonesia Timur',
        'other': 'Lainnya'
    }

    tier_display_map = {
        'confirmed': 'Confirmed',
        'probable': 'Probable',
        'possible': 'Possible'
    }

    hazard_display_map = {
        'rob': 'Banjir Rob',
        'high_wave': 'Gelombang Pasang'
    }

    records = []
    for _, row in merged.iterrows():
        title = str(row['first_title']).strip('"\' ') if pd.notna(row['first_title']) else ''
        terms = str(row['terms']).strip('"\' ') if pd.notna(row['terms']) else ''
        depth = float(row['depth_cm']) if pd.notna(row['depth_cm']) else None
        reg_code = str(row['region']).strip()
        tier_code = str(row['tier']).strip().lower()
        hazard_code = str(row['hazard']).strip()

        records.append({
            'id': str(row['event_id']),
            'hazard': hazard_code,
            'hazard_label': hazard_display_map.get(hazard_code, hazard_code.replace('_', ' ').title()),
            'date_start': str(row['date_start']),
            'date_end': str(row['date_end']),
            'days': int(row['n_days']) if pd.notna(row['n_days']) else 1,
            'place': str(row['place']).title(),
            'province': str(row['province']).strip(),
            'regency': str(row['regency']).strip() if pd.notna(row['regency']) else '',
            'region': reg_code,
            'region_label': region_display_map.get(reg_code, reg_code.replace('_', ' ').title()),
            'tier': tier_code,
            'tier_label': tier_display_map.get(tier_code, tier_code.title()),
            'tier_reason': str(row['tier_reason']).strip() if pd.notna(row['tier_reason']) else '',
            'depth_cm': depth,
            'title': title,
            'terms': terms,
            'url': str(row['urls']) if pd.notna(row['urls']) else '',
            'n_articles': int(row['n_articles']) if pd.notna(row['n_articles']) else 1,
            'n_domains': int(row['n_domains_indep']) if pd.notna(row['n_domains_indep']) else 1,
            'lat': round(float(row['lat']), 5),
            'lon': round(float(row['lon']), 5),
        })

    # Summary statistics
    total_events = len(records)
    unique_places = len(set(r['place'] for r in records))
    unique_provinces = sorted(list(set(r['province'] for r in records if r['province'])))
    unique_years = sorted(list(set(r['date_start'][:4] for r in records)))

    tier_counts = {}
    for r in records:
        tier_counts[r['tier']] = tier_counts.get(r['tier'], 0) + 1

    region_counts = {}
    for r in records:
        region_counts[r['region']] = region_counts.get(r['region'], 0) + 1

    summary = {
        'total_events': total_events,
        'unique_places': unique_places,
        'unique_provinces': unique_provinces,
        'year_range': [unique_years[0], unique_years[-1]] if unique_years else [],
        'tier_counts': tier_counts,
        'region_counts': region_counts,
        'generated_at': pd.Timestamp.now().isoformat()
    }

    # [4/4] Output files
    json_path = out_dir / "events.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(records, f, separators=(',', ':'), ensure_ascii=False)
    print(f"[4/4] Wrote {total_events} events to {json_path} ({json_path.stat().st_size / 1024:.1f} KB)")

    js_path = out_dir / "events.js"
    with open(js_path, 'w', encoding='utf-8') as f:
        f.write("// INDO-COASTFLOOD: Indonesian Coastal Flood Catalogue Dataset (v3c)\n")
        f.write("// Loaded automatically when accessed via file:// without webserver\n")
        f.write("window.ROB_EVENTS = ")
        json.dump(records, f, separators=(',', ':'), ensure_ascii=False)
        f.write(";\n")
    print(f"      Wrote JS bundle to {js_path} ({js_path.stat().st_size / 1024:.1f} KB)")

    summary_path = out_dir / "summary.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"      Wrote summary metadata to {summary_path}")

    return records, summary


if __name__ == '__main__':
    default_events = REPO_ROOT / "data/processed/rob_events_v3c.csv"
    default_places = REPO_ROOT / "data/processed/rob_places_latlon.csv"
    default_out = Path(__file__).resolve().parent.parent / "data"

    parser = argparse.ArgumentParser(description="Export v3c rob catalogue for web dashboard")
    parser.add_argument('--events', type=Path, default=default_events, help="Path to rob_events_v3c.csv")
    parser.add_argument('--places', type=Path, default=default_places, help="Path to rob_places_latlon.csv")
    parser.add_argument('--out', type=Path, default=default_out, help="Output directory for web data")
    parser.add_argument('--no-exclusions', action='store_true', help="Disable scientific exclusions filtering")

    args = parser.parse_args()
    export_catalogue(args.events, args.places, args.out, apply_exclusions=not args.no_exclusions)
