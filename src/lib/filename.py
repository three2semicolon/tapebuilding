"""lib.filename - shared output-filename prediction.

Centralises filename prediction used by both download.manifest.predict_output_filename
(Spotify/spotdl) and download.soundcloud.soundcloud_download._predict_soundcloud_filename.
Uses lib.tags.sanitize for illegal-character replacement.
"""

from lib.tags import sanitize


def predict_output_filename(artist, track, fmt, set_name=None, set_position=None):
    """Predict the output filename for a track.

    If set_name and set_position are provided (playlist/set context), uses
    the template: '{set_name}/{set_position:02d} - {artist} - {track}.{fmt}'
    Otherwise uses: '{artist} - {track}.{fmt}'

    Components are sanitised individually (lib.tags.sanitize replaces illegal
    characters with '_') so the '/' path separator in playlist templates is
    preserved.
    """
    artist = sanitize(artist)
    track = sanitize(track)
    if set_name and set_position is not None:
        set_name = sanitize(set_name)
        return f"{set_name}/{set_position:02d} - {artist} - {track}.{fmt}"
    return f"{artist} - {track}.{fmt}"
