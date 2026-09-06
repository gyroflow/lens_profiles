#!/usr/bin/env python3
"""Build the camera catalogue from Gyroflow profiles and the pinned Lensfun data.

Run from any directory. No network, third-party Python packages or timestamps are
used, so a checkout always produces identical output. See CAMERA_DATABASE.md.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


def normalized(value):
    return "".join(c for c in value.lower() if c.isalnum())


def brand_name(value):
    return {"nikoncorporation": "Nikon", "canoninc": "Canon"}.get(normalized(value), value)


def camera_key(brand, model):
    original_brand, brand, model = normalized(brand), normalized(brand_name(brand)), normalized(model)
    if model.startswith(original_brand):
        model = model[len(original_brand):]
    if model.startswith(brand):
        model = model[len(brand):]
    # Lensfun's English Sony aliases use "Alpha"; Gyroflow uses "a".
    if brand == "sony" and model.startswith("alpha"):
        model = "a" + model[5:]
    if brand == "canon" and model.startswith("eos"):
        model = model[3:]
    if brand == "panasonic":
        for prefix in ["lumix", "dmc", "dc"]:
            if model.startswith(prefix):
                model = model[len(prefix):]
    return brand + "/" + model


def focal_range(model):
    match = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)\s*(?:mm\b)?", model)
    if match:
        low, high = map(float, match.groups())
        if 0 < low < high <= 3000:
            return low, high
    return None, None


def positive(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def texts(node, tag):
    return list(dict.fromkeys(x.text.strip() for x in node.findall(tag) if x.text and x.text.strip()))


def build(profile_root, lensfun_root):
    cameras, lenses, mounts, camera_aliases, lens_aliases = {}, {}, {}, {}, {}
    source_hash = hashlib.sha256()

    def index_camera(camera):
        for alias in [camera["model"], *camera["aliases"]]:
            camera_aliases.setdefault(camera_key(camera["brand"], alias), camera["id"])

    def index_lens(lens):
        for alias in [lens["model"], *lens["aliases"]]:
            for name in [alias, lens["brand"] + " " + alias]:
                lens_aliases.setdefault(normalized(name), set()).add(lens["id"])

    xml_files = sorted((lensfun_root / "data/db").glob("*.xml"))
    if not xml_files:
        raise ValueError("Lensfun database is missing; initialize the lensfun submodule")
    for path in xml_files:
        content = path.read_bytes()
        source_hash.update(path.name.encode() + b"\0" + content)
        root = ET.fromstring(content)
        for node in root.findall("mount"):
            name = node.findtext("name", "").strip()
            if name:
                mounts.setdefault(name, set()).update(texts(node, "compat"))
        for node in root.findall("camera"):
            brand = brand_name(node.findtext("maker", "").strip())
            models = texts(node, "model")
            variant = node.findtext("variant", "").strip()
            models = [m + (" " + variant if variant else "") for m in models]
            if not brand or not models:
                continue
            identifier = camera_key(brand, models[0])
            crop = positive(node.findtext("cropfactor"))
            camera = cameras.setdefault(identifier, dict(
                id=identifier, brand=brand, model=models[0], aliases=[], mounts=[],
                crop_factor=crop, sensor_width_mm=None, sensor_height_mm=None,
                profile_lenses=[], sources=["lensfun"]))
            camera["aliases"] = sorted(set(camera["aliases"] + models[1:]))
            camera["mounts"] = sorted(set(camera["mounts"] + texts(node, "mount")))
            # Only derive width/height when Lensfun actually specifies the aspect
            # ratio. Crop alone determines the diagonal, not the aspect ratio.
            ratio = node.findtext("aspect-ratio", "")
            if crop and re.fullmatch(r"\d+(?:\.\d+)?(?:[:/]\d+(?:\.\d+)?)?", ratio):
                parts = re.split(r"[:/]", ratio)
                aspect = float(parts[0]) / (float(parts[1]) if len(parts) > 1 else 1)
                if aspect > 0:
                    height = math.hypot(36, 24) / crop / math.sqrt(1 + aspect * aspect)
                    camera["sensor_width_mm"] = round(height * aspect, 3)
                    camera["sensor_height_mm"] = round(height, 3)
            index_camera(camera)
        for node in root.findall("lens"):
            brand = brand_name(node.findtext("maker", "").strip())
            models = texts(node, "model")
            if not models:
                continue
            identifier = "lensfun/" + normalized(brand) + "/" + normalized(models[0])
            low, high = focal_range(models[0])
            focal = node.find("focal")
            if focal is not None:
                low = positive(focal.get("min", focal.get("value"))) or low
                high = positive(focal.get("max", focal.get("value"))) or high
            lens = lenses.setdefault(identifier, dict(
                id=identifier, brand=brand, model=models[0], aliases=[], mounts=[],
                min_focal=low, max_focal=high, sources=["lensfun"]))
            lens["aliases"] = sorted(set(lens["aliases"] + models[1:]))
            lens["mounts"] = sorted(set(lens["mounts"] + texts(node, "mount")))
            index_lens(lens)

    # Root directories are camera brands; tooling, source data and VCS metadata
    # must never be mistaken for calibration profiles.
    paths = sorted(p for directory in profile_root.iterdir()
                   if directory.is_dir() and directory.name not in {"lensfun", "tools", "tests"}
                   and not directory.name.startswith(".") for p in directory.rglob("*.json"))
    for path in paths:
        content = path.read_bytes()
        source_hash.update(path.relative_to(profile_root).as_posix().encode() + b"\0" + content)
        profile = json.loads(content)
        if not isinstance(profile, dict) or "camera_brand" not in profile:
            continue
        for data in [profile, *({**profile, **c} for c in profile.get("compatible_settings", []) if isinstance(c, dict))]:
            brand, model, lens_model = (str(data.get(k) or "").strip() for k in ("camera_brand", "camera_model", "lens_model"))
            brand = brand_name(brand)
            if not brand or not model:
                continue
            identifier = camera_aliases.get(camera_key(brand, model), camera_key(brand, model))
            camera = cameras.setdefault(identifier, dict(
                id=identifier, brand=brand, model=model, aliases=[], mounts=[],
                crop_factor=None, sensor_width_mm=None, sensor_height_mm=None,
                profile_lenses=[], sources=[]))
            if model != camera["model"] and model not in camera["aliases"]:
                camera["aliases"].append(model)
            if "gyroflow" not in camera["sources"]:
                camera["sources"].append("gyroflow")
            index_camera(camera)
            if not lens_model:
                continue
            candidates = lens_aliases.get(normalized(lens_model), set())
            # An ambiguous name is kept camera-specific rather than merging two
            # lenses with different makers or mounts.
            lens_id = next(iter(candidates)) if len(candidates) == 1 else "gyroflow/" + identifier + "/" + normalized(lens_model)
            low, high = focal_range(lens_model)
            lens = lenses.setdefault(lens_id, dict(
                id=lens_id, brand="", model=lens_model, aliases=[], mounts=[],
                min_focal=low, max_focal=high, sources=["gyroflow"]))
            if lens_model != lens["model"] and lens_model not in lens["aliases"]:
                lens["aliases"].append(lens_model)
            if "gyroflow" not in lens["sources"]:
                lens["sources"].append("gyroflow")
            if lens_id not in camera["profile_lenses"]:
                camera["profile_lenses"].append(lens_id)

    for item in [*cameras.values(), *lenses.values()]:
        for key in ["aliases", "mounts", "sources", "profile_lenses"]:
            if key in item:
                item[key] = sorted(set(item[key]))
    revision = subprocess.run(["git", "-C", str(lensfun_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    return dict(schema_version=1, input_sha256=source_hash.hexdigest(), sources=[
        dict(name="gyroflow", url="https://github.com/gyroflow/lens_profiles", license="CC0-1.0"),
        dict(name="lensfun", url="https://github.com/lensfun/lensfun", revision=revision, license="CC-BY-SA-3.0"),
    ], mounts=[dict(name=name, compatible_with=sorted(compat)) for name, compat in sorted(mounts.items())],
        cameras=sorted(cameras.values(), key=lambda c: c["id"]), lenses=sorted(lenses.values(), key=lambda c: c["id"]))


def render(database):
    # One record per line keeps generated-data diffs reviewable without making
    # the entire catalogue one enormous line.
    sections = []
    for key, value in database.items():
        if key in {"mounts", "cameras", "lenses"}:
            rows = ",\n".join("    " + json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in value)
            sections.append(f"  {json.dumps(key)}: [\n{rows}\n  ]")
        else:
            sections.append(f"  {json.dumps(key)}: " + json.dumps(value, ensure_ascii=False))
    return "{\n" + ",\n".join(sections) + "\n}\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--profiles", type=Path, default=default_root)
    parser.add_argument("--lensfun", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    database = build(args.profiles, args.lensfun or args.profiles / "lensfun")
    output = args.output or args.profiles / "camera_database.json"
    rendered = render(database)
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != rendered:
            parser.exit(1, "camera_database.json is out of date; regenerate it\n")
    else:
        output.write_text(rendered, encoding="utf-8")
    print(f"{len(database['cameras'])} cameras, {len(database['lenses'])} lenses, {len(database['mounts'])} mounts")


if __name__ == "__main__":
    main()
