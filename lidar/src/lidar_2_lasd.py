#!/usr/bin/env python

# Filename: lidar_2_las.py
# Author: Ian Horn (refactored)
# Description: Download lidar intersecting an AOI from a STAC API
#              and convert COPC/LAZ files to LAS using ArcGIS Pro.


import os
import json
import pdal
import arcpy
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


# ------------------------------------------------------------
# Environment
# ------------------------------------------------------------

AOI = arcpy.GetParameterAsText(0) or r'C:/Users/ian.horn/Documents/repos/kyfromabove-arcgis-pro-solutions/pro-project/pro-project.gdb/county_polygon'

geojson_param = arcpy.GetParameterAsText(1) or 'GeoJSONs'
download_param = arcpy.GetParameterAsText(2) or 'Downloads'
POLYTYPE = (arcpy.GetParameterAsText(3) or 'Polygon').lower()
LIDAR_PHASE = (arcpy.GetParameterAsText(4) or "laz-phase2").lower()
SEARCH_LIMIT = int(arcpy.GetParameterAsText(5) or 50)

STAC = arcpy.GetParameterAsText(6) or 'https://drwgni8q1h.execute-api.us-west-2.amazonaws.com/'
SEARCH_URL = f"{STAC}search"

GEOJSON_FOLDER = Path(geojson_param) if geojson_param else Path.home() / "GeoJSONs"
DOWNLOAD_FOLDER = Path(download_param) if download_param else Path.home() / "Downloads"

GEOJSON_FOLDER.mkdir(parents=True, exist_ok=True)
DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

MAX_WORKERS = 4  # max(1, int(os.cpu_count() * 0.75))


# ------------------------------------------------------------
# GeoJSON
# ------------------------------------------------------------

def convert_to_geojson(feature_class):

    out_geojson = GEOJSON_FOLDER / f"{Path(feature_class).stem}.geojson"

    if not out_geojson.exists():
        arcpy.AddMessage(f"Creating GeoJSON: {out_geojson}")

        arcpy.FeaturesToJSON_conversion(
            in_features=feature_class,
            out_json_file=str(out_geojson),
            format_json="FORMATTED",
            geoJSON="GEOJSON",
            outputToWGS84="WGS84"
        )

    if not out_geojson.exists():
        raise RuntimeError("GeoJSON creation failed")

    with open(out_geojson, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not data.get("features"):
        raise ValueError("GeoJSON has no features")

    return data

def get_geometry(geojson):
    return geojson["features"][0]["geometry"]


# ------------------------------------------------------------
# STAC (SYNC FIXED)
# ------------------------------------------------------------

def get_assets(search_url, geometry):

    payload = {
        "collections": [LIDAR_PHASE],
        "intersects": geometry,
        "limit": SEARCH_LIMIT
    }

    response = requests.post(search_url, json=payload, timeout=60)
    response.raise_for_status()

    data = response.json()
    features = data.get("features", [])

    if not features:
        raise ValueError("No assets found.")

    urls = []

    for f in features:
        href = f.get("assets", {}).get("data", {}).get("href")
        if href:
            urls.append(href)

    return urls


# ------------------------------------------------------------
# PDAL
# ------------------------------------------------------------


def download_file(url):

    local_path = DOWNLOAD_FOLDER / Path(url).name

    if local_path.exists():
        arcpy.AddMessage(f"Skipping download: {local_path.name}")
        return str(local_path)

    arcpy.AddMessage(f"Downloading: {url}")

    try:
        with requests.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()

            with open(local_path, "wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)

        return str(local_path)

    except Exception as e:
        raise RuntimeError(f"Download failed {url}: {e}")


def run_pdal(url):

    arcpy.AddMessage(f"Starting pipeline: {url}")

    local_input = None

    try:
        # ----------------------------------------------------
        # 1. DOWNLOAD
        # ----------------------------------------------------
        local_input = download_file(url)

        outfile_name = DOWNLOAD_FOLDER / f"{Path(url).stem}.las"

        if outfile_name.exists():
            arcpy.AddMessage(f"Skipping existing: {outfile_name.name}")
            return

        # ----------------------------------------------------
        # 2. PROCESS
        # ----------------------------------------------------
        pipeline_json = [
            {
                "type": "readers.copc",
                "filename": local_input
            },
            {
                "type": "writers.las",
                "filename": str(outfile_name)
            }
        ]

        pipeline = pdal.Pipeline(json.dumps(pipeline_json))
        pipeline.execute()

        arcpy.AddMessage(f"Finished: {outfile_name.name}")

    except Exception as e:
        arcpy.AddWarning(f"Pipeline failed for {url}: {e}")

    finally:
        # ----------------------------------------------------
        # 3. CLEANUP (ALWAYS RUNS)
        # ----------------------------------------------------
        if local_input and Path(local_input).exists():
            try:
                os.remove(local_input)
                arcpy.AddMessage(f"Deleted temp: {Path(local_input).name}")
            except Exception as e:
                arcpy.AddWarning(f"Could not delete {local_input}: {e}")


# ------------------------------------------------------------
# Parallel processing (replacement for asyncio)
# ------------------------------------------------------------

def process_all(url_list):

    arcpy.AddMessage(f"Processing {len(url_list)} files...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(run_pdal, url): url for url in url_list}
        for future in as_completed(futures):
            url = futures[future]
            try:
                future.result()
            except Exception as e:
                arcpy.AddWarning(f"Failed {url}: {e}")


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    geojson = convert_to_geojson(AOI)
    geometry = get_geometry(geojson)

    url_list = get_assets(SEARCH_URL, geometry)
    arcpy.AddMessage(f"Found {len(url_list)} files.")

    process_all(url_list)
    arcpy.AddMessage("Finished.")


if __name__ == "__main__":
    main()