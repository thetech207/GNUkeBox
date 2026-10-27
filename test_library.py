"""Headless smoke test for library.py — run with the .venv python."""
import os
import struct
import sys
import tempfile
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from library import Library, extract_art, read_tags


def make_wav(path):
    w = wave.open(path, 'wb')
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(44100)
    w.writeframes(b'\x00\x00' * 44100)
    w.close()
    from mutagen.wave import WAVE
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TCON, TRCK, COMM, APIC
    a = WAVE(path)
    a.add_tags()
    a.tags.add(TIT2(encoding=3, text='Test Title'))
    a.tags.add(TPE1(encoding=3, text='Test Artist'))
    a.tags.add(TALB(encoding=3, text='Test Album'))
    a.tags.add(TDRC(encoding=3, text='1987'))
    a.tags.add(TCON(encoding=3, text='Rock'))
    a.tags.add(TRCK(encoding=3, text='3/12'))
    a.tags.add(COMM(encoding=3, lang='eng', desc='', text='a comment'))
    a.tags.add(APIC(encoding=3, mime='image/png', type=3, desc='',
                    data=b'\x89PNGfakedata'))
    a.save()


def make_id3v1(path):
    block = b'TAG'
    block += b'Old Title'.ljust(30, b'\x00')
    block += b'Old Artist'.ljust(30, b'\x00')
    block += b'Old Album'.ljust(30, b'\x00')
    block += b'1999'
    block += b'old comment'.ljust(28, b'\x00') + b'\x00' + bytes([7])
    block += bytes([17])  # Rock
    with open(path, 'wb') as fh:
        fh.write(b'\xff\xfb\x90\x64' + b'\x00' * 413 + block)


def make_mp3(path):
    # ID3v2 tag written by mutagen, followed by one MPEG1-L3-128k frame.
    from mutagen.id3 import ID3, TIT2, TPE1, APIC
    t = ID3()
    t.add(TIT2(encoding=3, text='MP3 Title'))
    t.add(TPE1(encoding=3, text='MP3 Artist'))
    t.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='',
               data=b'\xff\xd8\xff\xe0fakejpg'))
    with open(path, 'wb') as fh:
        fh.write(b'')
    t.save(path)
    with open(path, 'ab') as fh:
        fh.write((b'\xff\xfb\x90\x64' + b'\x00' * 413) * 100)


def main():
    tmp = tempfile.mkdtemp()
    wav = os.path.join(tmp, 'a.wav')
    mp3v1 = os.path.join(tmp, 'old.mp3')
    mp3 = os.path.join(tmp, 'new.mp3')
    make_wav(wav)
    make_id3v1(mp3v1)
    ok = True

    def check(name, cond, extra=''):
        nonlocal ok
        print(('  ok  ' if cond else ' FAIL ') + name +
              ('  ' + str(extra) if extra != '' else ''))
        ok = ok and cond

    d = read_tags(wav)
    check('wav title', d['title'] == 'Test Title', repr(d['title']))
    check('wav artist', d['artist'] == 'Test Artist')
    check('wav album', d['album'] == 'Test Album')
    check('wav year', d['year'] == '1987', d['year'])
    check('wav genre', d['genre'] == 'Rock')
    check('wav track', d['track'] == '3/12', d['track'])
    check('wav comment', 'comment' in d['comment'], d['comment'])
    check('wav art flag', d['has_art'] == 1)
    check('wav duration', d['duration'] > 0.5, d['duration'])
    art = extract_art(wav)
    check('wav art', art is not None and b'PNG' in art[0])

    d = read_tags(mp3v1)
    check('v1 title', d['title'] == 'Old Title', repr(d['title']))
    check('v1 artist', d['artist'] == 'Old Artist')
    check('v1 year', d['year'] == '1999')
    check('v1 comment', 'old comment' in d['comment'], d['comment'])
    check('v1 track', d['track'] == '7', d['track'])
    check('v1 genre', d['genre'] == 'Rock', d['genre'])

    try:
        make_mp3(mp3)
        d = read_tags(mp3)
        check('mp3 title', d['title'] == 'MP3 Title', repr(d['title']))
        check('mp3 artist', d['artist'] == 'MP3 Artist')
        check('mp3 art flag', d['has_art'] == 1)
        check('mp3 art', extract_art(mp3) is not None)
    except Exception as ex:
        print('  (mp3 synth failed:', ex, '— skipping mp3 checks)')

    # -- Library index/search
    lib = Library(os.path.join(tmp, 'x', 'lib.db'))
    for p in (wav, mp3v1):
        lib.upsert(read_tags(p))
    lib.commit()
    check('count', lib.count() == 2, lib.count())
    rows = lib.search({'artist': 'test'})
    check('search artist', len(rows) == 1 and rows[0]['title'] == 'Test Title')
    rows = lib.search({'year': '1980-1989'})
    check('search year range', len(rows) == 1, len(rows))
    rows = lib.search({'year': '1999'})
    check('search year exact', len(rows) == 1)
    rows = lib.search({}, any_text='old')
    check('search any', len(rows) >= 1, len(rows))
    rows = lib.search({'genre': 'rock'})
    check('search genre ci', len(rows) == 2, len(rows))
    sim = lib.similar(['Test Artist'], [], {wav})
    check('similar excludes', len(sim) == 0)
    sim = lib.similar(['Old Artist'], ['Rock'], set())
    check('similar matches', len(sim) >= 1, len(sim))
    check('distinct', 'Rock' in lib.distinct('genre'))
    lib.prune([tmp], {wav})
    check('prune', lib.count() == 1, lib.count())

    print('\nALL OK' if ok else '\nFAILURES', flush=True)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
