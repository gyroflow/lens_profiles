"""Match historical labels against sourced hardware names, preserving ambiguity."""

from collections import defaultdict
import re


def key(value):
    return " ".join(value.split()).casefold()


def compact(value):
    return "".join(key(value).split())


def lens_name(entry):
    brand, model = entry["brand"], entry["model"]
    return model if key(model).startswith(key(brand)) else f"{brand} {model}"


def lens_key(value):
    """Normalize typographical differences without dropping optical specifications."""
    value = re.sub(r"(?<![a-z0-9])f\s*/?\s*(\d+(?:\.\d+)?)(?![a-z0-9])", r"f/\1", key(value))
    return re.sub(r"\b(ef|rf)\s+(?=\d)", r"\1", value)


def identifies_lens_model(label):
    # Lensfun also uses EXIF descriptions such as "35mm f/2" as aliases.
    # A focal range, aperture or recording mode alone cannot identify a lens.
    words = re.findall(r"[^\W\d_]+", key(label))
    generic = {"mm", "cm", "f", "t", "x", "fixed", "lens", "standard", "prime",
               "wide", "angle", "ultra", "ultrawide", "linear", "zoom", "telephoto", "macro"}
    return any(word not in generic for word in words)


FOCAL_SETTING = re.compile(r"(?:\s+|\s*@\s*)\d{1,3}(?:\.\d+)?\s*mm\s*$", re.IGNORECASE)


def profile_files(root):
    for path in sorted(root.rglob("*.json")):
        parts = path.relative_to(root).parts
        if ".git" not in parts and "catalog" not in parts and path.name != "camera_database.json":
            yield path


def reviewed(row):
    return bool({"lensfun", "curated"}.intersection(row.get("source", [])))


class CatalogIndex:
    """Keep every matching identity so collisions never resolve by insertion order."""

    def __init__(self, cameras, lenses, registry=None):
        self.camera_names = {}
        self.camera_aliases = defaultdict(set)
        self.camera_spacing = defaultdict(set)
        self.lens_names = {}
        self.lens_aliases = defaultdict(set)
        self.lens_typography = defaultdict(set)
        for camera in cameras:
            if not reviewed(camera):
                continue
            brand, model = name = (camera["brand"], camera["model"])
            self.camera_names[key(brand), key(model)] = name
            for maker in [brand, *camera.get("brand_aliases", [])]:
                for label in [model, *camera.get("aliases", [])]:
                    self.camera_aliases[key(maker), key(label)].add(name)
                    self.camera_spacing[key(maker), compact(label)].add(name)
        for lens in lenses:
            if not reviewed(lens):
                continue
            name = lens_name(lens)
            primary = key(name)
            self.lens_names[primary] = min(self.lens_names.get(primary, name), name)
            # Lensfun's model field can include the manufacturer or an unbranded model number.
            # Only a unique full model or a sourced alias can identify a lens.
            labels = {alias for alias in lens.get("aliases", []) if identifies_lens_model(alias)}
            labels.add(name)
            label = lens["model"]
            prefix = lens["brand"] + " "
            if key(label).startswith(key(lens["brand"]) + " "):
                label = label[len(prefix):]
            if identifies_lens_model(label):
                labels.add(label)
            for label in labels:
                if label.strip():
                    self.lens_aliases[key(label)].add(name)
                    self.lens_typography[lens_key(label)].add(name)
        if registry:
            self._add_profile_aliases(registry)

    def _add_profile_aliases(self, registry):
        for kind in ("camera", "lens"):
            rows = list(registry.get(f"profile_{kind}_aliases", []))
            if kind == "lens":
                rows.extend(registry.get("lens_profile_aliases", []))
            for row in rows:
                model = key(row["raw_model"])
                if not model or not row.get("source_url", "").startswith("https://") or not row.get("source_profile_refs"):
                    raise ValueError(f"Expected a sourced historical {kind} mapping: {row}")
                if kind == "camera":
                    raw = key(row["raw_brand"]), model
                    target = self.camera_names.get((key(row["target_brand"]), key(row["target_model"])))
                    aliases = self.camera_aliases[raw]
                else:
                    name = lens_name({"brand": row["target_brand"], "model": row["target_model"]})
                    target = self.lens_names.get(key(name))
                    aliases = self.lens_aliases[model]
                if not target or aliases - {target}:
                    raise ValueError(f"Missing or conflicting target for historical {kind} mapping: {row}")
                aliases.add(target)

    def camera_candidates(self, brand, model):
        pair = key(brand), key(model)
        if pair in self.camera_names:
            return {self.camera_names[pair]}
        return self.camera_aliases.get(pair) or self.camera_spacing.get((pair[0], compact(model)), set())

    def lens_candidates(self, model):
        primary = key(model)
        if primary in self.lens_names:
            return {self.lens_names[primary]}
        matches = self.lens_aliases.get(primary) or self.lens_typography.get(lens_key(model), set())
        return {self.lens_names[key(name)] for name in matches}

    def lens_observation(self, label):
        """Return catalog candidates and the exact suffix describing the capture, if any."""
        whole = self.lens_candidates(label)
        if whole:
            return whole, ""
        setting = FOCAL_SETTING.search(label)
        if setting:
            prefix = label[:setting.start()]
            matches = self.lens_candidates(prefix)
            if matches:
                return matches, label[setting.start():]
        return set(), ""
