---
icon: lucide/settings
---

# configuration

beets configuration lives in `library_config.yaml` (a machine-specific file) with a path-templated example in `library_config.yaml.example`.

## key sections

### directory / library

```yaml
directory: <crate>
library: <crate>/beets.db
```

### pluginpath

points beets at the custom plugins shipped in the repo (e.g. `normalize_artists`):

```yaml
pluginpath:
  - <repo>/src/organize
```

### paths

destination path templates for imported files:

```yaml
paths:
  default: albums/$albumartist - $album%aunique{}/$track - $artist - $title
  comp: albums/$albumartist - $album%aunique{}/$track - $artist - $title
  singleton: singles/$artist - $title
```

### import

import behavior (move vs copy, duplicate handling, logging):

```yaml
import:
  move: yes
  copy: no
  write: yes
  duplicate_action: skip
  resume: yes
  log: <crate>/beets_import.log
  quiet_fallback: asis
```

### match

musicbrainz matching thresholds and preferences:

```yaml
match:
  strong_rec_thresh: 0.90
  preferred:
    countries: [us, gb, xw]
    media: [digital media, cd]
```

### plugins

plugins enabled at import, including the custom `normalize_artists` plugin:

```yaml
plugins:
  - normalize_artists
  - fetchart
  - embedart
  - duplicates
  - missing
  - info
```

see `library_config.yaml.example` for the full path-templated reference.
