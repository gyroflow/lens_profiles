#!/usr/bin/env python3

import argparse
import json
import math
import pathlib
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

from scripts.profile_identities import CatalogIndex, identifies_lens_model, key, lens_name, profile_files


# Pin the release input so one build cannot mix revisions between XML downloads.
LENSFUN_REVISION = "a5e2caeb6b646b7a0bb9ed76033b56f8c0499e86"
LENSFUN_API = f"https://api.github.com/repos/lensfun/lensfun/contents/data/db?ref={LENSFUN_REVISION}"
LENSFUN_RAW = f"https://raw.githubusercontent.com/lensfun/lensfun/{LENSFUN_REVISION}/data/db/{{name}}"


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def brand_name(value):
    normalized = key(value).replace(".", "")
    names = {
        "activeon": "ACTIVEON",
        "apple": "Apple",
        "akaso": "AKASO",
        "arri": "ARRI",
        "asus": "Asus",
        "asahi optical co,ltd": "Pentax",
        "betafpv": "BetaFPV",
        "blackmagic": "Blackmagic",
        "canon": "Canon",
        "casio computer co,ltd": "Casio",
        "casio computer co,ltd.": "Casio",
        "cooau": "COOAU",
        "dji": "DJI",
        "eastman kodak company": "Kodak",
        "eken": "EKEN",
        "feiyu-tech": "Feiyu Tech",
        "fimi": "FIMI",
        "fufifilm": "Fujifilm",
        "fujifilm": "Fujifilm",
        "gitup": "GitUp",
        "gopro": "GoPro",
        "google": "Google",
        "huawei": "Huawei",
        "iqoo": "IQOO",
        "iqoo 9": "IQOO",
        "insta360": "Insta360",
        "lamax": "LAMAX",
        "leica": "Leica",
        "leica camera ag": "Leica",
        "lg mobile": "LG",
        "lge": "LG",
        "mi": "Xiaomi",
        "niceboy": "Niceboy",
        "nikon": "Nikon",
        "nikon corporation": "Nikon",
        "olympus": "Olympus",
        "olympus corporation": "Olympus",
        "olympus imaging corp": "Olympus",
        "olympus optical co,ltd": "Olympus",
        "oneplus": "OnePlus",
        "oppo": "OPPO",
        "panasonic": "Panasonic",
        "pentax": "Pentax",
        "pentax corporation": "Pentax",
        "red": "RED",
        "realme": "REALME",
        "ricoh": "Ricoh",
        "runcam": "RunCam",
        "samsung": "Samsung",
        "samsung techwin": "Samsung",
        "samsung techwin co": "Samsung",
        "sjcam": "SJCam",
        "sony": "Sony",
        "volla": "Volla",
        "vivo": "Vivo",
        "wolfang": "Wolfang",
        "wolfgang": "Wolfang",
        "xiaomi": "Xiaomi",
    }
    return names.get(normalized, clean(value))


def camera_brand_name(brand, model):
    normalized = key(brand).replace(".", "")
    if normalized == "ricoh imaging company, ltd":
        return "Pentax" if re.match(r"^(K-|K[A-Z]|KP$|KF$)", clean(model)) else "Ricoh"
    return brand_name(brand)


def model_name(brand, model):
    model = clean(model).replace("CInema", "Cinema")
    if key(brand) == "blackmagic":
        model = re.sub(r"\b([46])k\b", lambda match: f"{match.group(1)}K", model, flags=re.IGNORECASE)
    return model


def first_float(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def sensor_size(crop_factor):
    if crop_factor is None or not math.isfinite(crop_factor) or crop_factor <= 0:
        return None
    if crop_factor <= 0.8:
        return "Medium format"
    if crop_factor <= 1.1:
        return "Full frame"
    if crop_factor <= 1.35:
        return "APS-H"
    if crop_factor <= 1.7:
        return "APS-C"
    if crop_factor <= 2.2:
        return "Micro Four Thirds"
    if crop_factor <= 3.0:
        return "1-inch"
    if crop_factor <= 4.8:
        return "1/1.7-inch"
    if crop_factor <= 6.2:
        return "1/2.3-inch"
    return "Small sensor"


def child_texts(node, tag):
    return [clean(x.text) for x in node.findall(tag) if clean(x.text)]


def preferred_model(node):
    models = [(clean(x.text), x.attrib.get("lang", "")) for x in node.findall("model") if clean(x.text)]
    if not models:
        return "", []

    preferred = next((text for text, lang in models if lang == "en"), models[0][0])
    aliases = []
    seen = {key(preferred)}
    for text, _lang in models:
        if key(text) not in seen:
            aliases.append(text)
            seen.add(key(text))
    return preferred, aliases


def extra_camera_aliases(brand, model):
    aliases = []
    if key(brand) == "sony":
        match = re.fullmatch(r"Alpha\s+(\d+)([A-Z]*)?(?:\s+([0-9IVX]+[A-Z]?))?", clean(model))
        if match:
            number, series, generation = match.groups()
            aliases.append(f"a{number}{series or ''}{generation or ''}")
    if key(brand) == "panasonic" and re.fullmatch(r"(?:DMC|DC)-[A-Z]+[A-Z0-9]*\d[A-Z0-9]*", model):
        body = model.split("-", 1)[1]
        aliases.extend([body, "Lumix " + body])
    elif key(brand) == "canon" and re.fullmatch(r"EOS (?:R|C)\d.*", model):
        aliases.append(model[4:])
    elif key(brand) == "fujifilm" and model.startswith("X-"):
        aliases.append("X" + model[2:])
    return aliases


def merge_values(target, values):
    existing = {key(x) for x in target}
    for value in values:
        if value and key(value) not in existing:
            target.append(value)
            existing.add(key(value))


def merge_camera(cameras, camera):
    original_brand = clean(camera["brand"])
    camera["brand"] = camera_brand_name(camera["brand"], camera["model"])
    camera["model"] = model_name(camera["brand"], camera["model"])
    if not camera["brand"] or not camera["model"]:
        return
    if original_brand and key(original_brand) != key(camera["brand"]):
        camera.setdefault("brand_aliases", []).append(original_brand)

    camera_key = key(camera["brand"]), key(camera["model"])
    existing = cameras.setdefault(camera_key, {
        "brand": camera["brand"],
        "model": camera["model"],
        "brand_aliases": [],
        "aliases": [],
        "mounts": [],
        "compatible_mounts": [],
        "sensor_size": None,
        "crop_factor": None,
        "source": [],
    })
    merge_values(existing["brand_aliases"], camera.get("brand_aliases", []))
    merge_values(existing["aliases"], camera.get("aliases", []))
    merge_values(existing["mounts"], camera.get("mounts", []))
    merge_values(existing["compatible_mounts"], camera.get("compatible_mounts", []))
    merge_values(existing["source"], camera.get("source", []))
    if camera.get("source_url") and not existing.get("source_url"):
        existing["source_url"] = camera["source_url"]
    if "fixed_lens" in camera:
        if not isinstance(camera["fixed_lens"], bool):
            raise ValueError(f"Expected a boolean fixed_lens for {camera_key}")
        existing["fixed_lens"] = camera["fixed_lens"]
    if existing["crop_factor"] is None:
        existing["crop_factor"] = camera.get("crop_factor")
    if existing["sensor_size"] is None:
        existing["sensor_size"] = camera.get("sensor_size") or sensor_size(existing["crop_factor"])


def merge_lens(lenses, lens):
    lens["brand"] = brand_name(lens["brand"])
    if not lens["model"]:
        return

    lens_key = (key(lens["brand"]), key(lens["model"]), tuple(sorted(key(x) for x in lens.get("mounts", []))))
    existing = lenses.setdefault(lens_key, {
        "brand": lens["brand"],
        "model": lens["model"],
        "mounts": [],
        "aliases": [],
        "crop_factor": None,
        "source": [],
    })
    merge_values(existing["aliases"], [label for label in lens.get("aliases", []) if identifies_lens_model(label)])
    merge_values(existing["mounts"], lens.get("mounts", []))
    merge_values(existing["source"], lens.get("source", []))
    if lens.get("source_url") and not existing.get("source_url"):
        existing["source_url"] = lens["source_url"]
    if existing["crop_factor"] is None:
        existing["crop_factor"] = lens.get("crop_factor")


def github_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "gyroflow-camera-database"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def github_text(url):
    request = urllib.request.Request(url, headers={"User-Agent": "gyroflow-camera-database"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def lensfun_xml_files(lensfun_db):
    if lensfun_db:
        paths = sorted(pathlib.Path(lensfun_db).glob("*.xml"))
        if not paths:
            raise ValueError(f"No Lensfun XML files found in {lensfun_db}")
        yield from paths
        return

    files = sorted(github_json(LENSFUN_API), key=lambda item: item.get("name", ""))
    for item in files:
        name = item.get("name", "")
        if name.endswith(".xml") and not name.endswith((".dtd", ".xsd")):
            yield name


def parse_lensfun_file(item, cameras, lenses, mount_compat=None):
    if isinstance(item, pathlib.Path):
        text = item.read_text(encoding="utf-8")
    else:
        text = github_text(LENSFUN_RAW.format(name=item))

    root = ET.fromstring(text)
    if mount_compat is None:
        mount_compat = {}

    for mount in root.findall("mount"):
        names = child_texts(mount, "name")
        if not names:
            continue
        mount_compat[key(names[0])] = child_texts(mount, "compat")

    # Lensfun's generic file describes optical projections and crop-factor
    # placeholders. Its mount definitions are useful; its records are not hardware.
    if pathlib.Path(item).name == "generic.xml":
        return

    for node in root.findall("camera"):
        brand = clean((node.findtext("maker") or ""))
        model, aliases = preferred_model(node)
        merge_values(aliases, extra_camera_aliases(brand, model))
        mounts = child_texts(node, "mount")
        compatible_mounts = []
        for mount in mounts:
            merge_values(compatible_mounts, mount_compat.get(key(mount), []))

        merge_camera(cameras, {
            "brand": brand,
            "model": model,
            "aliases": aliases,
            "mounts": mounts,
            "compatible_mounts": compatible_mounts,
            "sensor_size": sensor_size(first_float(node.findtext("cropfactor"))),
            "crop_factor": first_float(node.findtext("cropfactor")),
            "source": ["lensfun"],
        })

    for node in root.findall("lens"):
        brand = clean((node.findtext("maker") or ""))
        model, aliases = preferred_model(node)
        # Lensfun uses the same translated "fixed lens" label for many different optics.
        # Its untranslated model identifies the supported body and any converter.
        if key(model).startswith("fixed lens"):
            model = next((clean(item.text) for item in node.findall("model") if not item.get("lang")), model)
            aliases = []
        merge_lens(lenses, {
            "brand": brand,
            "model": model,
            "aliases": aliases,
            "mounts": child_texts(node, "mount"),
            "crop_factor": first_float(node.findtext("cropfactor")),
            "source": ["lensfun"],
        })


def parse_lensfun(lensfun_db, cameras, lenses):
    # Mount definitions can live in a different XML file from the camera.
    mount_compat = {}
    for item in lensfun_xml_files(lensfun_db):
        parse_lensfun_file(item, cameras, lenses, mount_compat)
    for camera in cameras.values():
        # Lensfun matches only the declared direct compatibility list. Following
        # links transitively through Generic would incorrectly include every mount.
        camera["compatible_mounts"] = []
        for mount in camera["mounts"]:
            merge_values(camera["compatible_mounts"], mount_compat.get(key(mount), []))


def parse_curated_identities(path, cameras, lenses):
    """Merge explicitly sourced identity rows without deriving them from profiles."""
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry.get("version") != 1:
        raise ValueError(f"Unsupported curated identity registry version in {path}")

    source_urls = set()
    for kind, merge in (("cameras", merge_camera), ("lenses", merge_lens)):
        for row in registry.get(kind, []):
            brand = clean(row.get("brand", ""))
            model = clean(row.get("model", ""))
            source_url = clean(row.get("source_url", ""))
            if not brand or not model or not source_url.startswith("https://"):
                raise ValueError(f"Curated {kind[:-1]} requires brand, model, and HTTPS source_url: {row!r}")
            aliases = row.get("aliases", [])
            if not isinstance(aliases, list) or any(not isinstance(alias, str) or not clean(alias) for alias in aliases):
                raise ValueError(f"Curated aliases must be nonempty strings: {row!r}")
            item = dict(row)
            item["brand"] = brand
            item["model"] = model
            item["source"] = ["curated"]
            merge(cameras if kind == "cameras" else lenses, item)
            source_urls.add(source_url)

    for field in ("profile_camera_aliases", "profile_lens_aliases", "lens_profile_aliases"):
        source_urls.update(row["source_url"] for row in registry.get(field, []))

    return registry, sorted(source_urls)


def parse_profiles(path, cameras, lenses, registry=None):
    """Mark trusted catalog entries observed in historical profiles."""
    stats = {"profile_files": 0, "matched_files": 0}
    index = CatalogIndex(cameras.values(), lenses.values(), registry)
    lens_entries = {}
    for lens in lenses.values():
        lens_entries.setdefault(lens_name(lens), []).append(lens)
    if not path or not path.exists():
        return stats
    for file in profile_files(path):
        profile = json.loads(file.read_bytes())
        if not isinstance(profile, dict):
            continue
        brand, model = profile.get("camera_brand"), profile.get("camera_model")
        if not isinstance(brand, str) or not isinstance(model, str) or not brand or not model:
            continue
        stats["profile_files"] += 1
        matches = index.camera_candidates(brand, model)
        if len(matches) == 1:
            maker, body = next(iter(matches))
            merge_values(cameras[key(maker), key(body)]["source"], ["gyroflow"])
            stats["matched_files"] += 1
        label = profile.get("lens_model")
        if isinstance(label, str) and label:
            matches, _setting = index.lens_observation(label)
            if len(matches) == 1:
                for lens in lens_entries[next(iter(matches))]:
                    merge_values(lens["source"], ["gyroflow"])
    return stats


def finalize(cameras, lenses):
    camera_list = sorted(cameras.values(), key=lambda x: (key(x["brand"]), key(x["model"])))
    lens_list = sorted(lenses.values(), key=lambda x: (key(x["brand"]), key(x["model"])))
    brand_spellings = {}
    for entry in camera_list + lens_list:
        if entry["brand"]:
            spellings = brand_spellings.setdefault(key(entry["brand"]), {})
            spellings[entry["brand"]] = spellings.get(entry["brand"], 0) + 1
    canonical_brands = {
        brand_key: sorted(spellings, key=lambda name: (-spellings[name], name.isupper(), name))[0]
        for brand_key, spellings in brand_spellings.items()
    }
    for entry in camera_list + lens_list:
        if entry["brand"]:
            entry["brand"] = canonical_brands[key(entry["brand"])]
    return camera_list, lens_list


def main():
    repo_root = pathlib.Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--lens-profiles", type=pathlib.Path, default=repo_root)
    parser.add_argument("--lensfun-db", type=pathlib.Path)
    parser.add_argument("--curated-identities", type=pathlib.Path, default=repo_root / "catalog" / "curated_identities.json")
    parser.add_argument("--output", type=pathlib.Path, default=repo_root / "camera_database.json")
    args = parser.parse_args()

    cameras = {}
    lenses = {}

    parse_lensfun(args.lensfun_db, cameras, lenses)
    registry, curated_source_urls = parse_curated_identities(args.curated_identities, cameras, lenses)
    profile_stats = parse_profiles(args.lens_profiles, cameras, lenses, registry)
    camera_list, lens_list = finalize(cameras, lenses)

    payload = {
        "version": 1,
        "sources": [{
            "name": "Lensfun camera and lens database",
            "url": f"https://github.com/lensfun/lensfun/tree/{LENSFUN_REVISION}/data/db",
            "revision": LENSFUN_REVISION,
            "license": "CC BY-SA 3.0",
            "license_file": "LENSFUN-DATABASE-LICENSE.txt",
        }] + [{"name": "Curated manufacturer identities", "url": url} for url in curated_source_urls],
        "cameras": camera_list,
        "lenses": lens_list,
    }
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {args.output} ({len(camera_list)} cameras, {len(lens_list)} lenses; {profile_stats['matched_files']}/{profile_stats['profile_files']} profile files matched existing identities)")


if __name__ == "__main__":
    sys.exit(main())
