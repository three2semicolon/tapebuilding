"""Global configuration and environment handling for tapebuilding."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (one level up from src)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / '.env'
load_dotenv(ENV_PATH)

# Default configuration values, can be overridden by .env
DEFAULT_FORMAT = os.getenv('DEFAULT_FORMAT', 'mp3')
DEFAULT_BITRATE = os.getenv('DEFAULT_BITRATE', '320k')
DEFAULT_VERBOSE = os.getenv('DEFAULT_VERBOSE', 'false').lower() == 'true'

# Resolve paths based on env vars or defaults
ARCHIVE_PATH = os.getenv('ARCHIVE_PATH', PROJECT_ROOT / 'archive')
TAPEDECK_PATH = os.getenv('TAPEDECK_PATH', PROJECT_ROOT / 'tapedeck')
PLAYLISTS_PATH = os.getenv('PLAYLISTS_PATH', PROJECT_ROOT / 'playlists')
EXPORTS_DIR = os.getenv('EXPORTS_DIR', os.path.join(PLAYLISTS_PATH, 'exports'))

# Flags for CLI options
VERBOSE = os.getenv('VERBOSE', str(DEFAULT_VERBOSE)).lower() == 'true'
DRY_RUN = os.getenv('DRY_RUN', 'false').lower() == 'true'
APPLY = os.getenv('APPLY', 'false').lower() == 'true'