import json
import pathlib
import tempfile
import unittest

import build_camera_database as db


class CameraDatabaseTests(unittest.TestCase):
    def test_optical_specs_cannot_supply_a_missing_lens_identity(self):
        lenses = {}
        db.merge_lens(lenses, {
            "brand": "Example", "model": "55-110mm f/4.5", "source": ["lensfun"],
            "aliases": ["35mm f/2", "X-Series 55-110"],
        })
        lens, = lenses.values()
        self.assertEqual(lens["aliases"], ["X-Series 55-110"])
        index = db.CatalogIndex([], lenses.values())
        for label in ("35mm f/2", "55-110mm f/4.5", "55-110mm f/4.5 70mm"):
            self.assertEqual(index.lens_observation(label), (set(), ""))
        self.assertEqual(index.lens_candidates("Example 55-110mm f/4.5"), {"Example 55-110mm f/4.5"})

    def test_builtin_optics_keep_body_names_and_interchangeable_lenses_keep_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "lenses.xml"
            path.write_text("""<lensdatabase>
              <lens><maker>Example</maker><mount>A</mount><model>Compact A Standard</model><model lang="en">fixed lens</model></lens>
              <lens><maker>Example</maker><mount>B</mount><model>Compact B Standard</model><model lang="en">fixed lens</model></lens>
              <lens><maker>Example</maker><mount>C</mount><model>Fifty XR</model><model lang="en">50mm XR</model></lens>
            </lensdatabase>""")
            lenses = {}
            db.parse_lensfun_file(path, {}, lenses)
            index = db.CatalogIndex([], lenses.values())
            self.assertEqual(index.lens_candidates("Fifty XR"), {"Example 50mm XR"})
            self.assertFalse(index.lens_candidates("fixed lens"))
            self.assertNotEqual(index.lens_candidates("Example Compact A Standard"), index.lens_candidates("Example Compact B Standard"))

    def test_invalid_crop_factors_are_unknown(self):
        for value in ('nan', 'inf', '-inf', '0', '-1', None, 'bad'):
            self.assertIsNone(db.first_float(value))
        self.assertEqual(db.first_float('1.5'), 1.5)

    def test_medium_format_is_not_classified_as_full_frame(self):
        self.assertEqual(db.sensor_size(0.79), 'Medium format')
        self.assertEqual(db.sensor_size(0.8), 'Medium format')
        self.assertEqual(db.sensor_size(1.0), 'Full frame')

    def test_z_cam_mft_mounts_match_catalog_lens_mounts(self):
        database = json.loads((pathlib.Path(__file__).parent / 'camera_database.json').read_text())
        lens_mounts = {mount for lens in database['lenses'] for mount in lens['mounts']}
        cameras = {
            camera['model']: camera for camera in database['cameras']
            if camera['brand'] == 'Z CAM' and camera['model'] in {'E2', 'E2-M4'}
        }
        self.assertEqual(set(cameras), {'E2', 'E2-M4'})
        for camera in cameras.values():
            self.assertIn('Micro 4/3 System', camera['mounts'])
            self.assertTrue(set(camera['mounts']) & lens_mounts)

    def test_unknown_profile_does_not_create_camera_from_crop_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / 'profile.json').write_text('''{
              "camera_brand": "Example", "camera_model": "Body",
              "lens_model": "Lens with speed booster", "crop_factor": 0.75
            }''')
            cameras = {}
            stats = db.parse_profiles(root, cameras, {})
            self.assertEqual(cameras, {})
            self.assertEqual(stats['matched_files'], 0)

    def test_camera_match_preserves_exact_identity_and_rejects_ambiguous_aliases(self):
        cameras = [
            {"brand": "Sony", "model": "Alpha 7 IV", "aliases": ["A7 IV"], "source": ["lensfun"]},
            {"brand": "Sony", "model": "A7 IV", "source": ["curated"]},
            {"brand": "Sony", "model": "Alpha7IV", "source": ["curated"]},
        ]
        for order in (cameras, reversed(cameras)):
            index = db.CatalogIndex(order, [])
            self.assertEqual(index.camera_candidates("Sony", "A7 IV"), {("Sony", "A7 IV")})
            self.assertFalse(index.camera_candidates("Nikon", "A7 IV"))
            self.assertEqual(index.camera_candidates("Sony", "Alpha 7IV"), {("Sony", "Alpha 7 IV"), ("Sony", "Alpha7IV")})
            self.assertFalse(index.camera_candidates("Sony", "Alpha7IV+"))

    def test_brand_display_spelling_is_consistent(self):
        cameras = {}
        db.merge_camera(cameras, {'brand': 'Niceboy', 'model': 'VEGA'})
        db.merge_camera(cameras, {'brand': 'NICEBOY', 'model': 'VEGA 6'})
        db.merge_camera(cameras, {'brand': 'Realme', 'model': '3 Pro'})
        db.merge_camera(cameras, {'brand': 'REALME', 'model': '6 Pro'})
        camera_list, _ = db.finalize(cameras, {})
        self.assertEqual({x['brand'] for x in camera_list if x['brand'].casefold() == 'niceboy'}, {'Niceboy'})
        self.assertEqual({x['brand'] for x in camera_list if x['brand'].casefold() == 'realme'}, {'REALME'})

    def test_generic_lensfun_templates_contribute_mounts_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "generic.xml"
            path.write_text("<lensdatabase><mount><name>Generic</name><compat>M</compat></mount>"
                            "<camera><maker>Generic</maker><model>Crop-factor 1.5</model></camera>"
                            "<lens><maker>Generic</maker><model>Rectilinear</model></lens></lensdatabase>")
            cameras, lenses, mounts = {}, {}, {}
            db.parse_lensfun_file(path, cameras, lenses, mounts)
            self.assertEqual((cameras, lenses, mounts), ({}, {}, {"generic": ["M"]}))

    def test_missing_lensfun_directory_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                db.parse_lensfun(pathlib.Path(directory), {}, {})

    def test_mounts_resolve_across_files_without_transitive_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / 'a.xml').write_text('''<lensdatabase>
              <camera><maker>Example</maker><model>Camera</model><mount>A</mount><cropfactor>1.5</cropfactor></camera>
            </lensdatabase>''')
            (root / 'z.xml').write_text('''<lensdatabase>
              <mount><name>A</name><compat>B</compat></mount>
              <mount><name>B</name><compat>C</compat></mount>
              <mount><name>C</name><compat>B</compat></mount>
            </lensdatabase>''')
            cameras = {}
            db.parse_lensfun(root, cameras, {})
            self.assertEqual(cameras[('example', 'camera')]['compatible_mounts'], ['B'])

    def test_profiles_only_mark_unique_catalog_matches_and_ignore_catalog_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / 'Sony').mkdir()
            (root / 'catalog').mkdir()
            (root / 'Sony' / 'known.json').write_text(json.dumps({
                'camera_brand': 'Sony', 'camera_model': 'ILME-FX30',
                'lens_model': 'Sony FE 50mm F1.8', 'crop_factor': 9.0,
            }))
            (root / 'Sony' / 'untrusted.json').write_text(json.dumps({
                'camera_brand': 'xxx', 'camera_model': 'xxx', 'lens_model': '5000 blank-brand lenses',
            }))
            (root / 'Sony' / 'blank.json').write_text(json.dumps({
                'camera_brand': '', 'camera_model': '', 'lens_model': 'xxx',
            }))
            (root / 'catalog' / 'curated_identities.json').write_text(json.dumps({
                'camera_brand': 'Fake', 'camera_model': 'Registry row', 'lens_model': 'Registry lens',
            }))

            cameras = {}
            lenses = {}
            db.merge_camera(cameras, {'brand': 'Sony', 'model': 'FX30', 'aliases': ['ILME-FX30'], 'source': ['lensfun']})
            db.merge_lens(lenses, {'brand': 'Sony', 'model': 'FE 50mm F1.8', 'source': ['lensfun']})
            stats = db.parse_profiles(root, cameras, lenses)

            self.assertEqual(stats['profile_files'], 2)
            self.assertEqual(stats['matched_files'], 1)
            self.assertEqual(set(cameras), {('sony', 'fx30')})
            self.assertEqual(set(lenses), {('sony', 'fe 50mm f1.8', ())})
            self.assertEqual(cameras[('sony', 'fx30')]['aliases'], ['ILME-FX30'])
            self.assertEqual(cameras[('sony', 'fx30')]['crop_factor'], None)
            self.assertEqual(lenses[('sony', 'fe 50mm f1.8', ())]['aliases'], [])
            self.assertEqual(lenses[('sony', 'fe 50mm f1.8', ())]['source'], ['lensfun', 'gyroflow'])

    def test_curated_rows_and_qualified_profile_pairs_generate_deterministically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            profile_root = root / 'profiles'
            profile_root.mkdir()
            registry_path = root / 'curated.json'
            registry_path.write_text(json.dumps({
                'version': 1,
                'cameras': [{
                    'brand': 'Example', 'model': 'Body', 'aliases': ['Body 1'],
                    'source_url': 'https://manufacturer.example/body',
                }],
                'lenses': [{
                    'brand': 'Example', 'model': 'Lens', 'aliases': ['Lens One'],
                    'source_url': 'https://manufacturer.example/lens',
                }],
                'profile_camera_aliases': [{
                    'raw_brand': 'example body', 'raw_model': 'wrong name',
                    'target_brand': 'Example', 'target_model': 'Body',
                    'source_profile_refs': ['Example/profile.json'],
                    'source_url': 'https://manufacturer.example/body',
                }],
            }))
            (profile_root / 'profile.json').write_text(json.dumps({
                'camera_brand': 'example body', 'camera_model': 'wrong name', 'lens_model': 'Lens One',
            }))

            results = []
            for _ in range(2):
                cameras = {}
                lenses = {}
                registry, sources = db.parse_curated_identities(registry_path, cameras, lenses)
                stats = db.parse_profiles(profile_root, cameras, lenses, registry)
                camera_list, lens_list = db.finalize(cameras, lenses)
                results.append(json.dumps({'cameras': camera_list, 'lenses': lens_list, 'sources': sources, 'stats': stats['matched_files']}, sort_keys=True))

            self.assertEqual(results[0], results[1])
            self.assertEqual(len(json.loads(results[0])['cameras']), 1)
            self.assertEqual(len(json.loads(results[0])['lenses']), 1)
            self.assertEqual(set(json.loads(results[0])['sources']), {
                'https://manufacturer.example/body', 'https://manufacturer.example/lens',
            })


if __name__ == '__main__':
    unittest.main()
