"""tests for lib.catalog.soundcloud_loose. rows below are taken verbatim from a real
unmatched.csv; the catalog is synthetic (what the local library would plausibly hold).

drop next to your other lib.catalog tests; imports assume the package layout
lib/catalog/{row_access,soundcloud_loose}.py.
"""
import pytest

from lib.catalog.soundcloud_loose import SoundcloudLooseIndex, tokens


def E(title, artist, albumartist=None, length=200.0, path=None):
    return {'title': title, 'artist': artist, 'albumartist': albumartist or artist,
            'length': length, 'path': path or f'/crate/{artist}/{title}.mp3'}


CATALOG = [
    E('Sculpted', 'Haywyre'),
    E('Immaculation', 'Captain Murphy'),
    E('The Prisoner', 'Captain Murphy'),
    E('Am I Wrong', 'ANDERSON .PAAK'),
    E('I Love Love U', 'DJ LHC'),
    E('Ascension (feat. Vince Staples)', 'Gorillaz'),
    E('Malibu', 'J.ROBB'),
    E('Ragepeace', 'Aminé'),
    E('Almost Doesn\u2019t Count', 'wntr'),
    E("Ain't Gotta Call", 'ATM'),
    E('Otis (Mr. Carmack Remix)', 'Someone'),
    E('Drive Thru', 'Captain Murphy'),
    E('Oh Sheit It\'s X', 'Thundercat'),
    E('Yaaah Don\'t Do It', 'Some Artist'),     # title-only (distinctive, unique)
    # decoys: same title, different artist / original vs remix
    E('Malibu', 'Miley Cyrus'),
    E('Colorful', 'Somebody Else'),
    E('Cooking', 'Another Person'),
    E('Otis', 'Kanye West'),
    E('Sculpted Remix Pack', 'Nobody'),
]
IDX = SoundcloudLooseIndex(CATALOG)


def row(title, artist, url='https://soundcloud.com/x/y'):
    return {'track_name': title, 'artist_names': artist, 'spotify_url': url}


def m(title, artist, **kw):
    e, tier = IDX.match(row(title, artist, **kw))
    return (e['title'], e['artist'], tier) if e else (None, None, None)


@pytest.mark.parametrize('title,artist,want', [
    # artist glued to front of slug, uploader == artist
    ('haywyre sculpted', 'Haywyre', ('Sculpted', 'Haywyre')),
    # uploader is a label, artist only in the title
    ('captain murphy immaculation ft', 'selftitledmag', ('Immaculation', 'Captain Murphy')),
    ('captain murphy the prisoner', 'selftitledmag', ('The Prisoner', 'Captain Murphy')),
    ('captain murphy drive thru prod', 'selftitledmag', ('Drive Thru', 'Captain Murphy')),
    ('thundercat oh sheit its x', 'BRAINFEEDER', ("Oh Sheit It's X", 'Thundercat')),
    # artist at the END of the slug, with differently-punctuated uploader
    ('am i wrong anderson paak', 'anderson .paak', ('Am I Wrong', 'ANDERSON .PAAK')),
    # api-v2 real title with "ARTIST - Title" prefix
    ('DJ LHC - I LOVE LOVE U', 'dj lhc', ('I Love Love U', 'DJ LHC')),
    # feat clause on local side, dangling on row side
    ('ascension feat vince staples', 'Gorillaz', ('Ascension (feat. Vince Staples)', 'Gorillaz')),
    # accents + uploader == artist, single-word title
    ('ragepeace', 'Aminé', ('Ragepeace', 'Aminé')),
    # apostrophe dropped by the slug
    ('almost doesnt count', 'wntr', ('Almost Doesn\u2019t Count', 'wntr')),
    # noise tags
    ("[PREMIERE] ATM - Ain't Gotta Call (Original Mix) [\uff30\uff28\uff29\uff2c\uff34\uff28\uff34\uff32\uff21\uff38]",
     'CRAZED BEHAVIOUR', ("Ain't Gotta Call", 'ATM')),
    # remix with remixer in local brackets
    ('otis remix', 'mr carmack', ('Otis (Mr. Carmack Remix)', 'Someone')),
])
def test_matches(title, artist, want):
    got = m(title, artist)
    assert got[:2] == want, got


def test_picks_right_malibu():
    assert m('malibu', 'J.ROBB')[:2] == ('Malibu', 'J.ROBB')


def test_title_only_is_last_resort_and_labelled():
    t, a, tier = m('yaaah dont do it', 'random uploader')
    assert (t, tier) == ("Yaaah Don't Do It", 9)


@pytest.mark.parametrize('title,artist', [
    ('colorful', 'thoomn'),                    # title exists locally but by someone else
    ('cooking', 'woosta has a picnic'),
    ('malibu', 'nobody related'),              # ambiguous 2 locals, no artist evidence
    ('sculpted remix', 'haywyre'),             # remix must not map to the original
    ('otis', 'mr carmack'),                    # original must not map to a remix (and Kanye's isn't his)
])
def test_rejects(title, artist):
    assert m(title, artist)[0] is None, m(title, artist)


def test_remix_marker_must_agree():
    # row is a remix, only the original exists locally for this artist
    idx = SoundcloudLooseIndex([E('Sculpted', 'Haywyre')])
    e, _ = idx.match(row('haywyre sculpted vip', 'Haywyre'))
    assert e is None


def test_tokens_fold():
    assert tokens("Aminé's  \uff21\uff22\uff23") == ('amines', 'abc')


# ---- real misses reported from the user's library ---------------------------------
# (soundcloud title, uploader, tag-artist, tag-title, on-disk filename)
USER_CASES = [
    ('metropole', 'Anomalie', 'Anomalie', 'Métropole', '02 - Anomalie - Métropole.flac'),
    ('swindail ballpoint 1', 'Wu-zi', 'Swindail', 'Ballpoint', '09 - Swindail - Ballpoint.mp3'),
    ('well well prod enaur', 'on1y', 'on1y', 'well well', 'on1y - well well.mp3'),
    ('diversa underscore once again', '\u0486\u0485a', 'DIVERSA', 'once again', '09 - DIVERSA - once again.flac'),
    ('onmymind', 'cygn artist', 'C Y G N', 'OnMyMind', 'C Y G N - OnMyMind.flac'),
    ('hz 1', 'west1ne', 'West1ne', 'Hz', 'West1ne - Hz.mp3'),
    # "/" is how multi-artist tags are stored; "_" is how the filename spells it
    ('smile ft sophie meiers prod nohidea', 'BEN BEAL', 'Nohidea/Ben Beal/sophie meiers', 'Smile',
     'Nohidea_Ben Beal_sophie meiers - Smile.mp3'),
    ('haywyre time ft coma', 'Haywyre', 'Haywyre/CoMa', 'Time', '06 - Haywyre_CoMa - Time.mp3'),
]


@pytest.mark.parametrize('sc_title,uploader,tag_artist,tag_title,fname', USER_CASES)
def test_user_cases_clean_tags(sc_title, uploader, tag_artist, tag_title, fname):
    idx = SoundcloudLooseIndex([E(tag_title, tag_artist, path='/crate/' + fname)])
    e, tier = idx.match(row(sc_title, uploader))
    assert e is not None and e['title'] == tag_title and tier in (7, 8)


@pytest.mark.parametrize('sc_title,uploader,tag_artist,tag_title,fname', USER_CASES)
def test_user_cases_tags_missing_filename_only(sc_title, uploader, tag_artist, tag_title, fname):
    """untagged / badly tagged file: artist+title recovered from the filename."""
    entry = {'title': '', 'artist': '', 'albumartist': '', 'length': 200.0, 'path': '/crate/' + fname}
    idx = SoundcloudLooseIndex([entry])
    e, tier = idx.match(row(sc_title, uploader))
    assert e is not None and tier in (7, 8)


@pytest.mark.parametrize('sc_title,uploader,tag_artist,tag_title,fname', USER_CASES)
def test_user_cases_do_not_hit_unrelated_neighbors(sc_title, uploader, tag_artist, tag_title, fname):
    """same title by an unrelated artist must not win."""
    idx = SoundcloudLooseIndex([E(tag_title, 'Totally Different Person', path='/crate/other/x.mp3')])
    e, tier = idx.match(row(sc_title, uploader))
    assert e is None


# ---- round 3: bracketed titles + truncated slugs -------------------------------------
def test_bracketed_title_real_tags():
    """tags copied from the real file: title='Girls_Tequila (Kiss In The Club)',
    artist='Ethereal/Alli Cat', albumartist='Ethereal'."""
    entry = {'title': 'Girls_Tequila (Kiss In The Club)', 'artist': 'Ethereal/Alli Cat',
             'albumartist': 'Ethereal', 'length': 160.056,
             'path': '/crate/05_-_Ethereal_Alli_Cat_-_Girls_Tequila__Kiss_In_The_Club_.mp3'}
    idx = SoundcloudLooseIndex([entry])
    for t in ['Girls_Tequila (Kiss In The Club) feat. Alli Cat',   # api-v2 style
              'girls tequila kiss in the club feat alli cat',      # slug style
              'girls tequila']:                                    # bracket dropped
        e, tier = idx.match(row(t, 'ETHEREAL'))
        assert e is entry and tier == 7, (t, tier)


def test_truncated_slug_prefix():
    cat = [E('Pretty Thoughts', 'Galimatias/Alina Baraz'),
           E('Living Off the High', 'Moody Good', albumartist='Moody Good')]
    idx = SoundcloudLooseIndex(cat)
    e, tier = idx.match(row('alina baraz galimatias pretty', 'Galimatias'))
    assert e and e['title'] == 'Pretty Thoughts' and tier == 8
    e, tier = idx.match(row('moody good living off the', 'moody good'))
    assert e and e['title'] == 'Living Off the High' and tier == 8


def test_truncated_slug_cut_mid_word():
    idx = SoundcloudLooseIndex([E('Pretty Thoughts', 'Galimatias')])
    e, tier = idx.match(row('galimatias pretty thoug', 'Galimatias'))
    assert e and e['title'] == 'Pretty Thoughts'


def test_prefix_must_be_unambiguous():
    # "pretty" could be either track -> refuse rather than guess
    idx = SoundcloudLooseIndex([E('Pretty Thoughts', 'Galimatias'), E('Pretty Girl', 'Galimatias')])
    e, _ = idx.match(row('galimatias pretty', 'Galimatias'))
    assert e is None


def test_prefix_needs_artist_and_few_missing_words():
    idx = SoundcloudLooseIndex([E('Living Off the High', 'Moody Good')])
    assert idx.match(row('living off the', 'some random uploader'))[0] is None   # no artist evidence
    far = SoundcloudLooseIndex([E('Love Me Like You Do Tonight Again', 'Moody Good')])
    assert far.match(row('moody good love', 'moody good'))[0] is None            # too many words missing


# ---- round 4: catalog shaped like the user's Mp3tag screenshots -------------------------
def EA(title, artist, album, albumartist=None, length=200.0):
    return {'title': title, 'artist': artist, 'albumartist': albumartist or artist, 'album': album,
            'length': length, 'path': f'/crate/{album}/{title}.mp3'}


SHOT = SoundcloudLooseIndex([
    # Captain Murphy - Duality Deluxe
    EA('Hovercrafts and Cows (Prod Flying Lotus)', 'Captain Murphy', 'Duality Deluxe'),
    EA('Hovercrafts and Cows [Instrumental]', 'Captain Murphy', 'Duality Deluxe'),
    # DIVERSA - underscore
    *[EA(t, 'DIVERSA', 'underscore') for t in ['bae', 'xxxXXX', 'haveaniceday', 'srri srri',
                                              'trigger happy', 'lunatic', 'sandboxmode2', 'once again']],
    EA('awkward silence ft. oneira', 'DIVERSA', 'underscore'),
    # Alina Baraz - Urban Flora (+ a remixes album)
    *[EA(t, a, 'Urban Flora') for t, a in [
        ('Show Me', 'Alina Baraz/Galimatias'), ('Drift', 'Galimatias/Alina Baraz'),
        ('Can I', 'Galimatias/Alina Baraz'), ('Fantasy', 'Alina Baraz/Galimatias'),
        ('Make You Feel', 'Alina Baraz/Galimatias'), ('Maybe', 'Alina Baraz/Galimatias'),
        ('Pretty Thoughts', 'Galimatias/Alina Baraz'), ('Unfold', 'Alina Baraz/Galimatias')]],
    EA('Make You Feel (Remix)', 'Alina Baraz/Galimatias', 'Urban Flora (Remixes)'),
    # Kelela - RAVE:N, The Remixes
    EA('Contact - Karen Nyame KG Remix', 'Kelela/Karen Nyame KG', 'RAVE:N, The Remixes', 'Kelela'),
    EA('Closure - Flexulant x BAMBII Remix feat. Rahrah Gabor & Brazy',
       'Kelela/Flexulant/BAMBII/Rahrah Gabor/brazy', 'RAVE:N, The Remixes', 'Kelela'),
    EA('Divorce - DJ Manny Remix', 'Kelela/DJ Manny', 'RAVE:N, The Remixes', 'Kelela'),
    EA('Bruises (SUCIA! Remix)', 'Kelela, SUCIA!', 'RAVE:N, The Remixes', 'Kelela'),
])


def shot(title, artist):
    e, tier = SHOT.match(row(title, artist))
    return (e['title'], tier) if e else (None, None)


@pytest.mark.parametrize('title,uploader,want', [
    # truncated slug; plain track wins over its [Instrumental] twin
    ('captain murphy hovercrafts and', 'selftitledmag', 'Hovercrafts and Cows (Prod Flying Lotus)'),
    # slug reads "<artist> <ALBUM> <title-start>"
    ('diversa underscore awkward', '\u0486\u0485a', 'awkward silence ft. oneira'),
    ('diversa underscore trigger', '\u0486\u0485a', 'trigger happy'),
    # 4-char truncation, both names tagged as artists
    ('alina baraz galimatias make', 'Galimatias', 'Make You Feel'),
    ('alina baraz galimatias pretty', 'Galimatias', 'Pretty Thoughts'),
    # remixer is ALSO a tagged artist and the slug dropped the word "remix"
    ('closure flexulant x bambii', 'KELELA', 'Closure - Flexulant x BAMBII Remix feat. Rahrah Gabor & Brazy'),
    # abbreviated name inside the title: ordered subset
    ('contact kg remix', 'KELELA', 'Contact - Karen Nyame KG Remix'),
])
def test_screenshot_cases(title, uploader, want):
    assert shot(title, uploader)[0] == want


@pytest.mark.parametrize('title,uploader', [
    ('divorce loraine james remix', 'KELELA'),        # local one is DJ Manny's remix - different track
    ('Kelela - Bruises (OSSX Remix)', 'OSSX'),        # local one is SUCIA!'s remix - different track
    ('diversa underscore', '\u0486\u0485a'),          # album name only, no title at all
])
def test_screenshot_must_not_match(title, uploader):
    assert shot(title, uploader)[0] is None


def test_instrumental_row_picks_instrumental():
    assert shot('captain murphy hovercrafts and cows instrumental', 'selftitledmag')[0] == \
        'Hovercrafts and Cows [Instrumental]'
