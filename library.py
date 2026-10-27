"""library.py — tag reading, album-art extraction and the SQLite library index.

No Qt imports here; this module only needs mutagen + the standard library,
so it can be tested headlessly.
"""

import base64
import os
import re
import sqlite3
import threading

AUDIO_EXTS = {
    '.mp3', '.flac', '.ogg', '.oga', '.opus', '.m4a', '.mp4', '.aac',
    '.wav', '.wma', '.aiff', '.aif', '.wv', '.ape', '.mka', '.mpc',
    '.spx', '.tta', '.dsf', '.mid',
}

# Columns stored per track (besides path/mtime/size which are bookkeeping).
TAG_FIELDS = ('title', 'artist', 'album', 'year', 'genre', 'track', 'comment')

# Classic ID3v1 genre table (indexes 0-79 plus the common 80-191 extensions).
ID3V1_GENRES = (
    'Blues', 'Classic Rock', 'Country', 'Dance', 'Disco', 'Funk', 'Grunge',
    'Hip-Hop', 'Jazz', 'Metal', 'New Age', 'Oldies', 'Other', 'Pop', 'R&B',
    'Rap', 'Reggae', 'Rock', 'Techno', 'Industrial', 'Alternative', 'Ska',
    'Death Metal', 'Pranks', 'Soundtrack', 'Euro-Techno', 'Ambient',
    'Trip-Hop', 'Vocal', 'Jazz+Funk', 'Fusion', 'Trance', 'Classical',
    'Instrumental', 'Acid', 'House', 'Game', 'Sound Clip', 'Gospel', 'Noise',
    'Alt. Rock', 'Bass', 'Soul', 'Punk', 'Space', 'Meditative',
    'Instrumental Pop', 'Instrumental Rock', 'Ethnic', 'Gothic', 'Darkwave',
    'Techno-Industrial', 'Electronic', 'Pop-Folk', 'Eurodance', 'Dream',
    'Southern Rock', 'Comedy', 'Cult', 'Gangsta Rap', 'Top 40',
    'Christian Rap', 'Pop/Funk', 'Jungle', 'Native American', 'Cabaret',
    'New Wave', 'Psychedelic', 'Rave', 'Showtunes', 'Trailer', 'Lo-Fi',
    'Tribal', 'Acid Punk', 'Acid Jazz', 'Polka', 'Retro', 'Musical',
    'Rock & Roll', 'Hard Rock', 'Folk', 'Folk-Rock', 'National Folk',
    'Swing', 'Fast Fusion', 'Bebop', 'Latin', 'Revival', 'Celtic',
    'Bluegrass', 'Avantgarde', 'Gothic Rock', 'Progressive Rock',
    'Psychedelic Rock', 'Symphonic Rock', 'Slow Rock', 'Big Band',
    'Chorus', 'Easy Listening', 'Acoustic', 'Humour', 'Speech', 'Chanson',
    'Opera', 'Chamber Music', 'Sonata', 'Symphony', 'Booty Bass', 'Primus',
    'Porn Groove', 'Satire', 'Slow Jam', 'Club', 'Tango', 'Samba',
    'Folklore', 'Ballad', 'Power Ballad', 'Rhythmic Soul', 'Freestyle',
    'Duet', 'Punk Rock', 'Drum Solo', 'A Cappella', 'Euro-House',
    'Dance Hall', 'Goa', 'Drum & Bass', 'Club-House', 'Hardcore',
    'Terror', 'Indie', 'BritPop', 'Negerpunk', 'Polsk Punk', 'Beat',
    'Christian Gangsta Rap', 'Heavy Metal', 'Black Metal', 'Crossover',
    'Contemporary Christian', 'Christian Rock', 'Merengue', 'Salsa',
    'Thrash Metal', 'Anime', 'JPop', 'Synthpop', 'Abstract', 'Art Rock',
    'Baroque', 'Bhangra', 'Big Beat', 'Breakbeat', 'Chillout', 'Downtempo',
    'Dub', 'EBM', 'Eclectic', 'Electro', 'Electroclash', 'Emo',
    'Experimental', 'Garage', 'Global', 'IDM', 'Illbient',
    'Industro-Goth', 'Jam Band', 'Krautrock', 'Leftfield', 'Lounge',
    'Math Rock', 'New Romantic', 'Nu-Breakz', 'Post-Punk', 'Post-Rock',
    'Psytrance', 'Shoegaze', 'Space Rock', 'Trop Rock', 'World Music',
    'Neoclassical', 'Audiobook', 'Audio Theatre', 'Neue Deutsche Welle',
    'Podcast', 'Indie Rock', 'G-Funk', 'Dubstep', 'Garage Rock',
    'Psybient',
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    path     TEXT PRIMARY KEY,
    mtime    REAL,
    size     INTEGER,
    title    TEXT,
    artist   TEXT,
    album    TEXT,
    year     TEXT,
    genre    TEXT,
    track    TEXT,
    comment  TEXT,
    duration REAL,
    has_art  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_artist ON tracks(artist COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_album  ON tracks(album  COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_genre  ON tracks(genre  COLLATE NOCASE);
"""

_SEARCHABLE = ('title', 'artist', 'album', 'year', 'genre', 'track',
               'comment')


def _clean(v):
    """Coerce a mutagen value to a stripped string ('' if unusable)."""
    if v is None:
        return ''
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ''
    try:
        return str(v).strip()
    except Exception:
        return ''


def _first(tags, *keys):
    """First non-empty value among vorbis-style keys."""
    for k in keys:
        v = _clean(tags.get(k))
        if v:
            return v
    return ''


def _year(s):
    m = re.search(r'(\d{4})', s or '')
    return m.group(1) if m else (s or '')


def _id3v1(path, d):
    """Manual fallback for the fixed 128-byte ID3v1 block."""
    try:
        with open(path, 'rb') as fh:
            fh.seek(-128, os.SEEK_END)
            blk = fh.read(128)
        if len(blk) != 128 or blk[:3] != b'TAG':
            return
        dec = lambda b: b.split(b'\x00', 1)[0].decode('latin-1').strip()
        if not d['title']:
            d['title'] = dec(blk[3:33])
        if not d['artist']:
            d['artist'] = dec(blk[33:63])
        if not d['album']:
            d['album'] = dec(blk[63:93])
        if not d['year']:
            d['year'] = dec(blk[93:97])
        if blk[125] == 0 and blk[126] != 0:  # v1.1: 28-byte comment + track
            if not d['comment']:
                d['comment'] = dec(blk[97:125])
            if not d['track']:
                d['track'] = str(blk[126])
        elif not d['comment']:
            d['comment'] = dec(blk[97:127])
        g = blk[127]
        if not d['genre'] and g < len(ID3V1_GENRES):
            d['genre'] = ID3V1_GENRES[g]
    except (OSError, IOError):
        pass


def _from_id3(tags, d):
    """Pull fields from an ID3 object (covers ID3v2 and ID3v1 read by mutagen)."""
    def frame(*ids):
        for i in ids:
            f = tags.get(i)
            if f is not None:
                s = _clean(f)
                if s:
                    return s
        return ''
    d['title'] = d['title'] or frame('TIT2')
    d['artist'] = d['artist'] or frame('TPE1', 'TPE2')
    d['album'] = d['album'] or frame('TALB')
    d['year'] = d['year'] or _year(frame('TDRC', 'TYER', 'TDOR'))
    d['genre'] = d['genre'] or frame('TCON')
    d['track'] = d['track'] or frame('TRCK')
    if not d['comment']:
        for c in tags.getall('COMM'):
            s = _clean(c)
            if s:
                d['comment'] = s
                break
    if tags.getall('APIC'):
        d['has_art'] = 1


def _from_vorbis(tags, d):
    """FLAC / Ogg Vorbis / Opus / APEv2-style key=value tags."""
    def g(*ks):
        for k in ks:
            v = _first(tags, k, k.upper(), k.lower())
            if v:
                return v
        return ''
    d['title'] = d['title'] or g('title')
    d['artist'] = d['artist'] or g('artist', 'albumartist')
    d['album'] = d['album'] or g('album')
    d['year'] = d['year'] or _year(g('date', 'year'))
    d['genre'] = d['genre'] or g('genre')
    d['track'] = d['track'] or g('tracknumber', 'track')
    d['comment'] = d['comment'] or g('comment', 'description')
    if _first(tags, 'metadata_block_picture', 'METADATA_BLOCK_PICTURE',
              'coverart'):
        d['has_art'] = 1


def _from_mp4(tags, d):
    d['title'] = d['title'] or _first(tags, '\xa9nam')
    d['artist'] = d['artist'] or _first(tags, '\xa9ART', 'aART')
    d['album'] = d['album'] or _first(tags, '\xa9alb')
    d['year'] = d['year'] or _year(_first(tags, '\xa9day'))
    d['genre'] = d['genre'] or _first(tags, '\xa9gen', 'gnre')
    tr = tags.get('trkn')
    if tr and not d['track']:
        try:
            d['track'] = str(tr[0][0])
        except Exception:
            pass
    d['comment'] = d['comment'] or _first(tags, '\xa9cmt')
    if tags.get('covr'):
        d['has_art'] = 1


def _from_asf(tags, d):
    """WMA / ASF."""
    d['title'] = d['title'] or _first(tags, 'Title')
    d['artist'] = d['artist'] or _first(tags, 'Author', 'WM/Author')
    d['album'] = d['album'] or _first(tags, 'WM/AlbumTitle')
    d['year'] = d['year'] or _year(_first(tags, 'WM/Year',
                                          'WM/OriginalReleaseTime'))
    d['genre'] = d['genre'] or _first(tags, 'WM/Genre')
    d['track'] = d['track'] or _first(tags, 'WM/TrackNumber', 'WM/Track')
    d['comment'] = d['comment'] or _first(tags, 'Description',
                                        'WM/Comments')
    if tags.get('WM/Picture'):
        d['has_art'] = 1


def read_tags(path):
    """Return a dict of tag fields for *path*; never raises."""
    d = dict.fromkeys(TAG_FIELDS, '')
    d.update(path=path, mtime=0.0, size=0, duration=0.0, has_art=0)
    try:
        st = os.stat(path)
        d['mtime'], d['size'] = st.st_mtime, st.st_size
    except OSError:
        return d

    audio = None
    try:
        import mutagen
        audio = mutagen.File(path)
    except Exception:
        audio = None

    if audio is not None:
        try:
            d['duration'] = float(getattr(audio.info, 'length', 0) or 0)
        except Exception:
            pass
        tags = getattr(audio, 'tags', None)
        if tags is not None:
            try:
                import mutagen.id3
                import mutagen.mp4
                import mutagen.asf
                if isinstance(tags, mutagen.id3.ID3):
                    _from_id3(tags, d)
                elif isinstance(tags, mutagen.mp4.MP4Tags):
                    _from_mp4(tags, d)
                elif isinstance(tags, mutagen.asf.ASFTags):
                    _from_asf(tags, d)
                else:
                    _from_vorbis(tags, d)
            except ImportError:
                _from_vorbis(tags, d)
        if type(audio).__name__ in ('FLAC', 'OggFLAC') and \
                getattr(audio, 'pictures', None):
            d['has_art'] = 1
        if not any(d[f] for f in TAG_FIELDS):
            _id3v1(path, d)
    else:
        _id3v1(path, d)

    if not d['title']:
        d['title'] = os.path.splitext(os.path.basename(path))[0]
    return d


def extract_art(path):
    """Return (bytes, mimetype) for embedded art, else None."""
    try:
        import mutagen
        audio = mutagen.File(path)
    except Exception:
        audio = None
    if audio is not None:
        tags = getattr(audio, 'tags', None)
        try:
            import mutagen.id3
            if isinstance(tags, mutagen.id3.ID3):
                apics = tags.getall('APIC')
                if apics:
                    return bytes(apics[0].data), apics[0].mime
        except Exception:
            pass
        pics = getattr(audio, 'pictures', None)
        if pics:  # FLAC
            return bytes(pics[0].data), pics[0].mime
        if tags is not None:
            blk = _first(tags, 'metadata_block_picture',
                         'METADATA_BLOCK_PICTURE')
            if blk:  # Ogg/Opus: base64'd FLAC Picture block
                try:
                    import mutagen.flac
                    p = mutagen.flac.Picture(base64.b64decode(blk))
                    return bytes(p.data), p.mime
                except Exception:
                    pass
            cov = tags.get('covr')
            if cov:  # MP4
                return bytes(cov[0]), getattr(cov[0], 'mime', 'image/jpeg')
            pic = tags.get('WM/Picture')
            if pic:  # WMA: [type][size][mime\0][desc\0(utf16)][data]
                try:
                    b = bytes(pic[0])
                    off = 5
                    off = b.index(b'\x00', off) + 1
                    off = b.index(b'\x00\x00', off) + 2
                    return b[off:], 'image/jpeg'
                except Exception:
                    pass
    # Folder art convention as a last resort.
    for name in ('cover.jpg', 'folder.jpg', 'front.jpg', 'album.jpg',
                 'cover.png', 'folder.png', 'front.png', 'album.png'):
        cand = os.path.join(os.path.dirname(path), name)
        try:
            with open(cand, 'rb') as fh:
                return fh.read(), 'image/jpeg'
        except OSError:
            continue
    return None


class Library:
    """SQLite-backed track index."""

    def __init__(self, db_path):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.db.executescript(_SCHEMA)
        self.db.commit()

    # -- writes ------------------------------------------------------------
    def upsert(self, d):
        cols = ('path', 'mtime', 'size') + TAG_FIELDS + ('duration',
                                                         'has_art')
        with self._lock:
            self.db.execute(
                'INSERT OR REPLACE INTO tracks (%s) VALUES (%s)' % (
                    ','.join(cols), ','.join('?' * len(cols))),
                [d.get(c) for c in cols])

    def commit(self):
        with self._lock:
            self.db.commit()

    def known(self):
        with self._lock:
            return {r[0]: r[1] for r in
                    self.db.execute('SELECT path, mtime FROM tracks')}

    def prune(self, roots, keep):
        """Drop rows under *roots* that are not in the *keep* set."""
        with self._lock:
            for root in roots:
                dead = [r[0] for r in self.db.execute(
                    'SELECT path FROM tracks WHERE path LIKE ?',
                    (root.rstrip(os.sep) + os.sep + '%',))
                    if r[0] not in keep]
                self.db.executemany('DELETE FROM tracks WHERE path=?',
                                    [(p,) for p in dead])
            self.db.commit()

    # -- reads -------------------------------------------------------------
    def count(self):
        with self._lock:
            return self.db.execute(
                'SELECT COUNT(*) FROM tracks').fetchone()[0]

    def distinct(self, field):
        if field not in _SEARCHABLE:
            return []
        with self._lock:
            return [r[0] for r in self.db.execute(
                'SELECT DISTINCT %s FROM tracks WHERE %s != "" ORDER BY 1'
                % (field, field)).fetchall()]

    @staticmethod
    def _like(v):
        return '%' + v.replace('\\', '\\\\').replace('%', '\\%') \
                      .replace('_', '\\_') + '%'

    def search(self, filters, any_text='', limit=5000):
        """filters: {field: text}; every non-empty field must match (AND)."""
        sql = ['SELECT * FROM tracks']
        where, args = [], []
        for f in _SEARCHABLE:
            v = (filters.get(f) or '').strip()
            if not v:
                continue
            if f == 'year':
                m = re.match(r'^\s*(\d{4})\s*[-–]\s*(\d{4})\s*$', v)
                if m:
                    lo, hi = sorted((int(m.group(1)), int(m.group(2))))
                    where.append(
                        "CAST(substr(year,1,4) AS INT) BETWEEN ? AND ?")
                    args += [lo, hi]
                    continue
            where.append("%s LIKE ? ESCAPE '\\'" % f)
            args.append(self._like(v))
        if any_text.strip():
            v = self._like(any_text.strip())
            ors = ["%s LIKE ? ESCAPE '\\'" % f for f in
                   ('title', 'artist', 'album', 'genre', 'comment', 'path')]
            where.append('(' + ' OR '.join(ors) + ')')
            args += [v] * 6
        if where:
            sql.append('WHERE ' + ' AND '.join(where))
        sql.append('ORDER BY LOWER(artist), LOWER(album), '
                   'CAST(track AS INT), LOWER(title) LIMIT %d' % limit)
        with self._lock:
            return self.db.execute(' '.join(sql), args).fetchall()

    def similar(self, artists, genres, exclude, limit=100):
        """Tracks sharing an artist or genre with the given sets."""
        where, args = [], []
        if artists:
            where.append('LOWER(artist) IN (%s)'
                         % ','.join('?' * len(artists)))
            args += [a.lower() for a in artists]
        if genres:
            where.append('LOWER(genre) IN (%s)'
                         % ','.join('?' * len(genres)))
            args += [g.lower() for g in genres]
        if not where:
            where = ['1=1']
        sql = ('SELECT * FROM tracks WHERE (%s) ORDER BY RANDOM() LIMIT ?'
               % ' OR '.join(where))
        with self._lock:
            rows = self.db.execute(sql, args + [limit * 4]).fetchall()
        return [r for r in rows if r['path'] not in exclude][:limit]

    def get(self, path):
        with self._lock:
            return self.db.execute('SELECT * FROM tracks WHERE path=?',
                                   (path,)).fetchone()
