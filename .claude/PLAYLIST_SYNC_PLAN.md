# tapebuilding — playlist sync: excludes, SoundCloud, cross-service plan

Three related asks, in the order they should actually be built:

1. `--exclude` for Spotify playlist sync (small, standalone, do first)
2. SoundCloud export/download (bigger, mirrors the Spotify export/download
   split, mostly independent of (1))
3. A cross-service "check what's missing, autodownload it" workflow (the
   thing the eventual web app wants to call — depends on (1) and (2)
   existing, and on `BUGFIX_PLAN.md`'s matching fixes landing first,
   since it's pointless to automate downloads on top of a matcher that's
   currently misreporting `unmatched.csv`)

---

## 1. `--exclude` flag for Spotify playlist sync

**Where:** `playlists/build.py`'s `_select_playlists()`, with `core
sync` (which calls `build_playlists()` directly) picking it up for free
once it's a `build_playlists()` parameter.

**Design:**

- Repeatable flag: `--exclude NAME_OR_ID`, e.g.
  `playlists --apply --rescrape --exclude "__orc" --exclude "__beats by three2"`.
- Matching should mirror how `-p/--playlist` already resolves a
  name-or-id, so the two flags behave symmetrically — same
  `lib.text.normalize_key()`-based case-insensitive name match, or exact
  Spotify ID match.
- Applies **after** the default-scope / `--all` / `--mine` resolution,
  as a filter-out step, before matching against the catalog — an
  excluded playlist should never show up in `unmatched.csv` or trigger a
  cover download, not just get skipped at the `.m3u8`-write step.
- **Conflict with `-p`:** if `-p` explicitly names a playlist that's also
  passed to `--exclude`, that's a contradictory request. Recommend
  erring the same way `playlists/cli.py` already does for `--all` +
  `--mine` ("only present to error clearly if combined") — fail loudly
  rather than silently deciding a winner.
- **Not propagating to `download export`:** the raw export's job is
  capturing everything; deciding what becomes a local playlist belongs
  at the sync/build layer, not the export layer. Keep the two decoupled
  unless a concrete reason to exclude at export time shows up later.
- **Nice-to-have, not required for v1:** a `PLAYLISTS_EXCLUDE` env var
  (comma-separated) as a standing default the CLI flag can add to, so
  you're not retyping the same two names on every `core sync`. Skip this
  unless it turns out to be annoying without it — easy to add later,
  doesn't need deciding now.

---

## 2. SoundCloud playlist sync

Recap of what `TODO.md` already sketched, fleshed out into an actual
shape.

### Export side — `download/soundcloud_export.py` (new)

- `list_user_sets(profile_url_or_username)` — `yt-dlp` `extract_flat`
  against `https://soundcloud.com/<user>/sets` to list your own
  sets/playlists (title, url, track count) without downloading anything.
  `ytdl.py` already uses `extract_flat` for its `--metadata-only` path,
  so this reuses a pattern already proven in the repo rather than
  introducing new yt-dlp usage.
- `list_user_likes(profile_url_or_username)` — same idea against
  `/likes`, **if** likes should be in scope (see open question below;
  Spotify's `liked_songs.csv` has an analog, but SoundCloud likes tend
  to be a much noisier, less curated list than playlists — confirm
  before building this half).
- `export_set(set_url)` — `extract_flat` on one set → track rows
  (title, uploader, track url, position). No duration/album without a
  second, non-flat, per-track extraction pass — expensive, and matches
  the sparser-metadata tradeoff `README.md` already documents for
  `ytdl.py`. v1 accepts the sparser shape.
- `export_all_data()` analog — walks every set from `list_user_sets()`,
  unions into one `soundcloud_manifest.csv`. **Dedup key is the track
  URL** (or url + normalized title as a fallback for re-uploads) —
  unlike Spotify, `extract_flat` doesn't give a stable numeric track ID
  to dedup on.
- Output shape, mirroring Spotify's as closely as SoundCloud's metadata
  allows: `soundcloud_playlists.csv`, `soundcloud_playlist_tracks.csv`,
  `soundcloud_manifest.csv`, `soundcloud_manifest_urls.txt`.
- **Auth:** public sets need none. Private/followed-only sets need
  cookies — reuse `ytdl.py`'s existing `--cookies-from-browser`/
  `--cookie-file` options rather than inventing a second cookie
  mechanism.

### Download side

- `download.ytdl.download_ytdl()` already walks a single playlist/set
  URL end-to-end (yt-dlp handles the playlist mechanics itself) — the
  new manifest doesn't replace that path, it exists so a **library-wide**
  SoundCloud sync gets the same "what's actually new" tracking Spotify
  has. Feed `soundcloud_manifest_urls.txt` through a SoundCloud-aware
  equivalent of `spotify_download.py`'s batching/retry/
  `--pre-skip-existing` loop, calling `download_ytdl()` per track (or
  per set) underneath.
- **Existence check:** `download.existing`'s filename-stem index is
  already extension/source-agnostic (confirmed in `TODO.md`) — the
  missing piece is *predicting* `download_ytdl()`'s own filename from
  manifest metadata alone, the SoundCloud-side equivalent of
  `download.manifest.predict_output_filename()`. `ytdl.py`'s actual
  templates (`Uploader - Title.ext` singles, `Set Name/NN - Uploader -
  Title.ext` sets) need to be replicated **exactly** in the predictor —
  same "match the real tool's output exactly, not close enough" caveat
  `NEW_FEATURE_GUIDE.md` §4 already flags for the Spotify side, and the
  same kind of thing Bug 1 in `BUGFIX_PLAN.md` shows what happens when a
  prediction and the real tag/filename drift apart.
- **New CLI surface:** recommend a parallel `download soundcloud`
  subcommand (mirroring `download export`'s shape) rather than
  overloading `download spotify`'s flags with a `--source` switch — auth,
  metadata shape, and filename prediction diverge enough between the two
  that shared flags would get confusing fast.
- **Package location:** `TODO.md` already leans `download/` over a new
  top-level `soundcloud/` package for now — agree with that; revisit
  only if SoundCloud grows its own matching/dedup logic the way
  Spotify's `merge_and_deduplicate()`/`_fuzzy_key()` did.

### Matching against the crate (for `.m3u8` building)

- `lib.catalog.matcher`'s tiers 3 and 6 depend on album/duration data
  SoundCloud tracks mostly won't have. Tiers 1/2/4/5 (title+artist exact
  or fuzzy) should still function using uploader-as-artist. Treat this
  as a known reduced-accuracy subset rather than trying to force
  album-dependent tiers to work off missing data — don't invent
  SoundCloud-specific matcher tiers unless the reduced set turns out to
  actually miss too much in practice.

### Playlist-file (`.m3u8`) side — the actual design decision

`playlists/build.py` today is Spotify-shaped: `_select_playlists()` and
`_scope_rescrape()` both assume Spotify's CSV columns. Two ways to add
SoundCloud:

- **(a) Parallel path:** a `soundcloud_build.py` alongside `build.py`,
  duplicating the export→select→match→write→unmatched orchestration but
  pointed at the SoundCloud manifest. Fast to ship, but it's exactly the
  kind of duplication `lib/` was created to kill.
- **(b) Shared orchestration, swappable source:** extract
  `build_playlists()`'s "select rows → match against catalog → write
  `.m3u8`/unmatched" middle section into a source-agnostic function
  taking already-normalized rows, regardless of which service they came
  from. `spotify_build.py`/`soundcloud_build.py` (or one file with a
  `source=` param) would each own only the fetch + CSV-shape part. This
  is the shape that actually supports "manage my Spotify or SoundCloud
  playlists" as one mental model, and it's what §3's cross-service
  workflow (and the eventual web app) wants underneath it.

**Recommendation: (b), done as its own refactor step *after*
`BUGFIX_PLAN.md`'s Bug 1/2 fixes land and are re-verified** — building a
second playlist source on top of matching logic that's currently
misreporting matches just doubles the surface area you'd have to re-test
once the matcher's fixed.

---

## 3. Cross-service "check + autodownload" workflow

The end-goal described: for a given playlist (Spotify or SoundCloud), one
action does rescrape/re-list → match against crate → collect unmatched
→ auto-run the matching download command on just the unmatched subset →
re-match → rebuild the `.m3u8`. Today that's several manual steps
(`playlists --apply --rescrape`, eyeball `unmatched.csv`, `download
spotify -u unmatched_urls.txt`, `playlists --apply --rescrape` again) —
this workflow just chains steps that already exist into one call.

- **Natural home:** a new `core/` function (e.g. `run_playlist_sync()`),
  same shape as `run_download_songs()`: call `build_playlists()`, then
  `download_spotify()`/`download_soundcloud()` on the unmatched subset if
  new tracks came back, then `build_playlists()` again — one structured
  result. This is exactly "orchestrate multiple domain packages into one
  opinionated workflow," which `NEW_FEATURE_GUIDE.md` §1 already says
  belongs in `core/`, not in `app/` itself. `app/`, once built, is just a
  button that calls it (see `WEB_APP_PLAN.md`'s update).
- **Defer until:** `--exclude` exists (so autodownload doesn't pull
  tracks for playlists you deliberately don't sync — e.g. you wouldn't
  want this workflow auto-downloading your soundtrack playlist's
  "missing" tracks), and the SoundCloud manifest/predictor exist (so
  there's actually a `download_soundcloud()` to call for that half).

---

## Open questions for you

- SoundCloud: playlists only for v1, or likes too?
- `--exclude` + `-p` naming the same playlist: hard error (recommended),
  or should exclude just silently win?
- OK to defer the shared-orchestration refactor (§2, option b) until
  after `BUGFIX_PLAN.md`'s Bug 1/2 are fixed, per the recommendation
  above — or is unblocking SoundCloud sooner worth the parallel-path
  duplication of option (a) as a stopgap?
- SpotDL fallback: consider adding an option to prompt for alternative source (YouTube Music or local file) when a track cannot be found via SpotDL, to improve matching for soundtracks and reduce unmatched tracks.
