#!/usr/bin/env python3
"""Normalize only profile identity fields that resolve to one catalog identity.

Run without --apply to review the proposed changes and unresolved examples.
The camera catalog is the authority for canonical names and its explicit aliases.
An optional curated registry may provide exact, qualified profile mappings using
profile_camera_aliases and profile_lens_aliases arrays.
"""

import argparse
import collections
import json
import pathlib
import re
import sys

from profile_identities import CatalogIndex, key, profile_files


PROFILE_FIELDS = {"camera_brand", "camera_model", "lens_model"}


def top_level_string_spans(text):
    """Return JSON-decoded root string values with source-token offsets."""
    decoder = json.JSONDecoder()
    i = 0
    while i < len(text) and text[i].isspace():
        i += 1
    if i == len(text) or text[i] != "{":
        raise ValueError("profile root must be a JSON object")
    i += 1
    spans = {}
    while True:
        while i < len(text) and (text[i].isspace() or text[i] == ","):
            i += 1
        if i >= len(text) or text[i] == "}":
            break
        name, name_end = decoder.raw_decode(text, i)
        if not isinstance(name, str):
            raise ValueError("profile object has a non-string key")
        i = name_end
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text) or text[i] != ":":
            raise ValueError("invalid JSON object key separator")
        i += 1
        while i < len(text) and text[i].isspace():
            i += 1
        start = i
        value, end = decoder.raw_decode(text, i)
        if name in PROFILE_FIELDS and isinstance(value, str):
            spans[name] = (value, start, end)
        i = end
        while i < len(text) and text[i].isspace():
            i += 1
        if i < len(text) and text[i] == "}":
            break
        if i >= len(text) or text[i] != ",":
            raise ValueError("invalid JSON object separator")
    return spans


def choose(candidates):
    if len(candidates) == 1:
        return next(iter(candidates)), "resolved"
    if candidates:
        return None, "ambiguous"
    return None, "unmatched"


def lens_review_reason(raw, candidates):
    if candidates:
        return "multiple catalog matches"
    label = key(raw)
    if re.fullmatch(r"\d+(?:\.\d+)?\s*(?:-\s*\d+(?:\.\d+)?\s*)?(?:mm)?", label):
        return "numeric or focal-length label"
    if label in {"wide", "max wide", "ultrawide", "ultra wide", "linear", "narrow", "superview", "main"} or re.fullmatch(r"\d+(?:\.\d+)?\s*x", label):
        return "view or zoom label"
    if label.endswith((".json", ".gyroflow")):
        return "profile reference"
    return "no catalog match"


def add_review(groups, identity, reason, candidates, path):
    group = identity, reason, tuple(sorted(candidates))
    groups.setdefault(group, []).append(path.as_posix())


def review_rows(groups):
    return [
        {"identity": identity, "reason": reason, "candidates": candidates, "count": len(paths), "profiles": sorted(paths)}
        for (identity, reason, candidates), paths in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def replace_root_fields(text, obj, edits, path_label="profile"):
    spans = top_level_string_spans(text)
    replacements = []
    for name, value in edits.items():
        if name not in spans:
            raise ValueError(f"{path_label} is missing root value {name}")
        old, start, end = spans[name]
        if old != obj.get(name):
            raise ValueError(f"{path_label} changed while being read")
        token = json.dumps(value, ensure_ascii="\\u" in text[start:end])
        replacements.append((start, end, token))

    updated = text
    for start, end, token in sorted(replacements, reverse=True):
        updated = updated[:start] + token + updated[end:]
    return updated


def main():
    root = pathlib.Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=pathlib.Path, default=root / "camera_database.json")
    parser.add_argument("--registry", type=pathlib.Path, default=root / "catalog" / "curated_identities.json")
    parser.add_argument("--report", type=pathlib.Path, help="write unresolved identities and their profile paths to a JSON file outside the profile checkout")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write uniquely resolved identity fields")
    mode.add_argument("--check", action="store_true", help="fail if a uniquely resolvable profile value needs normalization")
    args = parser.parse_args()
    if args.report and (args.report.resolve() == root or root in args.report.resolve().parents):
        parser.error("--report must be outside the checkout so it cannot enter a profile release")

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    registry = json.loads(args.registry.read_text(encoding="utf-8")) if args.registry.exists() else {}
    index = CatalogIndex(catalog["cameras"], catalog["lenses"], registry)

    counts = collections.Counter()
    unresolved_cameras = collections.Counter()
    unresolved_lenses = collections.Counter()
    camera_review, lens_review = {}, {}
    file_count = changed_files = 0

    for path in profile_files(root):
        try:
            text = path.read_bytes().decode("utf-8")
            obj = json.loads(text)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            print(f"Cannot inspect {path.relative_to(root)}: {error}", file=sys.stderr)
            return 2
        if not isinstance(obj, dict):
            continue
        file_count += 1
        brand = obj.get("camera_brand", "")
        model = obj.get("camera_model", "")
        lens_model = obj.get("lens_model", "")
        edits = {}

        if isinstance(brand, str) and isinstance(model, str) and brand and model:
            candidates = index.camera_candidates(brand, model)
            target, status = choose(candidates)
            counts[f"camera_{status}"] += 1
            if target:
                if (brand, model) != target:
                    edits["camera_brand"], edits["camera_model"] = target
            else:
                unresolved_cameras[(brand, model)] += 1
                if args.report:
                    reason = "multiple catalog matches" if candidates else "no catalog match"
                    add_review(camera_review, (brand, model), reason, candidates, path.relative_to(root))

        if isinstance(lens_model, str) and lens_model:
            candidates, setting = index.lens_observation(lens_model)
            target, status = choose(candidates)
            counts[f"lens_{status}"] += 1
            if target and lens_model != target + setting:
                edits["lens_model"] = target + setting
            elif not target:
                unresolved_lenses[lens_model] += 1
                if args.report:
                    add_review(lens_review, lens_model, lens_review_reason(lens_model, candidates), candidates, path.relative_to(root))

        if not edits:
            continue
        changed_files += 1
        counts["changed_camera_pairs"] += int("camera_brand" in edits)
        counts["changed_lens_names"] += int("lens_model" in edits)
        updated = replace_root_fields(text, obj, edits, str(path.relative_to(root)))

        if args.apply:
            checked = json.loads(updated)
            expected = dict(obj)
            expected.update(edits)
            if checked != expected:
                raise ValueError(f"unexpected profile data change in {path.relative_to(root)}")
            path.write_bytes(updated.encode("utf-8"))

    print(f"Profiles scanned: {file_count}; correctable files: {changed_files}; apply={args.apply}; check={args.check}")
    if args.report:
        report = {"profiles_scanned": file_count, "counts": dict(sorted(counts.items())),
                  "unresolved_camera_identities": review_rows(camera_review), "unresolved_lens_labels": review_rows(lens_review)}
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name in sorted(counts):
        print(f"{name}: {counts[name]}")
    print("Unresolved camera identities (top 12):")
    for (brand, model), count in unresolved_cameras.most_common(12):
        print(f"  {count:4}  {brand} / {model}")
    print("Unresolved lens names (top 12):")
    for model, count in unresolved_lenses.most_common(12):
        print(f"  {count:4}  {model}")
    return 1 if args.check and changed_files else 0


if __name__ == "__main__":
    sys.exit(main())
