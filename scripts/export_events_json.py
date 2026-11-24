#!/usr/bin/env python3
"""
export_events_json.py
---------------------
Converts a coastal flood catalogue (rob_events_<cat>.csv, default v4; with
coastal-snapped coordinates, scientific regional overrides/exclusions, and
matched BMKG tide gauge water level anomalies) into optimized JSON and JS
payloads for the INA-CoastalFlood interactive web dashboard.

Features:
  - Reads data/processed/rob_events_<cat>.csv and data/processed/rob_places_latlon.csv
  - Reads station and satellite values from that catalogue's own tables
    (rob_tg_match_<cat>.csv, rob_contrib_<cat>.csv, rob_events_with_bands_<cat>.csv), keyed by event_id
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

from src import catalogue

try:
    from src.regions import drop_excluded, apply_event_overrides, apply_region_overrides
    HAS_REGIONS_MODULE = True
except ImportError:
    HAS_REGIONS_MODULE = False
    print("Notice: src.regions module not found, continuing without custom overrides.")


# @@AI@@ 2026-10-16 (Randi): station and satellite values are read from the tables of the catalogue named by the
# events file (rob_tg_match_<cat>.csv, rob_contrib_<cat>.csv, rob_events_with_bands_<cat>.csv; names as in
# src/catalogue.py), keyed directly by that catalogue's event_id. The old path read the v3c tables and translated ids
# through data/processed/event_id_map_v4.csv, which went stale whenever v4 was rebuilt and its ids renumbered.
def _catalogue_table(template: str, cat: str):
    """Read data/processed/<template with cat filled in>; None, with a warning, if the table is absent."""
    path = catalogue.PROC / template.format(cat=cat)
    if not path.is_file():
        print(f"      Warning: {path.name} not found; these fields stay empty for catalogue {cat}.")
        return None
    return pd.read_csv(path, dtype={'event_id': str})


def load_tidegauge_data(repo_root: Path, cat: str) -> dict:
    """Load nearest BMKG tide station matches and calculate water level anomalies, keyed by (place_clean, date_start)."""
    daily_pct_file = repo_root / "data/raw/tidegauge/restricted/tg_daily_pct_local.parquet"
    df_match = _catalogue_table("rob_tg_match_{cat}.csv", cat)
    df_contrib = _catalogue_table("rob_contrib_{cat}.csv", cat)
    tg_by_id = {}
    key_by_id = {}

    if df_match is not None:
        for _, r in df_match.iterrows():
            ev_id = str(r['event_id'])
            pl_key = (str(r['place']).strip().lower(), str(r['date_start']).strip())
            key_by_id[ev_id] = pl_key
            tg_by_id[ev_id] = {
                'station': str(r['station']),
                'dist_km': round(float(r['dist_km']), 1),
                'pct': round(float(r['pct_max']), 1) if pd.notna(r['pct_max']) else None,
                'anom_cm': None,
                'wl_m': None
            }

    if df_contrib is not None:
        for _, r in df_contrib.iterrows():
            ev_id = str(r['event_id'])
            if ev_id in tg_by_id:
                if pd.notna(r['anom_obs_cm']):
                    tg_by_id[ev_id]['anom_cm'] = round(float(r['anom_obs_cm']), 1)
                if pd.notna(r['wl_obs_m']):
                    tg_by_id[ev_id]['wl_m'] = round(float(r['wl_obs_m']), 2)

    if daily_pct_file.is_file() and df_match is not None:
        start_by_id = df_match.set_index('event_id')['date_start']
        df_pct = pd.read_parquet(daily_pct_file)
        df_pct['date'] = pd.to_datetime(df_pct['date'])
        df_pct['doy'] = df_pct['date'].dt.dayofyear

        for ev_id, info in tg_by_id.items():
            if info['anom_cm'] is not None:
                continue
            ev_date = pd.to_datetime(start_by_id[ev_id])
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

    return {key_by_id[ev_id]: info for ev_id, info in tg_by_id.items() if ev_id in key_by_id}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers."""
    R = 6371.0
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(dlon1 := lon2 - lon1)
    a = np.sin(dlat / 2.0)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2.0)**2
    c = 2.0 * np.arcsin(np.sqrt(a))
    return round(float(R * c), 1)


def load_satellite_data(repo_root: Path, cat: str) -> dict:
    """Load nearest ocean pixel satellite sea level anomaly and decomposed bands, keyed by (place_clean, date_start)."""
    df_bands = _catalogue_table("rob_events_with_bands_{cat}.csv", cat)
    sat_data = {}
    if df_bands is not None:
        for _, r in df_bands.iterrows():
            pl_key = (str(r['place']).strip().lower(), str(r['date_start']).strip())
            sla_cm = round(float(r['detrended_sla_cm']), 1) if pd.notna(r['detrended_sla_cm']) else None
            seas_cm = round(float(r['seasonal_cm']), 1) if pd.notna(r['seasonal_cm']) else None
            intra_cm = round(float(r['intraseasonal_cm']), 1) if pd.notna(r['intraseasonal_cm']) else None
            px_lat = round(float(r['pixel_lat']), 3) if pd.notna(r['pixel_lat']) else None
            px_lon = round(float(r['pixel_lon']), 3) if pd.notna(r['pixel_lon']) else None

            sat_data[pl_key] = {
                'sla_cm': sla_cm,
                'seasonal_cm': seas_cm,
                'intra_cm': intra_cm,
                'pixel_lat': px_lat,
                'pixel_lon': px_lon
            }
    return sat_data


def merge_same_place(df: pd.DataFrame, articles_csv: Path) -> pd.DataFrame:
    """@@AI@@ 2026-10-30 (Randi: Padang Kawa is in Aceh Barat Daya). The catalogue forms its events per place NAME
    before the place corrections; two copies of one report filed under different names (E00946 'aceh barat', E00947
    'padang') become the same place once corrected. Rows with the same place and province whose dates touch (next
    start at most one day after the previous end, the v5 event rule) are joined: dates spanned, counts summed, urls
    and terms joined, independent outlets counted from the article table, the first event id kept."""
    df = df.copy()
    df["t_s"] = pd.to_datetime(df["date_start"])
    df["t_e"] = pd.to_datetime(df["date_end"])
    df = df.sort_values(["place", "province", "t_s", "event_id"])
    grp, prev = [], None
    for r in df.itertuples():
        key = (r.place, r.province)
        new = prev is None or key != prev[0] or (r.t_s - prev[1]).days > 1
        grp.append(0 if not grp else grp[-1] + 1 if new else grp[-1])
        prev = (key, max(r.t_e, prev[1]) if not new else r.t_e)
    df["t_g"] = grp
    if df["t_g"].is_unique:
        return df.drop(columns=["t_s", "t_e", "t_g"]).sort_index()
    domain = {}
    if articles_csv.is_file():
        a = pd.read_csv(articles_csv, usecols=["link", "domain"], low_memory=False)
        domain = dict(zip(a["link"], a["domain"].fillna("")))
    rows = []
    for _, g in df.groupby("t_g", sort=False):
        r = g.iloc[0].copy()
        if len(g) > 1:
            hz = set(g["hazard"])
            r["hazard"] = ("tide_wave" if "tide_wave" in hz or {"rob", "high_wave"} <= hz
                           else "high_wave" if hz == {"high_wave"} else "rob")
            r["date_start"], r["date_end"] = g["t_s"].min().date().isoformat(), g["t_e"].max().date().isoformat()
            r["n_days"] = (g["t_e"].max() - g["t_s"].min()).days + 1
            for c in ("n_query_hits", "n_articles_raw", "n_articles"):
                r[c] = int(pd.to_numeric(g[c], errors="coerce").fillna(0).sum())
            urls = list(dict.fromkeys(u for s in g["urls"].fillna("") for u in str(s).split()))
            r["urls"] = " ".join(urls)
            r["terms"] = "|".join(dict.fromkeys(x for s in g["terms"].fillna("") for x in str(s).split("|") if x))
            r["n_domains_raw"] = int(pd.to_numeric(g["n_domains_raw"], errors="coerce").max())
            r["n_domains_indep"] = (len({domain[u] for u in urls if domain.get(u)})
                                    or int(pd.to_numeric(g["n_domains_indep"], errors="coerce").max()))
            r["warning_ambiguous"] = bool(g["warning_ambiguous"].astype(str).eq("True").any())
            r["depth_cm"] = pd.to_numeric(g["depth_cm"], errors="coerce").max()
            print(f"      Joined after the place corrections: {' + '.join(g['event_id'])} -> {r['event_id']} "
                  f"({r['place']}, {r['date_start']})")
        rows.append(r)
    return pd.DataFrame(rows).drop(columns=["t_s", "t_e", "t_g"]).sort_index()


def export_catalogue(events_csv: Path, places_csv: Path, out_dir: Path, apply_exclusions: bool = True):
    out_dir.mkdir(parents=True, exist_ok=True)

    if not events_csv.is_file():
        raise FileNotFoundError(f"Events CSV not found at {events_csv}")
    if not places_csv.is_file():
        raise FileNotFoundError(f"Places CSV not found at {places_csv}")

    print(f"[1/5] Reading events from {events_csv.name}...")
    df_events = pd.read_csv(events_csv)
    raw_count = len(df_events)

    # @@AI@@ 2026-10-16 (Randi): the same corrections as every Ch5 analysis, for any catalogue. src.regions matches
    # exclusions and place overrides by article URL to the catalogue named by the events file (rob_events_<cat>.csv),
    # so the v3c-to-v4 id map is no longer needed here; the v3c exclusions that still apply to v4 events are applied.
    import os, re as _re
    _m = _re.match(r"rob_events_(.+)\.csv$", events_csv.name)
    if _m:
        os.environ["ROB_CATALOGUE"] = _m.group(1)
    cat = catalogue.name()
    print(f"      Catalogue: {cat} (station and satellite values from rob_*_{cat}.csv)")
    if HAS_REGIONS_MODULE and apply_exclusions:
        print("[2/5] Applying scientific exclusions & place/region overrides from src.regions...")
        df_events = drop_excluded(df_events, all_hazards=True)   # @@AI@@ 2026-10-19: web shows every hazard
        print(f"      Filtered {raw_count} raw events down to {len(df_events)} verified coastal flood events.")
    elif HAS_REGIONS_MODULE:
        df_events = apply_region_overrides(apply_event_overrides(df_events))
    if HAS_REGIONS_MODULE:   # @@AI@@ 2026-10-30
        df_events = merge_same_place(df_events, REPO_ROOT / f"data/raw/rob_harvest/articles_screened_{cat}.csv")
    if HAS_REGIONS_MODULE:   # @@AI@@ 2026-11-13 (Randi): literature floods confirmed by Randi, tagged "confirmed"
        from src.regions import event_additions
        df_add = event_additions()
        if len(df_add):
            df_events = pd.concat([df_events, df_add], ignore_index=True)
            print(f"      Added {len(df_add)} confirmed literature event(s): {list(df_add['event_id'])}")

    # @@AI@@ 2026-11-24 (Randi: "Di web tolong tambahkan keterangannya kalau yang benarnya 15 Jun 2025"): events whose
    # date was corrected (src.regions.date_overrides, applied with the other corrections above) carry a note, and
    # their station and satellite values come from the research tables, which are built on the corrected date (the
    # tables of the web catalogue hold the reported date)
    date_notes = {}
    if HAS_REGIONS_MODULE:
        from src.regions import date_overrides
        ov = date_overrides()
        ids = set(df_events["event_id"].astype(str))
        date_notes = {str(o["event_id"]): o for _, o in ov.iterrows() if str(o["event_id"]) in ids}
        if date_notes:
            print(f"      Date corrections: {sorted(date_notes)}")

    print(f"[3/5] Reading places coordinates from {places_csv.name}...")
    df_places = pd.read_csv(places_csv)

    # Case-insensitive cleaning and matching
    df_events['place_clean'] = df_events['place'].astype(str).str.strip().str.lower()
    df_events['prov_clean'] = df_events['province'].astype(str).str.strip().str.lower()
    df_places['place_clean'] = df_places['place'].astype(str).str.strip().str.lower()
    df_places['prov_clean'] = df_places['province'].astype(str).str.strip().str.lower()
    places_clean = df_places.drop_duplicates(subset=['place_clean', 'prov_clean'])

    # Merge on place & province
    merged = df_events.merge(
        places_clean[['place_clean', 'prov_clean', 'lat', 'lon', 'regency']],
        on=['place_clean', 'prov_clean'],
        how='left'
    )

    # Fallback merge on place name only for any unmatched province strings
    missing = merged['lat'].isna()
    if missing.sum() > 0:
        print(f"      Resolving {missing.sum()} places with province fallback...")
        places_by_place = places_clean.drop_duplicates(subset=['place_clean']).set_index('place_clean')
        for idx in merged[missing].index:
            p = merged.loc[idx, 'place_clean']
            prov = merged.loc[idx, 'prov_clean']
            if p == 'pesisir selatan' and prov != 'sumatera barat':
                continue
            if p in places_by_place.index:
                merged.loc[idx, 'lat'] = places_by_place.loc[p, 'lat']
                merged.loc[idx, 'lon'] = places_by_place.loc[p, 'lon']
                merged.loc[idx, 'regency'] = places_by_place.loc[p, 'regency']

    # Fallback for Madura if still unlocated
    madura_mask = merged['lat'].isna() & (merged['place_clean'] == 'madura')
    if madura_mask.sum() > 0:
        merged.loc[madura_mask, 'lat'] = -7.03
        merged.loc[madura_mask, 'lon'] = 112.75
        merged.loc[madura_mask, 'regency'] = 'Bangkalan (Madura)'

    gk_mask = merged['lat'].isna() & (merged['place_clean'].isin(['gunungkidul', 'baron', 'tpi baron']))
    if gk_mask.sum() > 0:
        merged.loc[gk_mask, 'lat'] = -8.1288
        merged.loc[gk_mask, 'lon'] = 110.5489
        merged.loc[gk_mask, 'regency'] = 'Gunungkidul (DI Yogyakarta)'

    # Keep events even if lat/lon is unlocated (e.g. 3 regional "pesisir selatan" direction events)
    unlocated = merged['lat'].isna().sum()
    if unlocated > 0:
        print(f"      Notice: {unlocated} event(s) without point coordinates kept for table (not mapped on leaflet).")

    # Load tide gauge observations
    print("[4/6] Matching nearest BMKG tide gauge water level anomalies...")
    tg_data = load_tidegauge_data(REPO_ROOT, cat)
    ev_keys = [(str(r['place']).strip().lower(), str(r['date_start']).strip()) for _, r in merged.iterrows()]
    matched_tg_count = sum(1 for k in ev_keys if k in tg_data)
    with_anom_count = sum(1 for k in ev_keys if k in tg_data and tg_data[k]['anom_cm'] is not None)
    print(f"      Matched {matched_tg_count} events to nearest tide station ({with_anom_count} with active water level anomalies).")

    # Load satellite sea level altimetry
    print("[5/6] Matching nearest satellite altimetry sea level anomalies (C3S)...")
    sat_data = load_satellite_data(REPO_ROOT, cat)
    matched_sat_count = sum(1 for k in ev_keys if k in sat_data and sat_data[k]['sla_cm'] is not None)
    print(f"      Matched {matched_sat_count} events to nearest satellite ocean grid pixels.")
    if date_notes:   # @@AI@@ 2026-11-24: corrected dates, values from the research tables (see date_notes above)
        import yaml
        research_cat = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())["rob"]["catalogue"]
        tg_res, sat_res = load_tidegauge_data(REPO_ROOT, research_cat), load_satellite_data(REPO_ROOT, research_cat)
        for _, r in merged[merged["event_id"].astype(str).isin(date_notes)].iterrows():
            k = (str(r['place']).strip().lower(), str(r['date_start']).strip())
            tg_data.pop(k, None)
            sat_data.pop(k, None)
            if k in tg_res:
                tg_data[k] = tg_res[k]
            if k in sat_res:
                sat_data[k] = sat_res[k]
            print(f"      {r['event_id']} {k}: station {'yes' if k in tg_res else 'no'}, satellite "
                  f"{'yes' if k in sat_res else 'no'} ({research_cat} tables)")
        # summary counts again, with the corrected events
        matched_tg_count = sum(1 for k in ev_keys if k in tg_data)
        with_anom_count = sum(1 for k in ev_keys if k in tg_data and tg_data[k]['anom_cm'] is not None)
        matched_sat_count = sum(1 for k in ev_keys if k in sat_data and sat_data[k]['sla_cm'] is not None)

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
        'high_wave': 'Gelombang Tinggi',
        'tide_wave': 'Rob + Gelombang (compound tide-wave)'   # @@AI@@ 2026-10-21 (Randi)
    }

    # Load screened article table for rich per-event article list
    print("[6/7] Loading screened article table for full headline and source mapping...")
    art_path = catalogue.articles_path()
    articles_by_url = {}
    if art_path.is_file():
        df_art = pd.read_csv(art_path, usecols=['link', 'title', 'published_date', 'domain']).drop_duplicates(subset=['link'])
        for _, ar in df_art.iterrows():
            u = str(ar['link']).strip()
            articles_by_url[u] = {
                'title': str(ar['title']).strip('"\' ') if pd.notna(ar['title']) else '',
                'url': u,
                'date': str(ar['published_date']).strip() if pd.notna(ar['published_date']) else '',
                'domain': str(ar['domain']).strip() if pd.notna(ar['domain']) else ''
            }
        print(f"      Loaded {len(articles_by_url)} unique article records from {art_path.name}")
    else:
        print(f"      Warning: Articles file not found at {art_path}")
    # @@AI@@ 2026-11-13: the paper behind each literature event is its one "article" (DOI link)
    if 'source_code' in merged.columns:
        for _, ev in merged[merged['source_code'] == 'literature'].iterrows():
            articles_by_url[str(ev['urls']).strip()] = {'title': str(ev['first_title']), 'url': str(ev['urls']).strip(),
                                                        'date': str(ev['date_start']), 'domain': 'doi.org'}

    # Load manual audit flags & QC verified tiers from data/processed/dashboard_audit_*.csv
    print("[7/7] Loading manual audit review flags from data/processed/dashboard_audit_*.csv...")
    audit_files = sorted(list((REPO_ROOT / "data/processed").glob("dashboard_audit_*.csv")) +
                         list((REPO_ROOT / "data/processed").glob("rob_inaccurate_audit_*.csv")))
    target_data_dir = Path("/Users/randifirdaus/Documents/indonesian-coastal-flood-catalogue/data")
    if target_data_dir.is_dir():
        audit_files += list(target_data_dir.glob("dashboard_audit_*.csv"))

    # Deduplicate while preserving order
    seen_files = set()
    dedup_audit_files = []
    for f in audit_files:
        if f.name not in seen_files:
            seen_files.add(f.name)
            dedup_audit_files.append(f)
    audit_files = dedup_audit_files

    # Build event lookups: url -> ev_id and (date_start, place_clean) -> ev_id
    url_to_ev_id = {}
    dp_to_ev_id = {}
    for _, ev in merged.iterrows():
        eid = str(ev['event_id'])
        u_list = str(ev['urls']).split() if pd.notna(ev['urls']) else []
        for u in u_list:
            url_to_ev_id[u] = eid
        pl_key = (str(ev['date_start']).strip(), str(ev['place']).strip().lower())
        dp_to_ev_id[pl_key] = eid

    audit_flags = {}
    matched_by_url = 0
    matched_by_dp = 0
    unmatched_audit_rows = []

    for af in audit_files:
        try:
            df_a = pd.read_csv(af)
            for _, ar in df_a.iterrows():
                u_raw = str(ar.get('url', '')).strip() if pd.notna(ar.get('url')) else ''
                dt = str(ar.get('date_start', '')).strip() if pd.notna(ar.get('date_start')) else ''
                pl = str(ar.get('place', '')).strip().lower() if pd.notna(ar.get('place')) else ''
                orig_eid = str(ar.get('event_id', '')).strip() if pd.notna(ar.get('event_id')) else ''

                ev_id = None
                match_type = None

                # Check URL tokens (including cases where audit row joined URLs with spaces)
                u_tokens = u_raw.split() if u_raw else []
                for u in u_tokens:
                    if u in url_to_ev_id:
                        ev_id = url_to_ev_id[u]
                        match_type = 'url'
                        break

                if not ev_id and (dt, pl) in dp_to_ev_id:
                    ev_id = dp_to_ev_id[(dt, pl)]
                    match_type = 'date_place'

                if not ev_id:
                    unmatched_audit_rows.append((orig_eid, pl, dt, u_raw, af.name))
                    continue

                if match_type == 'url':
                    matched_by_url += 1
                else:
                    matched_by_dp += 1

                # Parse verified tier & audit reason
                raw_v_tier = str(ar.get('verified_tier', '')).strip().lower() if pd.notna(ar.get('verified_tier')) else ''
                raw_status = str(ar.get('audit_status', '')).strip().upper() if pd.notna(ar.get('audit_status')) else ''
                raw_reason = str(ar.get('audit_reason') if pd.notna(ar.get('audit_reason')) else (ar.get('flag_reason') if pd.notna(ar.get('flag_reason')) else (ar.get('reason') if pd.notna(ar.get('reason')) else ''))).strip()
                flagged_at = str(ar.get('flagged_at', '')).strip() if pd.notna(ar.get('flagged_at')) else ''
                raw_auditor = str(ar.get('auditor', '')).strip() if ('auditor' in ar and pd.notna(ar.get('auditor'))) else ''
                if not raw_auditor or raw_auditor.lower() == 'randi':
                    raw_auditor = 'Randi Firdaus'

                if raw_v_tier in ['confirmed', 'probable', 'possible', 'not_rob']:
                    v_tier = raw_v_tier
                elif raw_status == 'INACCURATE':
                    v_tier = 'not_rob'
                elif raw_status.lower() in ['confirmed', 'probable', 'possible']:
                    v_tier = raw_status.lower()
                else:
                    v_tier = 'not_rob'

                # If already flagged, newest flagged_at wins
                if ev_id in audit_flags:
                    prev_at = audit_flags[ev_id].get('flagged_at', '')
                    if flagged_at and flagged_at < prev_at:
                        continue

                audit_flags[ev_id] = {
                    'flagged_inaccurate': (v_tier == 'not_rob'),
                    'verified_tier': v_tier,
                    'flag_reason': raw_reason,
                    'flagged_at': flagged_at,
                    'auditor': raw_auditor,
                }
        except Exception as err:
            print(f"      Notice: Could not parse {af.name}: {err}")

    print(f"      [Audit Matching] Loaded {len(audit_files)} audit file(s).")
    print(f"      Matched by URL: {matched_by_url} row(s)")
    print(f"      Matched by date+place: {matched_by_dp} row(s)")
    print(f"      Events currently flagged/curated in catalogue: {len(audit_flags)}")
    print(f"      Unmatched audit rows: {len(unmatched_audit_rows)}")
    for ur in unmatched_audit_rows:
        preview_u = (ur[3][:60] + '...') if len(ur[3]) > 60 else ur[3]
        print(f"        - Unmatched: [{ur[4]}] ID:{ur[0]} {ur[1]} ({ur[2]}) URL:{preview_u}")

    records = []
    events_with_diff_n_articles = []
    missing_urls_in_articles = []

    for _, row in merged.iterrows():
        ev_id = str(row['event_id'])
        title = str(row['first_title']).strip('"\' ') if pd.notna(row['first_title']) else ''
        terms = str(row['terms']).strip('"\' ') if pd.notna(row['terms']) else ''
        depth = float(row['depth_cm']) if pd.notna(row['depth_cm']) else None
        reg_code = str(row['region']).strip()
        tier_code = str(row['tier']).strip().lower() if ('tier' in row and pd.notna(row['tier'])) else ''
        hazard_code = str(row['hazard']).strip()
        ev_lat = round(float(row['lat']), 5) if pd.notna(row['lat']) else None
        ev_lon = round(float(row['lon']), 5) if pd.notna(row['lon']) else None

        # Tide gauge match info (keyed by (place_clean, date_start) so id shifts cannot misalign)
        ev_key = (str(row['place']).strip().lower(), str(row['date_start']).strip())
        tg_info = tg_data.get(ev_key, None)

        # Satellite SLA match info
        sat_raw = sat_data.get(ev_key, None)
        sat_info = None
        if sat_raw and sat_raw.get('sla_cm') is not None:
            dist_sat = None
            if ev_lat is not None and ev_lon is not None and sat_raw.get('pixel_lat') is not None and sat_raw.get('pixel_lon') is not None:
                dist_sat = haversine_km(ev_lat, ev_lon, sat_raw['pixel_lat'], sat_raw['pixel_lon'])
            sat_info = {
                'sla_cm': sat_raw['sla_cm'],
                'dist_km': dist_sat
            }

        # Multi-article resolution
        urls_raw = str(row['urls']) if pd.notna(row['urls']) else ''
        url_list = urls_raw.split()
        n_articles_val = int(row['n_articles']) if pd.notna(row['n_articles']) else len(url_list)

        if len(url_list) != n_articles_val:
            events_with_diff_n_articles.append((ev_id, n_articles_val, len(url_list)))
            print(f"      Warning: Event {ev_id} has {len(url_list)} URLs but n_articles={n_articles_val}")

        articles = []
        for u in url_list:
            if u in articles_by_url:
                articles.append(dict(articles_by_url[u]))
            else:
                missing_urls_in_articles.append((ev_id, u))
                print(f"      Warning: Event {ev_id} URL not found in articles table: {u}")
                articles.append({
                    'title': title or 'Laporan Banjir Rob',
                    'url': u,
                    'date': str(row['date_start']),
                    'domain': ''
                })

        # Sort articles in chronological order
        articles.sort(key=lambda a: a.get('date') or '')

        # Primary url is the first article's url
        first_url = url_list[0] if url_list else ''
        if not title and articles:
            title = articles[0]['title']

        flag_info = audit_flags.get(ev_id, {})
        if tier_code == 'confirmed' and not flag_info:   # @@AI@@ 2026-11-13: shown as a verified event on the web
            flag_info = {'flagged_inaccurate': False, 'verified_tier': 'confirmed', 'auditor': 'Randi Firdaus',
                         'flag_reason': str(row['tier_reason']).strip() if pd.notna(row.get('tier_reason')) else '',
                         'flagged_at': ''}

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
            'tier_label': tier_display_map.get(tier_code, tier_code.title() if tier_code else ''),
            'tier_reason': str(row['tier_reason']).strip() if ('tier_reason' in row and pd.notna(row['tier_reason'])) else '',
            'depth_cm': depth,
            'title': title,
            'terms': terms,
            'url': first_url,
            'articles': articles,
            'n_articles': int(row['n_articles']) if pd.notna(row['n_articles']) else 1,
            'n_domains': int(row['n_domains_indep']) if pd.notna(row['n_domains_indep']) else 1,
            'lat': ev_lat,
            'lon': ev_lon,
            'tg': tg_info,
            'sat': sat_info,
            'flagged_inaccurate': flag_info.get('flagged_inaccurate', False),
            'flag_reason': flag_info.get('flag_reason', ''),
            'flagged_at': flag_info.get('flagged_at', ''),
            'verified_tier': flag_info.get('verified_tier', None),
            'auditor': flag_info.get('auditor', ''),
        })
        if ev_id in date_notes:   # @@AI@@ 2026-11-24: date corrected by Randi; reported date and note (EN, ID)
            o = date_notes[ev_id]
            records[-1].update({'date_reported': str(o['date_start_reported']), 'date_note': str(o['note_en']),
                                'date_note_id': str(o['note_id'])})

    # Summary statistics
    total_events = len(records)
    unique_places = len(set(r['place'] for r in records))
    unique_provinces = sorted(list(set(r['province'] for r in records if r['province'])))
    unique_years = sorted(list(set(r['date_start'][:4] for r in records)))

    tier_counts = {}
    for r in records:
        if r.get('tier'):
            tier_counts[r['tier']] = tier_counts.get(r['tier'], 0) + 1

    region_counts = {}
    for r in records:
        region_counts[r['region']] = region_counts.get(r['region'], 0) + 1

    hazard_counts = {}
    for r in records:
        hazard_counts[r.get('hazard', 'rob')] = hazard_counts.get(r.get('hazard', 'rob'), 0) + 1

    summary = {
        'total_events': total_events,
        'unique_places': unique_places,
        'unique_provinces': unique_provinces,
        'year_range': [unique_years[0], unique_years[-1]] if unique_years else [],
        'tier_counts': tier_counts,
        'region_counts': region_counts,
        'hazard_counts': hazard_counts,
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
        f.write(f"// INA-CoastalFlood: Indonesian Coastal Flood Catalogue Dataset ({cat})\n")
        f.write("// Loaded automatically when accessed via file:// without webserver\n")
        f.write("window.ROB_EVENTS = ")
        json.dump(records, f, separators=(',', ':'), ensure_ascii=False)
        f.write(";\n")
    print(f"      Wrote JS bundle to {js_path} ({js_path.stat().st_size / 1024:.1f} KB)")

    summary_path = out_dir / "summary.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"      Wrote summary metadata to {summary_path}")

    # [6.5/7] Export OpenAlex literature flood dates (literature.json and literature.js)
    export_literature(REPO_ROOT, places_csv, out_dir, {r['id'] for r in records})

    # [7/7] Update local index.html static placeholders & cache-buster tags if present (skip public repo folder)
    rob_events = hazard_counts.get('rob', total_events)
    for candidate_index in [out_dir.parent / "index.html"]:
        if candidate_index.is_file():
            try:
                update_index_html(candidate_index, total_events, rob_events)
            except Exception as e:
                print(f"      Notice: Could not update {candidate_index.name}: {e}")

    return records, summary


def export_literature(repo_root: Path, places_csv: Path, out_dir: Path, web_event_ids: set):
    """Export OpenAlex literature flood date rows (2015-2026) to literature.json and literature.js."""
    lit_csv = repo_root / "data/processed/literature_rob_events.csv"
    v5e_csv = repo_root / "data/processed/rob_events_v5e.csv"
    if not lit_csv.is_file():
        print(f"      Notice: {lit_csv} not found; skipping literature export.")
        return []

    df_lit = pd.read_csv(lit_csv)
    df_places = pd.read_csv(places_csv)

    # Coordinate lookup by (place, province) then fallback by place (same pattern as catalogue)
    coords_by_place_prov = {}
    coords_by_place = {}
    for _, row in df_places.iterrows():
        p_clean = str(row['place']).strip().lower()
        prov_clean = str(row['province']).strip().lower() if pd.notna(row.get('province')) else ''
        if pd.notna(row['lat']) and pd.notna(row['lon']):
            coords_by_place_prov[(p_clean, prov_clean)] = (float(row['lat']), float(row['lon']))
            if p_clean not in coords_by_place:
                coords_by_place[p_clean] = (float(row['lat']), float(row['lon']))

    # P-id -> v5 E-ids mapping from rob_events_v5e.csv (merged_from column)
    p_to_e = {}
    if v5e_csv.is_file():
        df_v5e = pd.read_csv(v5e_csv)
        for _, row in df_v5e.iterrows():
            pid = str(row['event_id']).strip()
            mf = str(row['merged_from']).strip() if pd.notna(row.get('merged_from')) else ''
            p_to_e[pid] = [eid.strip() for eid in mf.split() if eid.strip()]

    # Verify all linked P-ids across the CSV map to web E-ids
    all_csv_pids = sorted({
        p.strip()
        for val in df_lit['catalogue_event_id'].dropna()
        for p in str(val).split()
        if p.strip()
    })
    unmapped_pids = []
    missing_web_eids = []
    for pid in all_csv_pids:
        eids = p_to_e.get(pid, [])
        if not eids:
            unmapped_pids.append(pid)
        for eid in eids:
            if eid not in web_event_ids:
                missing_web_eids.append((pid, eid))

    # Filter to kind == "date" and date in 2015..2026 (109 rows: 90 with place, 87 in rob_places_latlon.csv)
    df_date = df_lit[df_lit['kind'] == 'date'].copy()
    df_date['_start_str'] = df_date['date_or_month'].astype(str).str.split('/').str[0].str.strip()
    df_sub = df_date[
        (df_date['_start_str'] >= '2015-01-01') & (df_date['_start_str'] <= '2026-12-31')
    ].copy()

    region_display_map = {
        'java_north': 'Pantura Jawa',
        'java_south': 'Jawa Selatan',
        'sumatra_east': 'Sumatera Timur',
        'sumatra_west': 'Sumatera Barat',
        'kalimantan': 'Kalimantan',
        'east_indo': 'Indonesia Timur',
        'other': 'Lainnya'
    }

    lit_records = []
    with_place_count = 0
    with_coords_count = 0

    for seq_idx, (csv_idx, row) in enumerate(df_sub.iterrows()):
        raw_oa = str(row['openalex_id']).strip() if pd.notna(row.get('openalex_id')) else ''
        work_id = raw_oa.rstrip('/').split('/')[-1] if raw_oa else f"ROW{csv_idx}"
        dom = str(row['date_or_month']).strip()
        item_id = f"LIT-{work_id}-{dom}"

        date_start, _, date_end = dom.partition('/')
        date_start = date_start.strip()
        date_end = date_end.strip() if date_end.strip() else date_start

        place_raw = str(row['place']).strip() if pd.notna(row.get('place')) and str(row['place']).strip() else ''
        place_clean = place_raw.lower()
        prov_raw = str(row['province']).strip() if pd.notna(row.get('province')) and str(row['province']).strip() else ''
        prov_clean = prov_raw.lower()
        regency_raw = str(row['regency']).strip() if pd.notna(row.get('regency')) and str(row['regency']).strip() else ''
        region_raw = str(row['region']).strip() if pd.notna(row.get('region')) and str(row['region']).strip() else ''

        if place_clean:
            with_place_count += 1

        coords = None
        if place_clean:
            coords = coords_by_place_prov.get((place_clean, prov_clean))
            if not coords:
                if place_clean != "pesisir selatan" or prov_clean == "sumatera barat":
                    coords = coords_by_place.get(place_clean)

        lat = round(coords[0], 5) if coords else None
        lon = round(coords[1], 5) if coords else None
        if lat is not None and lon is not None:
            with_coords_count += 1

        cat_raw = str(row['catalogue_event_id']).strip() if pd.notna(row.get('catalogue_event_id')) else ''
        pids = [p.strip() for p in cat_raw.split() if p.strip()]
        status = "in catalogue" if len(pids) > 0 else "not in catalogue"

        linked_e_ids = []
        for pid in pids:
            for eid in p_to_e.get(pid, []):
                if eid in web_event_ids and eid not in linked_e_ids:
                    linked_e_ids.append(eid)

        flood_sentence = bool(row['flood_sentence']) if pd.notna(row.get('flood_sentence')) else False
        pub_year = int(row['year']) if pd.notna(row.get('year')) else None
        title = str(row['title']).strip() if pd.notna(row.get('title')) else ''
        source = str(row['source']).strip() if pd.notna(row.get('source')) else ''
        doi = str(row['doi']).strip() if pd.notna(row.get('doi')) else ''
        oa_url = str(row['oa_url']).strip() if pd.notna(row.get('oa_url')) else ''
        snippet = str(row['snippet']).strip() if pd.notna(row.get('snippet')) else ''

        lit_records.append({
            'id': item_id,
            'uid': f"{item_id}#{seq_idx + 1}",
            'openalex_id': raw_oa,
            'work_id': work_id,
            'date_or_month': dom,
            'date_start': date_start,
            'date_end': date_end,
            'place': place_raw,
            'regency': regency_raw,
            'province': prov_raw,
            'region': region_raw,
            'region_label': region_display_map.get(region_raw, region_raw if region_raw else '-'),
            'status': status,
            'catalogue_event_id': cat_raw,
            'linked_e_ids': linked_e_ids,
            'flood_sentence': flood_sentence,
            'title': title,
            'year': pub_year,
            'source': source,
            'doi': doi,
            'oa_url': oa_url,
            'snippet': snippet,
            'lat': lat,
            'lon': lon,
        })

    lit_json_path = out_dir / "literature.json"
    with open(lit_json_path, 'w', encoding='utf-8') as f:
        json.dump(lit_records, f, separators=(',', ':'), ensure_ascii=False)

    lit_js_path = out_dir / "literature.js"
    with open(lit_js_path, 'w', encoding='utf-8') as f:
        f.write("// INA-CoastalFlood: OpenAlex Literature Flood Dates (2015-2026)\n")
        f.write("// Loaded automatically when accessed via file:// without webserver\n")
        f.write("window.ROB_LITERATURE = ")
        json.dump(lit_records, f, separators=(',', ':'), ensure_ascii=False)
        f.write(";\n")

    print(
        f"      Wrote {len(lit_records)} literature items ({with_place_count} with place, "
        f"{with_coords_count} on map, {len(lit_records) - with_coords_count} table-only) "
        f"to {lit_json_path.name} & {lit_js_path.name}"
    )
    print(
        f"      Literature P-id check: {len(all_csv_pids)} distinct P-ids in CSV; "
        f"unmapped={unmapped_pids}, missing_in_web={missing_web_eids}"
    )
    return lit_records


def update_index_html(index_path: Path, total_events: int, rob_events: int = None):
    """Automatically update index.html static placeholder counts and cache-busting version params."""
    import re
    content = index_path.read_text(encoding='utf-8')
    v_tag = f"{total_events}.{pd.Timestamp.now().strftime('%Y%m%d%H%M')}"
    total_fmt = f"{total_events:,}"
    default_events = rob_events if rob_events is not None else total_events
    default_fmt = f"{default_events:,}"

    # Update cache-busting params for events.js, events.json, literature.js, literature.json
    content = re.sub(r'data/events\.js\?v=[^"\'\s>]+', f'data/events.js?v={v_tag}', content)
    content = re.sub(r'data/events\.json\?v=[^"\'\s>]+', f'data/events.json?v={v_tag}', content)
    content = re.sub(r'data/literature\.js\?v=[^"\'\s>]+', f'data/literature.js?v={v_tag}', content)
    content = re.sub(r'data/literature\.json\?v=[^"\'\s>]+', f'data/literature.json?v={v_tag}', content)

    # Update static badge/stat placeholders (defaulting to rob count for initial load)
    content = re.sub(r'(id="stat-total"[^>]*>)[0-9,]+(<)', rf'\g<1>{default_fmt}\g<2>', content)
    content = re.sub(r'(id="stat-filtered"[^>]*>)[0-9,]+(<)', rf'\g<1>{default_fmt}\g<2>', content)
    content = re.sub(r'(id="badge-all-reg"[^>]*>)[0-9,]+(<)', rf'\g<1>{default_events}\g<2>', content)
    content = re.sub(r'(id="label-count-active"[^>]*>)[0-9,]+(<)', rf'\g<1>{default_fmt}\g<2>', content)
    content = re.sub(r'(id="mobile-fab-count"[^>]*>)[0-9,]+(<)', rf'\g<1>{default_fmt}\g<2>', content)
    content = re.sub(r'(id="chart-filter-count"[^>]*>)[0-9,]+(<)', rf'\g<1>{default_fmt}\g<2>', content)
    content = re.sub(r'(id="table-total-count"[^>]*>)[0-9,]+(<)', rf'\g<1>{default_fmt}\g<2>', content)
    content = re.sub(r'(<span class="font-semibold font-mono">)[0-9,]+(</span> verified events)', rf'\g<1>{default_fmt}\g<2>', content)

    index_path.write_text(content, encoding='utf-8')
    print(f"      Updated {index_path.name} with default={default_fmt} (total={total_fmt}) and v={v_tag}")



if __name__ == '__main__':
    default_events = REPO_ROOT / "data/processed/rob_events_v5.csv"
    default_places = REPO_ROOT / "data/processed/rob_places_latlon.csv"
    default_out = Path(__file__).resolve().parent.parent / "data"

    parser = argparse.ArgumentParser(description="Export v5 rob catalogue with tide gauge anomalies for web dashboard")
    parser.add_argument('--events', type=Path, default=default_events, help="Path to rob_events_v5.csv")
    parser.add_argument('--places', type=Path, default=default_places, help="Path to rob_places_latlon.csv")
    parser.add_argument('--out', type=Path, default=default_out, help="Output directory for web data")
    parser.add_argument('--no-exclusions', action='store_true', help="Disable scientific exclusions filtering")

    args = parser.parse_args()
    export_catalogue(args.events, args.places, args.out, apply_exclusions=not args.no_exclusions)

