# tapebuilding

building and managing my personal music library

## overview

this project provides tools for managing a personal music library, including:

- exporting spotify playlists and liked songs to csv
- downloading music from spotify urls using spotdl
- organizing downloaded music

## installation

1. clone the repository:

   ```bash
   git clone <repository-url>
   cd tapebuilding
   ```
2. install dependencies with uv:

   ```bash
   uv sync
   ```

   this creates a virtual environment and installs the package in editable mode, making the `download` and `export` commands available.

## export spotify data

the `export` module exports your spotify data (playlists, liked songs, etc.) to csv files for backup and processing.

### usage

#### basic usage

```bash
# export all data (default)
export

# export only your own playlists
export --mine

# specify output directory
export -o /path/to/export
```

#### export specific playlist

```bash
# by url
export -p "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"

# by id
export -p "37i9dQZF1DXcBWIGoYBM5M"
```

#### output files

when exporting, the following files are created in the export directory:

- `playlists.csv`: playlist metadata (name, description, owner, track count, etc.)
- `playlist_tracks.csv`: all tracks from all playlists (includes duplicates if a track appears in multiple playlists)
- `liked_songs.csv`: all your liked/saved tracks
- `spotify_manifest.csv`: deduplicated master list of all unique tracks from playlists + liked songs
- `spotify_manifest_urls.txt`: plain text file with spotify urls (one per line) for use with the download module

## download music

the `download` module allows you to download music from spotify urls (tracks, albums, playlists, etc.) using spotdl.

### supported input formats

the download module accepts the following as input (`--url-file` or `-u`):

- **text files (.txt)**: one spotify url per line
- **csv files (.csv)**: must contain a column named `spotify_url` (case-sensitive)
- **directories**: processes all `.csv` files in the directory (non-recursive), each must have a `spotify_url` column

### usage

#### basic usage

```bash
# using the default url file (export/spotify_manifest_urls.txt)
download

# specifying a custom url file
download -u path/to/urls.txt

# specifying an output directory
download -u path/to/urls.txt -o /path/to/output

# processing a directory of csv files (e.g., your export folder)
download -u /path/to/export/directory
```

#### batch processing

to improve performance, you can process multiple urls in each spotdl call (avoids restarting spotdl for each url):

```bash
# process 10 urls per batch (adjust based on command line length limits)
download -u path/to/urls.txt --batch-size 10

# for large exports, try 20-50
download -u export/spotify_manifest_urls.txt --batch-size 30
```

#### validation only

verify urls without downloading:

```bash
download -u path/to/urls.txt --validate-only
```

#### additional options

- `--format`: audio format (default: mp3)
- `--bitrate`: audio bitrate (default: 320k)
- `--overwrite-errors`: re-download files that had errors in previous attempts
- `--skip-existing`: skip files that already exist in output directory
- `--verbose`: enable verbose output from spotdl

## complete workflow

here's the recommended full workflow for maintaining your music library with tapebuilding:

### 1. initial setup

```bash
# clone the repository and set up the environment
git clone <repository-url>
cd tapebuilding
uv sync  # creates virtual environment and installs dependencies
```

### 2. export your spotify data

```bash
# activate the virtual environment (if not already activated)
# windows: .venv\Scripts\activate
# bash: source .venv/bin/activate

# export all your spotify data (playlists, liked songs, etc.)
export --all

# optional: export only your own playlists
# export --mine

# files will be created in the export/ directory by default
# key files: spotify_manifest.csv and spotify_manifest_urls.txt
```

### 3. validate your urls (recommended)

```bash
# check that all urls are valid and accessible
download --validate-only

# or validate a specific file
download -u export/spotify_manifest_urls.txt --validate-only
```

### 4. download your music

```bash
# download using the default manifest (export/spotify_manifest_urls.txt)
# using batch size of 25 for good performance
download --batch-size 25

# specify custom output directory
download -o /path/to/music/library --batch-size 25

# process a specific playlist csv
download -u export/playlist_my-favorites.csv --batch-size 10
```

### 5. verify and organize

after downloading, you can:

- check the output directory for your downloaded music files
- use your preferred music organizing tools to sort by artist/album/genre
- create backups of your music library

### maintenance / updates

to keep your library up to date with new music:

```bash
# repeat steps 2-4 periodically (weekly/monthly)
# the download process will skip existing files by default (unless --overwrite-errors is used)
# to only get new music, you can:
# 1. export again to get updated url lists
# 2. run download with --skip-existing to avoid re-downloading existing files

# example monthly update:
export --all
download --batch-size 25 --skip-existing
```

### environment variables

you can set the following in your `.env` file:

- `archive_path`: default output directory for downloads (defaults to `~/music/tapebuilding`)
- `ffmpeg_path`: path to ffmpeg executable (if not in your system path)
- `spotify_client_id`: your spotify api client id
- `spotify_client_secret`: your spotify api client secret
- `spotify_user_id`: your spotify user id
- `spotify_redirect_uri`: redirect uri for spotify auth (default: http://127.0.0.1:8888/callback)

### notes

- the download process automatically removes duplicate urls while preserving the order of first appearance
- when processing a directory, all `.csv` files are read (non-recursive)
- csv files must contain a column named `spotify_url` (exact case match)
