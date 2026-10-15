#!/usr/bin/env python3
"""
parse_catalogue_v3c.py
----------------------
Parses the v3c coastal flood catalogue and geocoded places from the thesis
dataset and exports clean, optimized JSON and JavaScript payloads for the
web dashboard.

Outputs:
  - data/events.json: Full JSON dataset for web fetch
  - data/events.js: window.ROB_EVENTS array for zero-CORS local file:// viewing
  - data/summary.json: Metadata, date ranges, and aggregated counts
"""

import sys
import os
import json
import argparse
from pathlib import Path
import pandas as pd

def parse_catalogue(events_csv: str, places_csv: str, out_dir: str):
    events_path = Path(events_csv)
    places_path = Path(places_csv)
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if not events_path.exists():
        raise FileNotFoundError(f"Events CSV not found at {events_path}")
    if not places_path.exists():
        raise FileNotFoundError(f"Places CSV not found at {places_path}")

    print(f"Loading events from {events_path}...")
    df_events = pd.read_csv(events_path)
    print(f"Loading places from {places_path}...")
    df_places = pd.read_csv(places_path)

    # De-duplicate places on ['place', 'province']
    places_clean = df_places.drop_duplicates(subset=['place', 'province'])
    
    # Merge events with coastal-snapped coordinates
    merged = df_events.merge(
        places_clean[['place', 'province', 'lat', 'lon', 'regency']],
        on=['place', 'province'],
        how='left'
    )

    # In case any place is still missing coordinates, fallback to place-only merge
    missing_coords = merged['lat'].isna()
    if missing_coords.sum() > 0:
        print(f"Warning: {missing_coords.sum()} events had unmatched province. Attempting place-only fallback...")
        places_by_place = df_places.drop_duplicates(subset=['place'])
        fallback_lookup = places_by_place.set_index('place')[['lat', 'lon', 'regency']]
        for idx in merged[missing_coords].index:
            p = merged.loc[idx, 'place']
            if p in fallback_lookup.index:
                merged.loc[idx, 'lat'] = fallback_lookup.loc[p, 'lat']
                merged.loc[idx, 'lon'] = fallback_lookup.loc[p, 'lon']
                merged.loc[idx, 'regency'] = fallback_lookup.loc[p, 'regency']

    # Final check on coordinates
    still_missing = merged['lat'].isna().sum()
    if still_missing > 0:
        print(f"Warning: {still_missing} events still missing coordinates! Dropping them for web map.")
        merged = merged.dropna(subset=['lat', 'lon'])

    # Sort events chronologically descending (newest first)
    merged = merged.sort_values(by='date_start', ascending=False)

    records = []
    region_display_map = {
        'java_north': 'Pantura Jawa',
        'java_south': 'Jawa Selatan',
        'sumatra_east': 'Sumatera Timur',
        'sumatra_west': 'Sumatera Barat',
        'kalimantan': 'Kalimantan',
        'east_indo': 'Indonesia Timur'
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

    for _, row in merged.iterrows():
        # Clean title: strip quotes if doubled
        raw_title = str(row['first_title']) if pd.notna(row['first_title']) else ''
        title_clean = raw_title.strip('"\' ')

        # Clean terms
        raw_terms = str(row['terms']) if pd.notna(row['terms']) else ''
        terms_clean = raw_terms.strip('"\' ')

        # Depth
        depth = float(row['depth_cm']) if pd.notna(row['depth_cm']) else None

        records.append({
            'id': str(row['event_id']),
            'hazard': str(row['hazard']),
            'hazard_label': hazard_display_map.get(str(row['hazard']), str(row['hazard']).replace('_', ' ').title()),
            'date_start': str(row['date_start']),
            'date_end': str(row['date_end']),
            'days': int(row['n_days']) if pd.notna(row['n_days']) else 1,
            'place': str(row['place']).title(),
            'province': str(row['province']).strip(),
            'regency': str(row['regency']).strip() if pd.notna(row['regency']) else '',
            'region': str(row['region']).strip(),
            'region_label': region_display_map.get(str(row['region']).strip(), str(row['region']).replace('_', ' ').title()),
            'tier': str(row['tier']).strip().lower(),
            'tier_label': tier_display_map.get(str(row['tier']).strip().lower(), str(row['tier']).title()),
            'tier_reason': str(row['tier_reason']).strip() if pd.notna(row['tier_reason']) else '',
            'depth_cm': depth,
            'title': title_clean,
            'terms': terms_clean,
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
        t = r['tier']
        tier_counts[t] = tier_counts.get(t, 0) + 1

    region_counts = {}
    for r in records:
        reg = r['region']
        region_counts[reg] = region_counts.get(reg, 0) + 1

    summary = {
        'total_events': total_events,
        'unique_places': unique_places,
        'unique_provinces': unique_provinces,
        'year_range': [unique_years[0], unique_years[-1]] if unique_years else [],
        'tier_counts': tier_counts,
        'region_counts': region_counts,
        'generated_at': pd.Timestamp.now().isoformat()
    }

    # 1. Write events.json
    json_path = output_path / "events.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(records, f, separators=(',', ':'), ensure_ascii=False)
    print(f"Successfully wrote {total_events} events to {json_path} ({json_path.stat().st_size / 1024:.1f} KB)")

    # 2. Write events.js for direct file:// browser support (bypasses CORS restrictions)
    js_path = output_path / "events.js"
    with open(js_path, 'w', encoding='utf-8') as f:
        f.write("// Indonesian Coastal Flood Catalogue Dataset (v3c)\n")
        f.write("// Loaded automatically when accessed via file:// without webserver\n")
        f.write("window.ROB_EVENTS = ")
        json.dump(records, f, separators=(',', ':'), ensure_ascii=False)
        f.write(";\n")
    print(f"Successfully wrote {total_events} events to {js_path} ({js_path.stat().st_size / 1024:.1f} KB)")

    # 3. Write summary.json
    summary_path = output_path / "summary.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Successfully wrote summary to {summary_path}")

    return records, summary

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Parse coastal flood catalogue v3c for web dashboard")
    parser.add_argument('--events', type=str, default="/Users/randifirdaus/Documents/Data_Processing/data/processed/rob_events_v3c.csv")
    parser.add_argument('--places', type=str, default="/Users/randifirdaus/Documents/Data_Processing/data/processed/rob_places_latlon.csv")
    parser.add_argument('--out', type=str, default="/Users/randifirdaus/Documents/indonesian-coastal-flood-catalogue/data")
    
    args = parser.parse_args()
    parse_catalogue(args.events, args.places, args.out)
