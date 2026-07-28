# Sample data

Small synthetic fixtures for exercising the CLI. None of these are real survey
records — no real monuments, parcels, clients, or coordinates.

| File | Used by | What it is |
|---|---|---|
| `triangle_network.json` | `meridian network adjust` | A 3-4-5 right triangle. `P1` and `P2` are fixed brass disks; `P3` enters with a deliberately wrong a-priori position of (2.9, 3.9) and three distance observations at σ = 5 mm pull it to (3, 4). |
| `sample_traverse.gsi` | `meridian traverse run` | A closed four-leg 10 m square in Leica GSI-16. Closure is exact, perimeter 40 m, area 100 m². |
| `square_100m.txt` | COGO helpers | A 100 m square as plain coordinates. |
| `topo_field_codes.pnezd` | `meridian field codes` | Point/Northing/Easting/Elevation/Description records with topo field codes. |

## Conventions worth knowing

**`sample_traverse.gsi` stores absolute azimuths in word 21.** Real GSI files
record a *horizontal circle reading*, which only becomes an azimuth once the
setup is oriented to a backsight. GSI has no backsight-azimuth word, so the
driver leaves `Setup.backsight_azimuth` as `None` and
`reduce_setup_observations` falls back to treating word 21 as an azimuth
directly — the driver emits a warning saying exactly that. This fixture is
written to suit that fallback so the traverse closes; it is not a faithful
capture of instrument output.

**Angle encoding is `DD MM SSSSS`.** The GSI parser reads words 21 and 22 as
DMS with the trailing five digits carrying seconds × 1000. So 90° is
`900000000`, not `900000` — the latter decodes to 0°09'00" (0.15°). The parser
does not yet read the file's angle-units flag, so a gon-configured instrument
file will be misread.
