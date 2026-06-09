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


# ------------------------------------------------------------
# Environment
# ------------------------------------------------------------

MAX_WORKERS = max(1, int(os.cpu_count() * 0.75))

AOI = arcpy.GetParameterAsText(0)

geojson_param = arcpy.GetParameterAsText(4)
download_param = arcpy.GetParameterAsText(1)

POLYTYPE = arcpy.GetParameterAsText(2).lower()
LIDAR_PHASE = arcpy.GetParameterAsText(3).lower() or "laz-phase2"

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
# File utilities
# ------------------------------------------------------------

def wait_for_file(path, timeout=120):

    start = time.time()
    last_size = -1
    stable_count = 0

    path = Path(path)

    while True:

        if path.exists():
            size = path.stat().st_size

            if size == last_size:
                stable_count += 1
            else:
                stable_count = 0
                last_size = size

            if stable_count >= 3:
                return

        if time.time() - start > timeout:
            raise TimeoutError(f"File not stable: {path}")

        time.sleep(1)


def download_file(url):

    local_path = DOWNLOAD_FOLDER / Path(url).name

    if not local_path.exists():

        arcpy.AddMessage(f"Downloading {url}")

        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()

            with open(local_path, "wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)

    wait_for_file(local_path)

    return str(local_path)


# ------------------------------------------------------------
# Conversion
# ------------------------------------------------------------

def process_lidar(url):

    name = Path(url).name.replace(".copc.laz", "").replace(".laz", "")

    local_input = download_file(url)

    output_las = DOWNLOAD_FOLDER / f"{name}.las"

    arcpy.AddMessage(f"Converting {name}")

    try:
        arcpy.conversion.ConvertLas(
            in_las=local_input,
            target_folder=str(DOWNLOAD_FOLDER),
            out_las_dataset=str(output_las) + ".lasd",
            file_version="SAME_AS_INPUT",
            compression="NO_COMPRESSION",
            las_options="REARRANGE_POINTS",
            define_coordinate_system="NO_FILES"
        )

        arcpy.AddMessage(f"Done: {name}")

    except Exception as e:
        arcpy.AddWarning(f"Failed {name}: {e}")


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    geojson = convert_to_geojson(AOI)
    geometry = get_geometry(geojson)

    url_list = get_assets(SEARCH_URL, geometry)

    arcpy.AddMessage(f"Found {len(url_list)} files.")

    for url in url_list:
        process_lidar(url)

    arcpy.AddMessage("Finished.")


if __name__ == "__main__":
    main()