# Camera catalogue

`camera_database.json` contains camera and lens names from the Gyroflow profiles
and the pinned Lensfun submodule. It contains Lensfun metadata, not distortion
calibrations that can be loaded directly in Gyroflow.

Regenerate it with Python 3 (standard library only):

```sh
git submodule update --init lensfun
python3 -m unittest discover -s tools -p 'test_*.py'
python3 tools/generate_camera_database.py
```

To update Lensfun, update the submodule commit, regenerate, and commit both the
submodule change and JSON. Profile releases regenerate the catalogue and include
it as `__camera_database` in `profiles.cbor.gz`. Older Gyroflow versions ignore
reserved entries; newer versions update the catalogue with the profiles. The app
also ships a copy in `resources/camera_database.json` for offline use.

Schema version 1 preserves source aliases and fixed-camera variants. Mount
compatibility is directional, as in Lensfun; adapting a lens does not make two
cameras' calibrations interchangeable. Sensor crop factors come from Lensfun;
width and height are only derived when a sensor aspect ratio is supplied.
Gyroflow video crop factors are not assumed to describe the physical sensor.
Unknown values remain null. Camera-specific, ambiguous lens names are preserved
without merging unrelated lenses. `input_sha256` identifies the source content.

## Data attribution and licence

The existing Gyroflow lens profiles remain under CC0-1.0. Lensfun camera/lens data
is copyright the Lensfun contributors, used under CC BY-SA 3.0:
https://github.com/lensfun/lensfun/tree/master/data

The combined `camera_database.json` is distributed under CC BY-SA 3.0, an
exception to this repository's default CC0 licence. This is a derived catalogue:
names have been normalized, aliases combined, source fields selected, focal
ranges parsed, and sensor dimensions calculated where enough data is available.
The source revision and licences are recorded in the JSON. The licence text is
included in `lensfun/data/COPYING.CC_BY-SA_3.0` and at
https://creativecommons.org/licenses/by-sa/3.0/ . Retain this attribution and
licence when distributing the generated catalogue, including in Gyroflow.
