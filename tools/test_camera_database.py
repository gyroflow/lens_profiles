import json
from pathlib import Path
import tempfile
import unittest

from generate_camera_database import build, camera_key, render


class CameraDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.xml = self.root / "lensfun/data/db"
        self.xml.mkdir(parents=True)
        (self.root / "Sony").mkdir()
        (self.xml / "test.xml").write_text('''<lensdatabase version="1">
          <mount><name>Sony E</name><compat>M42</compat></mount>
          <camera><maker>Sony</maker><model>ILCE-6000</model><model lang="en">Alpha 6000</model><mount>Sony E</mount><cropfactor>1.5</cropfactor><aspect-ratio>3:2</aspect-ratio></camera>
          <camera><maker>Sony</maker><model>Cybershot</model><variant>DSC-F707</variant><mount>sony707</mount><cropfactor>4</cropfactor></camera>
          <camera><maker>Sony</maker><model>Cybershot</model><variant>DSC-F717</variant><mount>sony707</mount><cropfactor>4</cropfactor></camera>
          <lens><maker>Sony</maker><model>E 16-50mm</model><mount>Sony E</mount><cropfactor>1.5</cropfactor></lens>
        </lensdatabase>''')

    def profile(self, filename, **overrides):
        data = dict(camera_brand="sony", camera_model="a6000", lens_model="Sony E 16-50mm", crop_factor=2)
        data.update(overrides)
        (self.root / "Sony" / filename).write_text(json.dumps(data))

    def test_alias_merge_keeps_variants_and_physical_sensor(self):
        self.profile("one.json")
        db = build(self.root, self.root / "lensfun")
        self.assertEqual(len(db["cameras"]), 3)
        camera = next(c for c in db["cameras"] if c["model"] == "ILCE-6000")
        self.assertEqual(camera["sources"], ["gyroflow", "lensfun"])
        self.assertEqual(camera["crop_factor"], 1.5)  # Not the video's crop.
        self.assertAlmostEqual(camera["sensor_width_mm"], 24, places=2)
        self.assertEqual(len(camera["profile_lenses"]), 1)
        self.assertEqual(len(db["lenses"]), 1)
        self.assertEqual(db["lenses"][0]["max_focal"], 50)

    def test_unknown_and_compatible_settings_are_preserved(self):
        self.profile("one.json", camera_model="Future camera", lens_model="", compatible_settings=[dict(camera_model="Other camera", lens_model="18–55mm")])
        db = build(self.root, self.root / "lensfun")
        camera = next(c for c in db["cameras"] if c["model"] == "Other camera")
        self.assertIsNone(camera["crop_factor"])
        self.assertEqual(len(camera["profile_lenses"]), 1)
        self.assertEqual(len(db["cameras"]), 5)

    def test_deterministic_and_excludes_tool_fixtures(self):
        self.profile("one.json")
        first = build(self.root, self.root / "lensfun")
        self.assertEqual(json.loads(render(first)), first)
        tools = self.root / "tools"
        tools.mkdir()
        (tools / "fixture.json").write_text('{"camera_brand":"Fake","camera_model":"Fixture"}')
        self.assertEqual(first, build(self.root, self.root / "lensfun"))
        self.assertEqual(camera_key("SONY", "Sony Alpha-6000"), camera_key("Sony", "a6000"))

    def test_missing_lensfun_is_an_error(self):
        with self.assertRaises(ValueError):
            build(self.root, self.root / "missing")

    def test_exif_manufacturer_and_model_prefix_aliases(self):
        (self.xml / "nikon.xml").write_text('''<lensdatabase version="1"><camera>
          <maker>Nikon Corporation</maker><model>NIKON D5300</model><mount>Nikon F</mount><cropfactor>1.5</cropfactor>
        </camera></lensdatabase>''')
        self.profile("nikon.json", camera_brand="Nikon", camera_model="D5300", lens_model="")
        db = build(self.root, self.root / "lensfun")
        camera = next(c for c in db["cameras"] if c["id"] == "nikon/d5300")
        self.assertEqual(camera["sources"], ["gyroflow", "lensfun"])
        self.assertEqual(camera_key("Canon", "EOS R5"), camera_key("Canon", "R5"))
        self.assertEqual(camera_key("Panasonic", "Lumix DC-GH5"), camera_key("Panasonic", "GH5"))


if __name__ == "__main__":
    unittest.main()
