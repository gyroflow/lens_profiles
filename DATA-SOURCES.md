# Camera catalog sources

`camera_database.json` is generated from Lensfun at pinned commit
`a5e2caeb6b646b7a0bb9ed76033b56f8c0499e86` and the explicitly sourced entries
in `catalog/curated_identities.json`. The registry records a manufacturer URL
for each curated camera or lens and for each reviewed, exact producer-pair
correction. Curated fields merge into exact Lensfun identities when one exists.

Gyroflow profile files can mark an existing Lensfun or curated identity as
observed after an exact or unique catalog match. They never create camera or
lens entries, contribute crop-factor metadata, or add profile text as catalog
aliases. Qualified `profile_camera_aliases` map reviewed historical producer
pairs to a sourced catalog row; they are inputs to the profile producer only
and are not emitted as camera aliases. The generator excludes `catalog/` from
its profile scan so the registry cannot be read as a profile.

Run `python3 scripts/normalize_profile_metadata.py --check --report ../profile-review.json`
to list unresolved historical labels and the files containing them. The matcher
preserves a capture focal length appended to an identified lens name. A focal
length or aperture by itself leaves the lens unidentified.

The generator pins Lensfun source and license details in the output. Lensfun's
database is licensed under CC BY-SA 3.0; the applicable license is included in
`LENSFUN-DATABASE-LICENSE.txt`. Preserve the Lensfun attribution and license
notice when redistributing the modified compilation.

Rebuild from the pinned Lensfun revision with `python3 build_camera_database.py`.
For an offline or inspected copy of that same revision, pass
`--lensfun-db /path/to/lensfun/data/db`.
