"""organize/normalize_artists.py - Bug 13 / D8 regression tests. pure
function, no beets needed."""
import pytest

from organize.normalize_artists import normalize_artist


# Bug 13: names containing ft / f. / feat mid-word must come back unchanged
@pytest.mark.parametrize('name', [
    'Daft Punk', 'Soft Cell', 'Left Boy', 'Defeat', 'Taft', 'Lift',
    'Jeff. Rosenstock', 'Ft. Lauderdale', 'Malcolm X',
    'King Gizzard & The Lizard Wizard', 'Simon & Garfunkel',
    'Tyler, The Creator', 'Solo Artist',
])
def test_names_left_alone(name):
    assert normalize_artist(name) == name


@pytest.mark.parametrize('raw,want', [
    ('Artist feat. Other', 'Artist feat. Other'),
    ('Artist ft. Other', 'Artist feat. Other'),
    ('Artist featuring Other', 'Artist feat. Other'),
    ('Artist (feat. Other)', 'Artist feat. Other'),
    ('Artist [feat. Other]', 'Artist feat. Other'),
    ('Artist f. Other', 'Artist feat. Other'),
    ('Artist feat. A x B', 'Artist feat. A, B'),
    ('Artist feat. Malcolm X', 'Artist feat. Malcolm X'),
])
def test_featuring(raw, want):
    assert normalize_artist(raw) == want


# D8: joins are ", " now, for any length
@pytest.mark.parametrize('raw,want', [
    ('A x B', 'A, B'),
    ('A and B', 'A, B'),
    ('A, B', 'A, B'),
    ('A, B, C', 'A, B, C'),
    ('A x B x C', 'A, B, C'),
])
def test_join_is_comma(raw, want):
    assert normalize_artist(raw) == want


def test_empty():
    assert normalize_artist('') == ''
    assert normalize_artist('   ') == ''
    assert normalize_artist(None) == ''
