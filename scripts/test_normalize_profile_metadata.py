import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import normalize_profile_metadata as normalizer
from profile_identities import CatalogIndex, lens_name


class ProfileMetadataNormalizationTests(unittest.TestCase):
    def test_review_retains_ambiguous_candidates_and_original_profile_paths(self):
        groups = {}
        for name in ["b.json", "a.json"]:
            normalizer.add_review(groups, "24mm", normalizer.lens_review_reason("24mm", set()), set(), pathlib.Path(name))
        normalizer.add_review(groups, "24mm", normalizer.lens_review_reason("24mm", {"A", "B"}), {"B", "A"}, pathlib.Path("c.json"))
        numeric, ambiguous = normalizer.review_rows(groups)
        self.assertEqual(numeric["profiles"], ["a.json", "b.json"])
        self.assertEqual(numeric["reason"], "numeric or focal-length label")
        self.assertEqual(ambiguous["reason"], "multiple catalog matches")
        self.assertEqual(ambiguous["candidates"], ("A", "B"))

    def test_catalog_alias_resolves_to_one_canonical_camera(self):
        catalog = {
            "cameras": [{
                "brand": "Sony",
                "model": "Alpha 7 III",
                "brand_aliases": [],
                "aliases": ["ILCE-7M3"],
                "source": ["lensfun"],
            }, {
                "brand": "Sony",
                "model": "Alpha 7 IV",
                "brand_aliases": [],
                "aliases": ["ILCE-7M4"],
                "source": ["gyroflow"],
            }],
            "lenses": [],
        }
        index = CatalogIndex(catalog["cameras"], catalog["lenses"])
        self.assertEqual(index.camera_candidates("Sony", "ILCE-7M3"), {("Sony", "Alpha 7 III")})
        self.assertEqual(index.camera_candidates("Sony", "Alpha7III"), {("Sony", "Alpha 7 III")})
        self.assertFalse(index.camera_candidates("Sony", "ILCE-7M4"))

    def test_ambiguous_alias_is_not_selected(self):
        self.assertEqual(
            normalizer.choose({("Sony", "Model A"), ("Sony", "Model B")}),
            (None, "ambiguous"),
        )

    def test_profile_scan_excludes_generated_catalog_and_working_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "Sony").mkdir()
            (root / "catalog").mkdir()
            (root / ".git").mkdir()
            (root / "Sony" / "camera.json").write_text("{}", encoding="utf-8")
            (root / "catalog" / "curated_identities.json").write_text("{}", encoding="utf-8")
            (root / ".git" / "object.json").write_text("{}", encoding="utf-8")
            (root / "camera_database.json").write_text("{}", encoding="utf-8")
            self.assertEqual(
                {path.relative_to(root).as_posix() for path in normalizer.profile_files(root)},
                {"Sony/camera.json"},
            )

    def test_lens_display_does_not_repeat_maker_prefix(self):
        self.assertEqual(
            lens_name({"brand": "Canon", "model": "Canon EF 50mm f/1.4 USM"}),
            "Canon EF 50mm f/1.4 USM",
        )
        self.assertEqual(
            lens_name({"brand": "Nikon", "model": "Nikkor Z 24-70mm f/4 S"}),
            "Nikon Nikkor Z 24-70mm f/4 S",
        )

    def test_f_number_slash_normalizes_only_fully_identified_lens(self):
        catalog = {
            "cameras": [],
            "lenses": [{
                "brand": "Sony",
                "model": "FE 35mm f/1.8",
                "aliases": [],
                "source": ["lensfun"],
            }],
        }
        index = CatalogIndex(catalog["cameras"], catalog["lenses"])
        candidates = index.lens_candidates("Sony FE 35mm F1.8")
        self.assertEqual(candidates, {"Sony FE 35mm f/1.8"})
        self.assertFalse(index.lens_candidates("35mm F1.8"))
        self.assertFalse(index.lens_candidates("Sony FE 35mm F1.8 GM"))

    def test_only_identity_string_tokens_change_and_crlf_survives(self):
        source = (
            '{\r\n'
            '  "camera_brand": "Sony",\r\n'
            '  "camera_model": "ILCE-7M3",\r\n'
            '  "lens_model": "old lens",\r\n'
            '  "calibration": {"focal_length": 1.2300, "coeffs": [1e-7, -2.5000]},\r\n'
            '  "camera_matrix": [1.0, 0.000001, 3]\r\n'
            '}\r\n'
        )
        original = json.loads(source)
        updated = normalizer.replace_root_fields(source, original, {
            "camera_model": "Alpha 7 III",
            "lens_model": "Canon EF 50mm f/1.4 USM",
        })
        result = json.loads(updated)
        self.assertEqual(result["camera_model"], "Alpha 7 III")
        self.assertEqual(result["lens_model"], "Canon EF 50mm f/1.4 USM")
        self.assertEqual(result["camera_brand"], original["camera_brand"])
        self.assertEqual(result["calibration"], original["calibration"])
        self.assertEqual(result["camera_matrix"], original["camera_matrix"])
        self.assertIn('"focal_length": 1.2300', updated)
        self.assertIn('1e-7, -2.5000', updated)
        self.assertIn('"camera_matrix": [1.0, 0.000001, 3]', updated)
        self.assertIn("\r\n", updated)
        self.assertNotIn("\n", updated.replace("\r\n", ""))


if __name__ == "__main__":
    unittest.main()
