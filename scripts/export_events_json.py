#!/usr/bin/env python3
"""
export_events_json.py
---------------------
Converts the v3c coastal flood catalogue (with coastal-snapped coordinates,
scientific regional overrides/exclusions, and matched BMKG tide gauge water
level anomalies) into optimized JSON and JS payloads for the INA-CoastalFlood
interactive web dashboard.

Features:
  - Reads data/processed/rob_events_v3c.csv and data/processed/rob_places_latlon.csv
  - Applies scientific filters from src.regions (drop_excluded, apply_event_overrides, apply_region_overrides)
  - Matches nearest BMKG tide station and computes peak water level anomaly (anom_obs_cm, wl_m, pct)
  - Exports clean, structured data/events.json for web fetch
  - Exports data/events.js (window.ROB_EVENTS) for zero-CORS local file:// viewing
  - Exports data/summary.json with aggregated metadata
"""

import sys
import os
import json
import argparse
from pathlib import Path
import numpy as np
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


def load_tidegauge_data(repo_root: Path) -> dict:
    """Load nearest BMKG tide station matches and calculate water level anomalies."""
    tg_match_file = repo_root / "data/processed/rob_tg_match_v3c.csv"
    contrib_file = repo_root / "data/processed/rob_contrib_v3c.csv"
    daily_pct_file = repo_root / "data/raw/tidegauge/restricted/tg_daily_pct_local.parquet"

    tg_data = {}

    if tg_match_file.is_file():
        df_match = pd.read_csv(tg_match_file)
        for _, r in df_match.iterrows():
            ev_id = str(r['event_id'])
            tg_data[ev_id] = {
                'station': str(r['station']),
                'dist_km': round(float(r['dist_km']), 1),
                'pct': round(float(r['pct_max']), 1) if pd.notna(r['pct_max']) else None,
                'anom_cm': None,
                'wl_m': None
            }

    if contrib_file.is_file():
        df_contrib = pd.read_csv(contrib_file)
        for _, r in df_contrib.iterrows():
            ev_id = str(r['event_id'])
            if ev_id in tg_data:
                if pd.notna(r['anom_obs_cm']):
                    tg_data[ev_id]['anom_cm'] = round(float(r['anom_obs_cm']), 1)
                if pd.notna(r['wl_obs_m']):
                    tg_data[ev_id]['wl_m'] = round(float(r['wl_obs_m']), 2)

    if daily_pct_file.is_file() and tg_match_file.is_file():
        df_match = pd.read_csv(tg_match_file)
        df_pct = pd.read_parquet(daily_pct_file)
        df_pct['date'] = pd.to_datetime(df_pct['date'])
        df_pct['doy'] = df_pct['date'].dt.dayofyear

        for ev_id, info in tg_data.items():
            if info['anom_cm'] is not None:
                continue
            ev_matches = df_match[df_match['event_id'] == ev_id]
            if len(ev_matches) == 0:
                continue
            ev_date = pd.to_datetime(ev_matches['date_start'].iloc[0])
            stn = info['station']
            stn_df = df_pct[df_pct['station'] == stn]
            ev_row = stn_df[stn_df['date'] == ev_date]
            if len(ev_row) > 0 and pd.notna(ev_row['wl_max'].iloc[0]):
                seg_id = ev_row['segment_id'].iloc[0]
                stn_seg = stn_df[stn_df['segment_id'] == seg_id]
                diff = np.abs(stn_seg['doy'].values - ev_date.dayofyear)
                circ_diff = np.minimum(diff, 366 - diff)
                ref_vals = stn_seg['wl_max'].values[circ_diff <= 45]
                ref_vals = ref_vals[~np.isnan(ref_vals)]
                if len(ref_vals) >= 15:
                    wl_obs = float(ev_row['wl_max'].iloc[0])
                    wl_ref = float(np.median(ref_vals))
                    anom_cm = round((wl_obs - wl_ref) * 100.0, 1)
                    info['anom_cm'] = anom_cm
                    info['wl_m'] = round(wl_obs, 2)

    return tg_data


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers."""
    R = 6371.0
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2.0)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2.0)**2
    c = 2.0 * np.arcsin(np.sqrt(a))
    return round(float(R * c), 1)


def load_satellite_data(repo_root: Path) -> dict:
    """Load nearest ocean pixel satellite sea level anomaly and decomposed bands."""
    bands_file = repo_root / "data/processed/rob_events_with_bands_v3c.csv"
    sat_data = {}
    if bands_file.is_file():
        df_bands = pd.read_csv(bands_file)
        for _, r in df_bands.iterrows():
            ev_id = str(r['event_id'])
            sla_cm = round(float(r['detrended_sla_cm']), 1) if pd.notna(r['detrended_sla_cm']) else None
            seas_cm = round(float(r['seasonal_cm']), 1) if pd.notna(r['seasonal_cm']) else None
            intra_cm = round(float(r['intraseasonal_cm']), 1) if pd.notna(r['intraseasonal_cm']) else None
            px_lat = round(float(r['pixel_lat']), 3) if pd.notna(r['pixel_lat']) else None
            px_lon = round(float(r['pixel_lon']), 3) if pd.notna(r['pixel_lon']) else None

            sat_data[ev_id] = {
                'sla_cm': sla_cm,
                'seasonal_cm': seas_cm,
                'intra_cm': intra_cm,
                'pixel_lat': px_lat,
                'pixel_lon': px_lon
            }
    return sat_data


def export_catalogue(events_csv: Path, places_csv: Path, out_dir: Path, apply_exclusions: bool = True):
    out_dir.mkdir(parents=True, exist_ok=True)

    if not events_csv.is_file():
        raise FileNotFoundError(f"Events CSV not found at {events_csv}")
    if not places_csv.is_file():
        raise FileNotFoundError(f"Places CSV not found at {places_csv}")

    print(f"[1/5] Reading events from {events_csv.name}...")
    df_events = pd.read_csv(events_csv)
    raw_count = len(df_events)

    # Apply scientific overrides & exclusions if available
    if HAS_REGIONS_MODULE and apply_exclusions:
        print("[2/5] Applying scientific exclusions & place/region overrides from src.regions...")
        df_events = drop_excluded(df_events)
        print(f"      Filtered {raw_count} raw events down to {len(df_events)} verified coastal flood events.")
    elif HAS_REGIONS_MODULE:
        df_events = apply_region_overrides(apply_event_overrides(df_events))

    print(f"[3/5] Reading places coordinates from {places_csv.name}...")
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

    # Load tide gauge observations
    print("[4/6] Matching nearest BMKG tide gauge water level anomalies...")
    tg_data = load_tidegauge_data(REPO_ROOT)
    matched_tg_count = sum(1 for e in merged['event_id'] if e in tg_data)
    with_anom_count = sum(1 for e in merged['event_id'] if e in tg_data and tg_data[e]['anom_cm'] is not None)
    print(f"      Matched {matched_tg_count} events to nearest tide station ({with_anom_count} with active water level anomalies).")

    # Load satellite sea level altimetry
    print("[5/6] Matching nearest satellite altimetry sea level anomalies (C3S)...")
    sat_data = load_satellite_data(REPO_ROOT)
    matched_sat_count = sum(1 for e in merged['event_id'] if e in sat_data and sat_data[e]['sla_cm'] is not None)
    print(f"      Matched {matched_sat_count} events to nearest satellite ocean grid pixels.")

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
        ev_id = str(row['event_id'])
        title = str(row['first_title']).strip('"\' ') if pd.notna(row['first_title']) else ''
        terms = str(row['terms']).strip('"\' ') if pd.notna(row['terms']) else ''
        depth = float(row['depth_cm']) if pd.notna(row['depth_cm']) else None
        reg_code = str(row['region']).strip()
        tier_code = str(row['tier']).strip().lower()
        hazard_code = str(row['hazard']).strip()
        ev_lat = round(float(row['lat']), 5)
        ev_lon = round(float(row['lon']), 5)

        # Tide gauge match info
        tg_info = tg_data.get(ev_id, None)

        # Satellite SLA match info
        sat_raw = sat_data.get(ev_id, None)
        sat_info = None
        if sat_raw and sat_raw.get('sla_cm') is not None:
            dist_sat = None
            if sat_raw.get('pixel_lat') is not None and sat_raw.get('pixel_lon') is not None:
                dist_sat = haversine_km(ev_lat, ev_lon, sat_raw['pixel_lat'], sat_raw['pixel_lon'])
            sat_info = {
                'sla_cm': sat_raw['sla_cm'],
                'dist_km': dist_sat
            }

        records.append({
            'id': ev_id,
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
            'lat': ev_lat,
            'lon': ev_lon,
            'tg': tg_info,
            'sat': sat_info,
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
        'tide_gauge_matches': matched_tg_count,
        'tide_gauge_anomalies': with_anom_count,
        'satellite_sla_matches': matched_sat_count,
        'generated_at': pd.Timestamp.now().isoformat()
    }

    # [6/6] Output files
    json_path = out_dir / "events.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(records, f, separators=(',', ':'), ensure_ascii=False)
    print(f"[6/6] Wrote {total_events} events to {json_path} ({json_path.stat().st_size / 1024:.1f} KB)")

    js_path = out_dir / "events.js"
    with open(js_path, 'w', encoding='utf-8') as f:
        f.write("// INA-CoastalFlood: Indonesian Coastal Flood Catalogue Dataset (v3c)\n")
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

    parser = argparse.ArgumentParser(description="Export v3c rob catalogue with tide gauge anomalies for web dashboard")
    parser.add_argument('--events', type=Path, default=default_events, help="Path to rob_events_v3c.csv")
    parser.add_argument('--places', type=Path, default=default_places, help="Path to rob_places_latlon.csv")
    parser.add_argument('--out', type=Path, default=default_out, help="Output directory for web data")
    parser.add_argument('--no-exclusions', action='store_true', help="Disable scientific exclusions filtering")

    args = parser.parse_args()
    export_catalogue(args.events, args.places, args.out, apply_exclusions=not args.no_exclusions)
