#!/usr/bin/env python

# Filename: lidar_2_las.py
# Author: Ian Horn (refactored)
# Description: Download lidar intersecting an AOI from a STAC API
#              and convert COPC/LAZ files to LAS using ArcGIS Pro.

import os
import json
import time
from pathlib import Path

import arcpy
import requests
import pdal

from concurrent.futures import ThreadPoolExecutor, as_completed


# ------------------------------------------------------------
# Environment
# ------------------------------------------------------------

MAX_WORKERS = max(1, int(os.cpu_count() * 0.75))

AOI = arcpy.GetParameterAsText(0)

geojson_param = arcpy.GetParameterAsText(0)
download_param = arcpy.GetParameterAsText(1)
POLYTYPE = arcpy.GetParameterAsText(2).lower()
LIDAR_PHASE = arcpy.GetParameterAsText(3).lower() or "laz-phase2"
SEARCH_LIMIT = arcpy.GetParameterAsText(4) 

STAC = "https://drwgni8q1h.execute-api.us-west-2.amazonaws.com"
SEARCH_URL = f"{STAC}/search"

GEOJSON_FOLDER = Path(geojson_param) if geojson_param else Path.home() / "GeoJSONs"
DOWNLOAD_FOLDER = Path(download_param) if download_param else Path.home() / "Downloads"

GEOJSON_FOLDER.mkdir(parents=True, exist_ok=True)
DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------
# GeoJSON
# ------------------------------------------------------------

def convert_to_geojson(feature_class):
    """Convert feature class to GeoJSON and return JSON."""

    out_geojson = GEOJSON_FOLDER / f"{Path(feature_class).stem}.geojson"

    arcpy.FeaturesToJSON_conversion(
        in_features=feature_class,
        out_json_file=str(out_geojson),
        format_json="FORMATTED",
        geoJSON="GEOJSON",
        outputToWGS84="WGS84"
    )

    with open(out_geojson, "r", encoding="utf-8") as f:
        return json.load(f)


def get_geometry(geojson):
    return geojson["features"][0]["geometry"]


# ------------------------------------------------------------
# STAC
# ------------------------------------------------------------

def get_assets(search_url, geometry):

    payload = {
        "collections": [LIDAR_PHASE],
        "intersects": geometry,
        "limit": SEARCH_LIMIT
    }

    response = requests.post(search_url, json=payload, timeout=60)
    response.raise_for_status()

    features = response.json().get("features", [])

    if not features:
        raise ValueError("No assets found.")

    urls = []

    for f in features:
        href = f.get("assets", {}).get("data", {}).get("href")
        if href:
            urls.append(href)

    return urls


# ------------------------------------------------------------
# Conversion
# ------------------------------------------------------------

def process_lidar(url):

    outfile_name = f'{Path(DOWNLOAD_FOLDER / ({url}).stem)}las'

    json = [
        {
            "type": "readers.copc",
            "filename": url
        },
        {
            "type": "writers.las",
            "filename": outfile_name
        }
    ]


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    geojson = convert_to_geojson(AOI)
    geometry = get_geometry(geojson)

    url_list = get_assets(SEARCH_URL, geometry)

    arcpy.AddMessage(f"Found {len(url_list)} files.")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        ffuture_to_url = {executor.submit(process_lidar, url, 60): url for url in urls}
        for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    data = future.result()
                except Exception as exc:
                    print('%r generated an exception: %s' % (url, exc))
                else:
                    print('%r page is %d bytes' % (url, len(data)))



if __name__ == "__main__":
     main()