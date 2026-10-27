# GNUkeBox

A search-driven jukebox for large local music collections on
Debian/Ubuntu. Point it at one or more music folders, type into any tag
field on the left (Title, Artist, Album, Year, Genre, Track, Comment —
the classic ID3v1 set, plus "search everything"), hit Search, and it
builds a playlist and just plays. When the playlist ends it keeps going
with tracks that share artists/genres with what you searched for.

## Install

```
sudo apt install python3-pyqt5 python3-pyqt5.qtmultimedia python3-mutagen \
    libqt5multimedia5-plugins gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-ugly gstreamer1.0-libav gstreamer1.0-pulseaudio
```

`libqt5multimedia5-plugins` is the part that provides Qt's GStreamer
playback service — without it you get
`No service found for "org.qt-project.qt.mediaplayer"` and tracks won't
play. The `gstreamer1.0-plugins-*` packages cover MP3, FLAC, Ogg/Vorbis,
Opus, M4A/AAC, WAV, WMA and more; `gstreamer1.0-pulseaudio` is the audio
output (works with PulseAudio and PipeWire; use `gstreamer1.0-alsa`
instead on a pure-ALSA setup).

## Run

```
./gnukebox.py        # or:  python3 gnukebox.py
```

Optional desktop integration:

```
mkdir -p ~/.local/share/applications
cp GNUkeBox.desktop ~/.local/share/applications/
# edit the Exec=/Icon= paths inside to match where you put the folder
```

## Use

- **Music folders** (top left): Add… / Remove / Rescan. Folders are
  remembered in `~/.config/GNUkeBox/config.json`; the tag index lives in
  `~/.local/share/GNUkeBox/library.db` and only re-reads changed files.
- **Search tags** (left): every filled-in field must match (AND,
  substring, case-insensitive). Year also accepts ranges like
  `1980-1989`. Empty search = whole library. Artist/Album/Genre fields
  autocomplete from your collection.
- **Playlist**: double-click to play a track; right-click for
  Play / Play next / Remove / Clear.
- **Transport**: shuffle toggle, previous, play/pause, stop, next,
  volume, and a click-and-drag seek bar.
- **Now playing**: the bottom bar shows art + all tag details. Click the
  art — or press **F11**, or just maximize the window — for the
  full-screen now-playing view (big art, seek bar, transport).
  **Esc** or **F11** exits.
- **Auto-continue**: at the end of the playlist it appends more tracks
  sharing artists/genres with the current queue so it never dead-ends.
- **Ctrl+F** focuses the search box.

## Files

- `gnukebox.py` — the whole GUI/player (PyQt5)
- `library.py` — tag reading (mutagen; ID3v1+v2, Vorbis/FLAC, MP4,
  WMA, plus a hand-rolled ID3v1 fallback) and the SQLite index
- `test_library.py` — headless tests for the tag/db layer

## Dev

```
python3 -m venv .venv && .venv/bin/pip install mutagen PyQt5
.venv/bin/python test_library.py
```
