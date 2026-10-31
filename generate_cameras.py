#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Generates camera, lens, mount, and lensfun distortion database for Gyroflow

import glob
import os
import xml.etree.ElementTree as ET
import json
import gzip
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Look for lensfun db either locally or in common repo paths
LENSFUN_CANDIDATES = [
    os.path.join(SCRIPT_DIR, "lensfun", "data", "db"),
    os.path.join(SCRIPT_DIR, "..", "lensfun", "data", "db"),
    r"C:\Users\xrawi\OneDrive\Рабочий стол\Game\MoneyHunt\lensfun\data\db",
    "/usr/share/lensfun/version_1",
    "/var/lib/lensfun-updates/version_1",
]

lensfun_dir = None
for candidate in LENSFUN_CANDIDATES:
    if os.path.exists(candidate) and glob.glob(os.path.join(candidate, "*.xml")):
        lensfun_dir = candidate
        break

gyro_profiles_dir = SCRIPT_DIR
output_dir = os.path.join(SCRIPT_DIR, "..", "gyroflow", "resources", "camera_presets")
if not os.path.exists(output_dir):
    output_dir = SCRIPT_DIR

mounts = {}
cameras = defaultdict(dict)
lenses = defaultdict(dict)

def guess_sensor_size(crop_factor):
    if not crop_factor:
        return "Unknown"
    try:
        cf = float(crop_factor)
    except:
        return "Unknown"
    if cf <= 1.05:
        return "Full Frame"
    elif 1.45 <= cf <= 1.58:
        return "APS-C"
    elif 1.59 <= cf <= 1.7:
        return "APS-C (Canon)"
    elif 1.9 <= cf <= 2.2:
        return "Micro Four Thirds"
    elif 2.5 <= cf <= 3.0:
        return "1 inch"
    elif 4.0 <= cf <= 6.5:
        return "Action Cam / Mobile"
    elif cf < 0.9:
        return "Medium Format"
    return f"{cf:.1f}x"

# 1. Parse Lensfun XMLs
if lensfun_dir:
    print(f"Reading LensFun database from {lensfun_dir}...")
    for xml_file in glob.glob(os.path.join(lensfun_dir, "*.xml")):
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            for m in root.findall("mount"):
                name = m.findtext("name")
                if name:
                    name = name.strip()
                    compats = [c.text.strip() for c in m.findall("compat") if c.text]
                    if name not in mounts:
                        mounts[name] = {"compatible_mounts": compats}
                    else:
                        for c in compats:
                            if c not in mounts[name]["compatible_mounts"]:
                                mounts[name]["compatible_mounts"].append(c)

            for cam in root.findall("camera"):
                maker = cam.findtext("maker")
                model = cam.findtext("model")
                mount = cam.findtext("mount")
                crop = cam.findtext("cropfactor")
                if maker and model:
                    maker = maker.strip()
                    model = model.strip()
                    cf = float(crop.strip()) if crop else 1.0
                    mount_s = mount.strip() if mount else "Fixed / Integrated"
                    cameras[maker][model] = {
                        "mount": mount_s,
                        "crop_factor": cf,
                        "sensor": guess_sensor_size(cf),
                        "source": "lensfun"
                    }

            for lens in root.findall("lens"):
                maker = lens.findtext("maker")
                model = lens.findtext("model")
                mount = lens.findtext("mount")
                crop = lens.findtext("cropfactor")
                if maker and model:
                    maker = maker.strip()
                    model = model.strip()
                    cf = float(crop.strip()) if crop else 1.0
                    mount_s = mount.strip() if mount else "Fixed / Integrated"
                    
                    dists = []
                    for d in lens.findall("calibration/distortion"):
                        m = d.attrib.get("model", "ptlens")
                        f = float(d.attrib.get("focal", 0))
                        a = float(d.attrib.get("a", 0))
                        b = float(d.attrib.get("b", 0))
                        c = float(d.attrib.get("c", 0))
                        dists.append({"model": m, "focal": f, "coeffs": [a, b, c]})

                    is_zoom = len(dists) > 1 or "-" in model
                    focals = [d["focal"] for d in dists if d.get("focal")]
                    min_f = min(focals) if focals else None
                    max_f = max(focals) if focals else None

                    lenses[maker][model] = {
                        "mount": mount_s,
                        "crop_factor": cf,
                        "sensor_coverage": guess_sensor_size(cf),
                        "is_zoom": is_zoom,
                        "min_focal": min_f,
                        "max_focal": max_f,
                        "has_calibration": len(dists) > 0,
                        "calibrations": dists,
                        "source": "lensfun"
                    }
        except Exception as e:
            pass

# 2. Merge Gyroflow lens profiles
print(f"Reading Gyroflow lens profiles from {gyro_profiles_dir}...")
for root_dir, dirs, files in os.walk(gyro_profiles_dir):
    for f in files:
        if f.endswith(".json"):
            fp = os.path.join(root_dir, f)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as jf:
                    data = json.load(jf)
                    cb = (data.get("camera_brand") or "").strip()
                    cm = (data.get("camera_model") or "").strip()
                    lm = (data.get("lens_model") or "").strip()
                    crop = data.get("crop_factor")
                    
                    if cb and cm:
                        if cm not in cameras[cb]:
                            cf = float(crop) if crop else 1.0
                            is_fixed = any(x in cb for x in ["GoPro", "Insta360", "DJI", "RunCam", "Caddx", "Foxeer", "Hawkeye"])
                            cameras[cb][cm] = {
                                "mount": "Fixed / Integrated" if is_fixed else "Interchangeable",
                                "crop_factor": cf,
                                "sensor": guess_sensor_size(cf),
                                "source": "gyroflow"
                            }
                    if cb and lm:
                        if lm not in lenses[cb]:
                            cf = float(crop) if crop else 1.0
                            lenses[cb][lm] = {
                                "mount": cameras.get(cb, {}).get(cm, {}).get("mount"),
                                "crop_factor": cf,
                                "sensor_coverage": guess_sensor_size(cf),
                                "is_zoom": "-" in lm,
                                "min_focal": data.get("focal_length"),
                                "max_focal": data.get("focal_length"),
                                "has_calibration": True,
                                "calibrations": [],
                                "source": "gyroflow"
                            }
            except:
                pass

db = {
    "version": 1,
    "mounts": mounts,
    "cameras": {k: v for k, v in sorted(cameras.items())},
    "lenses": {k: v for k, v in sorted(lenses.items())}
}

# Write out uncompressed and compressed versions
output_paths = [
    os.path.join(output_dir, "cameras.json"),
    os.path.join(SCRIPT_DIR, "cameras.json")
]

for out_path in output_paths:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as out:
        json.dump(db, out, indent=2, ensure_ascii=False)
    
    gz_path = out_path + ".gz"
    with gzip.open(gz_path, "wt", encoding="utf-8") as out_gz:
        json.dump(db, out_gz, ensure_ascii=False)

    print(f"Generated {out_path} ({os.path.getsize(out_path)} bytes)")
    print(f"Generated {gz_path} ({os.path.getsize(gz_path)} bytes)")

print(f"Total Brands: {len(db['cameras'])}, Total Cameras: {sum(len(v) for v in db['cameras'].values())}, Total Lenses: {sum(len(v) for v in db['lenses'].values())}")

