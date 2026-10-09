# Genuine historical OpenStudio fixtures

These files are unchanged upstream test resources, not current models with
edited version headers. Retrieved 2026-10-09. Tests use the pinned 3.11.0 SDK;
no older SDK installation is needed.

| Local fixture | Version | Upstream commit and resource | SHA-256 |
| --- | --- | --- | --- |
| openstudio-1.13.4-example.osm | 1.13.4 | [OpenStudio resource](https://github.com/NatLabRockies/OpenStudio/blob/fb22b142c3dc416f09e032a9ab6fd632643d9989/resources/osversion/1_13_4/example.osm) | 7dc06266c4eca5a65c3566a1083a8aa9fa4bafbb2d494f34a4ed2b650682d00f |
| openstudio-legacy-multiloop.osm | 2.2.2 | [OpenStudio-resources baseline_sys03](https://github.com/NatLabRockies/OpenStudio-resources/blob/90eeb34c0277810e3705a78dd544309ec08aae73/model/simulationtests/baseline_sys03.osm) | 1e27771daeb16d668c4ae0e5465b5ac737c347532b098c29328ba2548205c59b |

The first is 170,112 bytes with one air loop; the second is 481,106 bytes with ten
loops. The latter supports partial removal while retaining nine assignment lists.
Its upstream dangling StandardsMaterial reference produces an SDK log message;
this is distinct from VersionTranslator warnings/errors and is not hidden by tests.

To regenerate, download the raw content of these exact commit/resource URLs and
verify the hashes above. Upstream notices are retained beside the fixtures in
`OpenStudio-LICENSE.txt` and `OpenStudio-resources-LICENSE.txt`, retrieved from the
same pinned commits.
