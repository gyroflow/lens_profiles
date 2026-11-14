# Camera and lens metadata catalog

`__camera_catalog.json` describes camera bodies, lens names, aliases,
mounts and known crop factors. It contains no usable Gyroflow distortion
calibrations and imports no Lensfun distortion coefficients.

It combines metadata from this repository at
`886fc616c9c2c788856f54c21d451b9cb7fc4f44` and
[Lensfun](https://github.com/lensfun/lensfun) at
`bbd4332a9ec566fd9aa548c9e0d8ced238c56261`. The generator normalizes names
and merges unambiguous aliases. Revision IDs, record counts and a digest
of consumed inputs are retained inside the JSON.

The Lensfun database is distributed under Creative Commons
Attribution-ShareAlike 3.0. Its complete license is retained in
`__camera_catalog.LICENSE.txt`. The reserved JSON notice
`__camera_catalog.LICENSE.json` carries the source attribution, exact revision
links, modification notice and complete license into `profiles.cbor.gz`, because
the compression workflow packages JSON but does not package text or Markdown.
Preserve this notice and license when redistributing derived catalog data.

The dependency-free generator is proposed in
[Gyroflow's camera/lens selector branch](https://github.com/woahwhattheheck/gyroflow/tree/17b3332aa46672ff83ef3ab15319ec80a8c429e1).
Run `_scripts/generate_camera_catalog.py` with this profile tree, the
Lensfun `data/db` directory, their exact revision IDs and an output path
of `__camera_catalog.json` when updating the data.

The current compression workflow already packages JSON files into
`profiles.cbor.gz`. Older application clients skip reserved `__` entries in the compressed archive;
the proposed loader consumes the catalog and retains a bundled fallback. Running
directly from this source tree requires the reserved-entry handling proposed in
[Gyroflow PR #1244](https://github.com/gyroflow/gyroflow/pull/1244).
No additional release asset or extra client request is necessary.
