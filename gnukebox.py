#!/usr/bin/env python3
"""GNUkeBox — a search-driven jukebox for large local music collections.

Add folders, it indexes ID3/Vorbis/MP4 tags into SQLite; type into any tag
field on the left to build a playlist and let it run unattended. When a
playlist ends it keeps going with tracks sharing the same artists/genres.

Deps (Debian/Ubuntu):  python3-pyqt5  python3-pyqt5.qtmultimedia
                       python3-mutagen
"""

import json
import os
import random
import sys

from PyQt5.QtCore import (QEvent, QSize, QStringListModel, Qt, QThread, QTimer,
                          QUrl, pyqtSignal)
from PyQt5.QtGui import (QColor, QFont, QIcon, QKeySequence, QLinearGradient,
                         QPainter, QPen, QPixmap)
from PyQt5.QtMultimedia import (QMediaContent, QMediaPlayer,
                                QMultimedia)
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                             QCompleter, QFileDialog, QFrame, QGroupBox,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QListWidget, QMainWindow, QMenu, QMessageBox,
                             QPushButton, QSizePolicy, QSlider, QSplitter,
                             QStackedWidget, QStyle, QTableWidget,
                             QTableWidgetItem, QToolButton, QVBoxLayout,
                             QWidget)

from library import AUDIO_EXTS, Library, TAG_FIELDS, extract_art, read_tags

APP = 'GNUkeBox'
CONFIG = os.path.expanduser('~/.config/GNUkeBox/config.json')
DBPATH = os.path.expanduser('~/.local/share/GNUkeBox/library.db')

FIELD_LABELS = (('title', 'Title'), ('artist', 'Artist'),
                ('album', 'Album'), ('year', 'Year'),
                ('genre', 'Genre'), ('track', 'Track'),
                ('comment', 'Comment'))

STYLE = """
* { font-size: 13px; }
QMainWindow, QWidget { background: #16171b; color: #dddde2; }
QSplitter::handle { background: #0c0d10; width: 3px; }
QGroupBox { border: 1px solid #33363e; border-radius: 6px; margin-top: 10px;
            padding-top: 10px; font-weight: bold; color: #9da3b0; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; }
QLineEdit, QListWidget, QTableWidget, QComboBox {
    background: #1f2127; border: 1px solid #33363e; border-radius: 4px;
    padding: 4px; selection-background-color: #e95420;
    selection-color: #fff; }
QLineEdit:focus, QListWidget:focus, QTableWidget:focus {
    border: 1px solid #e95420; }
QTableWidget { gridline-color: #2a2d34; }
QHeaderView::section { background: #22242b; color: #9da3b0; border: 0;
    border-bottom: 1px solid #33363e; padding: 4px; }
QPushButton, QToolButton { background: #262932; border: 1px solid #383c46;
    border-radius: 5px; padding: 6px 12px; }
QPushButton:hover, QToolButton:hover { background: #313543; }
QPushButton:pressed, QToolButton:pressed,
QPushButton:checked, QToolButton:checked {
    background: #e95420; border-color: #e95420; color: #fff; }
QPushButton:disabled, QToolButton:disabled { color: #5a5e68; }
QPushButton#accent { background: #e95420; border-color: #e95420;
    color: #fff; font-weight: bold; }
QPushButton#accent:hover { background: #f06430; }
QSlider::groove:horizontal { height: 6px; background: #2a2d34;
    border-radius: 3px; }
QSlider::sub-page:horizontal { background: #e95420; border-radius: 3px; }
QSlider::handle:horizontal { background: #f0f0f2; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px; }
QSlider::handle:horizontal:hover { background: #fff; }
QLabel { color: #c7cad2; }
QLabel#npTitle { font-size: 15px; font-weight: bold; color: #f4f4f6; }
QLabel#npSub { color: #9da3b0; }
QLabel#bigTitle { font-size: 30px; font-weight: bold; color: #fff; }
QLabel#bigSub { font-size: 19px; color: #c7cad2; }
QLabel#bigTags { font-size: 14px; color: #8b90a0; }
QLabel#time { color: #9da3b0; }
QLabel#artThumb, QLabel#artBig { background: #101116;
    border: 1px solid #33363e; border-radius: 6px; }
QStatusBar { background: #101116; color: #8b90a0; }
QMenu { background: #1f2127; border: 1px solid #383c46; }
QMenu::item:selected { background: #e95420; }
QToolTip { background: #262932; color: #dddde2; border: 1px solid #383c46; }
"""


def load_config():
    try:
        with open(CONFIG) as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, 'w') as fh:
            json.dump(cfg, fh, indent=2)
    except OSError:
        pass


def fmt_time(ms):
    s = max(0, int(ms // 1000))
    return '%d:%02d' % (s // 60, s % 60)


def shuffle_icon(color='#d6d6dc'):
    """Classic two-crossing-arrows shuffle glyph, drawn to a pixmap."""
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 2, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(3, 9, 10, 9)     # top-left in
    p.drawLine(10, 9, 20, 23)   # cross down
    p.drawLine(3, 23, 10, 23)   # bottom-left in
    p.drawLine(10, 23, 20, 9)   # cross up
    for y in (9, 23):           # shafts + arrowheads on the right
        p.drawLine(20, y, 27, y)
        p.drawLine(21, y - 4, 28, y)
        p.drawLine(21, y + 4, 28, y)
    p.end()
    return QIcon(pm)


def placeholder_art(size):
    """Generated 'no art' tile — dark gradient with a note glyph."""
    pm = QPixmap(size, size)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor('#262932'))
    g.setColorAt(1, QColor('#14151a'))
    p = QPainter(pm)
    p.fillRect(0, 0, size, size, g)
    p.setPen(QColor('#3d4250'))
    f = QFont(); f.setPixelSize(int(size * .55))
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, '\u266a')
    p.end()
    return pm


class SeekSlider(QSlider):
    """QSlider that seeks to the clicked position."""
    seeked = pyqtSignal(int)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            v = self.style().sliderValueFromPosition(
                self.minimum(), self.maximum(), e.pos().x(), self.width())
            self.setValue(v)
            self.seeked.emit(v)
        super().mousePressEvent(e)


class Scanner(QThread):
    """Background recursive scan + tag extraction into the Library index."""
    progress = pyqtSignal(int, str)
    done = pyqtSignal(int, bool)  # files seen, was-cancelled

    def __init__(self, lib, folders, parent=None):
        super().__init__(parent)
        self.lib, self.folders = lib, folders
        self._stop = False

    def cancel(self):
        self._stop = True

    def run(self):
        try:
            known = self.lib.known()
        except Exception:
            known = {}
        seen, n = set(), 0
        for root in self.folders:
            if self._stop:
                break
            for dirpath, dirnames, filenames in os.walk(root):
                if self._stop:
                    break
                dirnames[:] = [d for d in dirnames
                               if not d.startswith('.')]
                for name in filenames:
                    if os.path.splitext(name)[1].lower() not in AUDIO_EXTS:
                        continue
                    path = os.path.join(dirpath, name)
                    seen.add(path)
                    try:
                        mt = os.stat(path).st_mtime
                    except OSError:
                        continue
                    if known.get(path) == mt:
                        continue
                    d = read_tags(path)
                    d['mtime'] = mt
                    self.lib.upsert(d)
                    n += 1
                    if n % 20 == 0:
                        self.lib.commit()
                        self.progress.emit(n, path)
            self.lib.commit()
        if not self._stop:
            self.lib.prune(self.folders, seen)
        self.done.emit(n, self._stop)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.lib = Library(DBPATH)
        self.queue = []            # list[sqlite Row-ish dict]
        self.queue_set = set()     # paths already queued
        self.idx = -1
        self.history = []          # shuffle-mode back stack
        self._seeking = False
        self._in_fs = False
        self._fs_guard = False
        self._art_cache = {}
        self._ph = placeholder_art(512)
        self.scanner = None
        self._last_filters = {}
        self._shuffle_played = set()   # queue indices already shuffled
        self._err_streak = 0           # consecutive playback errors

        self.setWindowTitle(APP)
        self.setWindowIcon(self._app_icon())
        self.resize(self.cfg.get('w', 1180), self.cfg.get('h', 720))

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_browser_page())
        self.stack.addWidget(self._build_fullscreen_page())
        self.setCentralWidget(self.stack)
        self.statusBar().showMessage('Ready — %d tracks indexed'
                                     % self.lib.count())

        self._wire_player()
        QTimer.singleShot(600, self._check_service)
        self._apply_volume(self.cfg.get('volume', 80))
        self.shuffle_btn.setChecked(bool(self.cfg.get('shuffle')))
        self._load_folder_list()
        self._refresh_completers()
        if self.folder_list.count():
            QTimer.singleShot(300, self.start_scan)
        else:
            self.statusBar().showMessage(
                'Add a music folder on the left to build your library')

    # ------------------------------------------------------------------ UI
    def _app_icon(self):
        pm = QPixmap(64, 64)
        pm.fill(QColor('#16171b'))
        p = QPainter(pm)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#e95420'))
        p.drawEllipse(6, 6, 52, 52)
        p.setBrush(QColor('#16171b'))
        p.drawEllipse(24, 24, 16, 16)
        p.end()
        return QIcon(pm)

    def _mk_btn(self, icon, tip, fn=None, checkable=False):
        b = QToolButton()
        b.setIcon(self.style().standardIcon(icon))
        b.setIconSize(QSize(22, 22))
        b.setToolTip(tip)
        b.setCheckable(checkable)
        if fn:
            b.clicked.connect(fn)
        return b

    def _build_browser_page(self):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        lay.addWidget(split)

        # ----- left: folders + search
        left = QWidget()
        left.setMinimumWidth(280)
        left.setMaximumWidth(430)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 8, 8)

        g = QGroupBox('Music folders')
        gl = QVBoxLayout(g)
        self.folder_list = QListWidget()
        self.folder_list.setMaximumHeight(110)
        gl.addWidget(self.folder_list)
        fb = QHBoxLayout()
        for text, fn in (('Add…', self.add_folder),
                         ('Remove', self.remove_folder),
                         ('Rescan', self.start_scan)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            fb.addWidget(b)
        self.scan_lbl = QLabel('')
        gl.addLayout(fb)
        gl.addWidget(self.scan_lbl)
        ll.addWidget(g)

        s = QGroupBox('Search tags')
        sl = QVBoxLayout(s)
        self.any_edit = QLineEdit()
        self.any_edit.setPlaceholderText('Search everything…')
        self.any_edit.returnPressed.connect(self.run_search)
        sl.addWidget(self.any_edit)
        self.edits = {}
        for key, label in FIELD_LABELS:
            e = QLineEdit()
            e.setPlaceholderText(label)
            e.setClearButtonEnabled(True)
            e.returnPressed.connect(self.run_search)
            self.edits[key] = e
            sl.addWidget(e)
        row = QHBoxLayout()
        self.autoplay_chk = QCheckBox('Auto-play')
        self.autoplay_chk.setChecked(True)
        self.autoplay_chk.setToolTip('Start the first result immediately')
        search_btn = QPushButton('Search')
        search_btn.setObjectName('accent')
        search_btn.clicked.connect(self.run_search)
        clear_btn = QPushButton('Clear')
        clear_btn.clicked.connect(self.clear_search)
        row.addWidget(self.autoplay_chk)
        row.addStretch(1)
        row.addWidget(clear_btn)
        row.addWidget(search_btn)
        sl.addLayout(row)
        hint = QLabel('Empty fields are ignored; every filled\n'
                      'field must match. Year accepts e.g.\n'
                      '1985 or 1980-1989.')
        hint.setStyleSheet('color:#6b7080')
        sl.addWidget(hint)
        sl.addStretch(1)
        fs_btn = QPushButton('Now Playing  (F11)')
        fs_btn.clicked.connect(self.enter_fullscreen)
        sl.addWidget(fs_btn)
        ll.addWidget(s, 1)

        # ----- right: playlist + transport
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 8, 8, 8)

        self.results_lbl = QLabel('Playlist')
        self.results_lbl.setStyleSheet('color:#8b90a0')
        rl.addWidget(self.results_lbl)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ('Title', 'Artist', 'Album', 'Genre', 'Time'))
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        for c, w in ((1, 160), (2, 160), (3, 90), (4, 48)):
            self.table.setColumnWidth(c, w)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.itemDoubleClicked.connect(
            lambda it: self.play_index(it.row()))
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        rl.addWidget(self.table, 1)

        rl.addWidget(self._build_player_bar())
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        return page

    def _build_player_bar(self):
        bar = QFrame()
        bar.setStyleSheet(
            'QFrame { background:#1c1e24; border:1px solid #2e313a;'
            ' border-radius:8px; }')
        v = QVBoxLayout(bar)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(6)

        seek = QHBoxLayout()
        self.pos_lbl = QLabel('0:00')
        self.pos_lbl.setObjectName('time')
        self.dur_lbl = QLabel('0:00')
        self.dur_lbl.setObjectName('time')
        self.seek = SeekSlider(Qt.Horizontal)
        self.seek.sliderPressed.connect(
            lambda: setattr(self, '_seeking', True))
        self.seek.sliderReleased.connect(self._seek_released)
        self.seek.seeked.connect(self._seek_clicked)
        seek.addWidget(self.pos_lbl)
        seek.addWidget(self.seek, 1)
        seek.addWidget(self.dur_lbl)
        v.addLayout(seek)

        ctl = QHBoxLayout()
        self.shuffle_btn = self._mk_btn(
            QStyle.SP_BrowserReload,
            'Shuffle — play the playlist in random order', checkable=True)
        self.shuffle_btn.setIcon(shuffle_icon())
        self.shuffle_btn.toggled.connect(self._set_shuffle)
        self.prev_btn = self._mk_btn(QStyle.SP_MediaSkipBackward,
                                     'Previous', self.prev)
        self.play_btn = self._mk_btn(QStyle.SP_MediaPlay,
                                     'Play / Pause', self.toggle_play)
        self.stop_btn = self._mk_btn(QStyle.SP_MediaStop, 'Stop', self.stop)
        self.next_btn = self._mk_btn(QStyle.SP_MediaSkipForward,
                                     'Next', self.next)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setFixedWidth(110)
        self.vol.valueChanged.connect(self._apply_volume)
        self.vol.setToolTip('Volume')
        self.vol_lbl = QLabel('80')
        self.vol_lbl.setObjectName('time')
        ctl.addWidget(self.shuffle_btn)
        ctl.addStretch(1)
        ctl.addWidget(self.prev_btn)
        ctl.addWidget(self.play_btn)
        ctl.addWidget(self.stop_btn)
        ctl.addWidget(self.next_btn)
        ctl.addStretch(1)
        vol_icon = QLabel()
        vol_icon.setPixmap(self.style().standardIcon(
            QStyle.SP_MediaVolume).pixmap(18, 18))
        ctl.addWidget(vol_icon)
        ctl.addWidget(self.vol)
        ctl.addWidget(self.vol_lbl)
        v.addLayout(ctl)

        np = QHBoxLayout()
        self.art_thumb = QLabel()
        self.art_thumb.setObjectName('artThumb')
        self.art_thumb.setFixedSize(76, 76)
        self.art_thumb.setAlignment(Qt.AlignCenter)
        self.art_thumb.setToolTip('Click for full-screen now playing')
        self.art_thumb.mousePressEvent = lambda e: self.enter_fullscreen()
        np.addWidget(self.art_thumb)
        col = QVBoxLayout()
        self.np_title = QLabel('Nothing playing')
        self.np_title.setObjectName('npTitle')
        self.np_sub = QLabel('')
        self.np_sub.setObjectName('npSub')
        self.np_tags = QLabel('')
        self.np_tags.setObjectName('npSub')
        for w in (self.np_title, self.np_sub, self.np_tags):
            col.addWidget(w)
        col.addStretch(1)
        np.addLayout(col, 1)
        v.addLayout(np)
        return bar

    def _build_fullscreen_page(self):
        page = QWidget()
        page.setStyleSheet('background:#0c0d10;')
        v = QVBoxLayout(page)
        v.setContentsMargins(60, 30, 60, 30)
        v.setSpacing(14)

        top = QHBoxLayout()
        self.fs_status = QLabel('NOW PLAYING')
        self.fs_status.setStyleSheet('color:#8b90a0; letter-spacing:3px;')
        top.addWidget(self.fs_status)
        top.addStretch(1)
        exit_btn = QPushButton('Exit full screen   Esc')
        exit_btn.clicked.connect(self.exit_fullscreen)
        top.addWidget(exit_btn)
        v.addLayout(top)

        self.fs_art = QLabel()
        self.fs_art.setObjectName('artBig')
        self.fs_art.setAlignment(Qt.AlignCenter)
        # Ignored policy: a big pixmap must never inflate the window's
        # size hint or it can't shrink back after fullscreen.
        self.fs_art.setSizePolicy(QSizePolicy.Ignored,
                                  QSizePolicy.Ignored)
        self.fs_art.setMinimumSize(0, 0)
        v.addWidget(self.fs_art, 1)

        self.fs_title = QLabel('Nothing playing')
        self.fs_title.setObjectName('bigTitle')
        self.fs_title.setAlignment(Qt.AlignCenter)
        self.fs_sub = QLabel('')
        self.fs_sub.setObjectName('bigSub')
        self.fs_sub.setAlignment(Qt.AlignCenter)
        self.fs_tags = QLabel('')
        self.fs_tags.setObjectName('bigTags')
        self.fs_tags.setAlignment(Qt.AlignCenter)
        v.addWidget(self.fs_title)
        v.addWidget(self.fs_sub)
        v.addWidget(self.fs_tags)

        seek = QHBoxLayout()
        self.fs_pos = QLabel('0:00')
        self.fs_pos.setObjectName('time')
        self.fs_dur = QLabel('0:00')
        self.fs_dur.setObjectName('time')
        self.fs_seek = SeekSlider(Qt.Horizontal)
        self.fs_seek.sliderPressed.connect(
            lambda: setattr(self, '_seeking', True))
        self.fs_seek.sliderReleased.connect(self._seek_released)
        self.fs_seek.seeked.connect(self._seek_clicked)
        seek.addWidget(self.fs_pos)
        seek.addWidget(self.fs_seek, 1)
        seek.addWidget(self.fs_dur)
        v.addLayout(seek)

        ctl = QHBoxLayout()
        ctl.addStretch(1)
        self.fs_shuffle = self._mk_btn(
            QStyle.SP_BrowserReload,
            'Shuffle — play the playlist in random order', checkable=True)
        self.fs_shuffle.setIcon(shuffle_icon())
        self.fs_shuffle.toggled.connect(self._set_shuffle)
        self.fs_shuffle.setMinimumSize(56, 56)
        self.fs_shuffle.setIconSize(QSize(30, 30))
        ctl.addWidget(self.fs_shuffle)
        self.fs_prev = self._mk_btn(QStyle.SP_MediaSkipBackward,
                                    'Previous', self.prev)
        self.fs_play = self._mk_btn(QStyle.SP_MediaPlay,
                                    'Play / Pause', self.toggle_play)
        self.fs_stop = self._mk_btn(QStyle.SP_MediaStop, 'Stop', self.stop)
        self.fs_next = self._mk_btn(QStyle.SP_MediaSkipForward,
                                    'Next', self.next)
        for b in (self.fs_prev, self.fs_play, self.fs_stop, self.fs_next):
            b.setIconSize(QSize(30, 30))
            b.setMinimumSize(56, 56)
            ctl.addWidget(b)
        ctl.addStretch(1)
        v.addLayout(ctl)
        return page

    # ------------------------------------------------------------- player
    def _wire_player(self):
        self.player = QMediaPlayer(self)
        self.player.setNotifyInterval(500)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.stateChanged.connect(self._on_state)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.error.connect(self._on_error)

    def _on_position(self, ms):
        if not self._seeking:
            for s in (self.seek, self.fs_seek):
                s.blockSignals(True)
                s.setValue(ms)
                s.blockSignals(False)
        self.pos_lbl.setText(fmt_time(ms))
        self.fs_pos.setText(fmt_time(ms))

    def _on_duration(self, ms):
        for s in (self.seek, self.fs_seek):
            s.setRange(0, ms)
        self.dur_lbl.setText(fmt_time(ms))
        self.fs_dur.setText(fmt_time(ms))

    def _on_state(self, st):
        if st == QMediaPlayer.PlayingState:
            self._err_streak = 0
        icon = QStyle.SP_MediaPause if st == QMediaPlayer.PlayingState \
            else QStyle.SP_MediaPlay
        for b in (self.play_btn, self.fs_play):
            b.setIcon(self.style().standardIcon(icon))

    def _on_media_status(self, st):
        if st == QMediaPlayer.EndOfMedia:
            self.next(auto=True)

    def _check_service(self):
        """Warn once if Qt has no multimedia backend (missing plugins pkg)."""
        if self.player.availability() == QMultimedia.ServiceMissing:
            QMessageBox.warning(
                self, APP + ' — audio backend missing',
                'Qt could not find a media player service '
                '("org.qt-project.qt.mediaplayer"), so nothing can play.\n\n'
                'Fix it with:\n\n'
                '  sudo apt install libqt5multimedia5-plugins '
                'gstreamer1.0-plugins-good gstreamer1.0-plugins-ugly '
                'gstreamer1.0-libav\n\n'
                'then restart GNUkeBox.')
            self.statusBar().showMessage(
                'Audio backend missing — install '
                'libqt5multimedia5-plugins (see README)')

    def _on_error(self, err):
        if err == QMediaPlayer.NoError:
            return
        msg = self.player.errorString() or 'playback error'
        if err == QMediaPlayer.ServiceMissingError:
            self.statusBar().showMessage('Audio backend missing: ' + msg)
            self._check_service()
            return
        self._err_streak += 1
        self.statusBar().showMessage('Playback error: %s' % msg)
        if self._err_streak >= 8:
            self.statusBar().showMessage(
                'Too many playback errors — stopped')
            self.stop()
            return
        QTimer.singleShot(400, lambda: self.next(auto=True))

    def _apply_volume(self, v):
        self.player.setVolume(v)
        self.vol.setValue(v)
        self.vol_lbl.setText(str(v))

    def _seek_released(self):
        self._seeking = False
        s = self.sender()
        self.player.setPosition(s.value())

    def _seek_clicked(self, v):
        self._seeking = False
        self.player.setPosition(v)

    # --------------------------------------------------------- playback
    def play_index(self, i):
        if not (0 <= i < len(self.queue)):
            return
        if self.idx >= 0 and self.idx != i:
            self.history.append(self.idx)
            self.history = self.history[-100:]
        self.idx = i
        self._shuffle_played.add(i)
        d = self.queue[i]
        path = d['path']
        if not os.path.exists(path):
            self.statusBar().showMessage('Missing file: ' + path)
            self.next()
            return
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        self.player.play()
        self._set_now_playing(d)
        self._highlight_row(i)
        self._scroll_to_row(i)

    def toggle_play(self):
        st = self.player.state()
        if st == QMediaPlayer.PlayingState:
            self.player.pause()
        elif st == QMediaPlayer.PausedState:
            self.player.play()
        elif self.idx >= 0:
            self.play_index(self.idx)
        elif self.queue:
            self.play_index(0)

    def stop(self):
        self.player.stop()

    def next(self, auto=False):
        if not self.queue:
            return
        if self.shuffle_btn.isChecked():
            pool = [i for i in range(len(self.queue))
                    if i not in self._shuffle_played]
            if not pool:
                self._extend_queue()
                pool = [i for i in range(len(self.queue))
                        if i not in self._shuffle_played]
            if not pool:  # whole queue played — start a fresh pass
                self._shuffle_played = {self.idx}
                pool = [i for i in range(len(self.queue))
                        if i != self.idx]
            if pool:
                self.play_index(random.choice(pool))
            return
        nxt = self.idx + 1
        if nxt >= len(self.queue):
            self._extend_queue()
            nxt = self.idx + 1
        if nxt < len(self.queue):
            self.play_index(nxt)
        elif auto:
            self.statusBar().showMessage(
                'End of playlist — nothing similar found')

    def prev(self):
        if self.player.position() > 4000:
            self.player.setPosition(0)
            return
        if self.shuffle_btn.isChecked() and self.history:
            prev_i = self.history.pop()
            self.idx = -1  # don't push history back
            self.play_index(prev_i)
            return
        self.play_index(max(0, self.idx - 1))

    def _extend_queue(self):
        """Append 'similar' tracks so playback never dead-ends."""
        artists, genres = [], []
        for d in self.queue:
            for coll, key in ((artists, 'artist'), (genres, 'genre')):
                v = d[key]
                if v and v not in coll:
                    coll.append(v)
        rows = self.lib.similar(artists[:40], genres[:20],
                                self.queue_set, limit=80)
        if not rows:
            return
        for r in rows:
            self.queue.append(dict(r))
            self.queue_set.add(r['path'])
        self._append_rows(rows)
        self.results_lbl.setText('Playlist — %d tracks (auto-extended)'
                                 % len(self.queue))

    # ------------------------------------------------------ now playing
    def _art_for(self, path):
        if path in self._art_cache:
            return self._art_cache[path]
        pm = None
        res = extract_art(path)
        if res:
            pm = QPixmap()
            if not pm.loadFromData(res[0]):
                pm = None
        if pm is None:
            pm = self._ph
        self._art_cache[path] = pm
        if len(self._art_cache) > 400:
            self._art_cache.clear()
            self._art_cache[path] = pm
        return pm

    def _set_now_playing(self, d):
        path = d['path']
        title = d['title'] or os.path.basename(path)
        artist = d['artist'] or 'Unknown artist'
        album = d['album'] or 'Unknown album'
        line2 = '%s — %s%s' % (artist, album,
                               ' (%s)' % d['year'] if d['year'] else '')
        bits = [b for b in
                (('Genre: ' + d['genre']) if d['genre'] else '',
                 ('Track %s' % d['track']) if d['track'] else '',
                 os.path.basename(path))
                if b]
        self.np_title.setText(title)
        self.np_sub.setText(line2)
        self.np_tags.setText('   ·   '.join(bits))
        self.fs_title.setText(title)
        self.fs_sub.setText(line2)
        self.fs_tags.setText('   ·   '.join(bits))
        pm = self._art_for(path)
        self.art_thumb.setPixmap(pm.scaled(
            76, 76, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._fs_art_scale()
        self.setWindowTitle('%s — %s · %s' % (title, artist, APP))

    def _fs_art_scale(self):
        if self.idx < 0 or self.idx >= len(self.queue):
            return
        pm = self._art_for(self.queue[self.idx]['path'])
        self.fs_art.setPixmap(pm.scaled(
            self.fs_art.size(), Qt.KeepAspectRatio,
            Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.stack.currentIndex() == 1:
            self._fs_art_scale()

    def _highlight_row(self, row):
        f = QFont()
        for r in range(self.table.rowCount()):
            f.setBold(r == row)
            for c in range(self.table.columnCount()):
                it = self.table.item(r, c)
                if it:
                    it.setFont(f)
                    it.setForeground(QColor('#e95420') if r == row
                                     else QColor('#dddde2'))

    def _scroll_to_row(self, row):
        it = self.table.item(row, 0)
        if it:
            self.table.scrollToItem(it, QAbstractItemView.PositionAtCenter)

    # ------------------------------------------------------------- scan
    def _load_folder_list(self):
        self.folder_list.clear()
        self.folder_list.addItems(self.cfg.get('folders', []))

    def _save_folders(self):
        self.cfg['folders'] = [self.folder_list.item(i).text()
                               for i in range(self.folder_list.count())]
        save_config(self.cfg)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(
            self, 'Choose a music folder', os.path.expanduser('~/Music'))
        if not d:
            return
        if self.folder_list.findItems(d, Qt.MatchExactly):
            return
        self.folder_list.addItem(d)
        self._save_folders()
        self.start_scan()

    def remove_folder(self):
        for it in self.folder_list.selectedItems():
            self.folder_list.takeItem(self.folder_list.row(it))
        self._save_folders()

    def start_scan(self):
        if self.scanner and self.scanner.isRunning():
            self.scanner.cancel()
            self.scanner.wait(2000)
        folders = [self.folder_list.item(i).text()
                   for i in range(self.folder_list.count())]
        if not folders:
            return
        self.scan_lbl.setText('Scanning…')
        self.scanner = Scanner(self.lib, folders, self)
        self.scanner.progress.connect(
            lambda n, p: self.scan_lbl.setText('Scanning… %d new — %s'
                                             % (n, os.path.basename(p))))
        self.scanner.done.connect(self._scan_done)
        self.scanner.start()

    def _scan_done(self, n, cancelled):
        self.scan_lbl.setText('%d tracks indexed (%d new)'
                              % (self.lib.count(), n))
        self.statusBar().showMessage('%d tracks in library'
                                     % self.lib.count())
        self._refresh_completers()

    def _refresh_completers(self):
        for key in ('artist', 'album', 'genre'):
            e = self.edits.get(key)
            if not e:
                continue
            c = QCompleter(self)
            m = QStringListModel(self.lib.distinct(key))
            c.setModel(m)
            c.setCaseSensitivity(Qt.CaseInsensitive)
            c.setFilterMode(Qt.MatchContains)
            e.setCompleter(c)

    # ----------------------------------------------------------- search
    def run_search(self):
        filters = {k: e.text().strip() for k, e in self.edits.items()}
        filters = {k: v for k, v in filters.items() if v}
        any_text = self.any_edit.text().strip()
        if not filters and not any_text:
            rows = self.lib.search({}, limit=5000)
        else:
            rows = self.lib.search(filters, any_text)
        self._last_filters = filters
        self.queue = [dict(r) for r in rows]
        self.queue_set = {r['path'] for r in rows}
        self.idx = -1
        self.history.clear()
        self._shuffle_played.clear()
        self.table.setRowCount(0)
        self._append_rows(rows)
        self.results_lbl.setText(
            'Playlist — %d track%s' % (len(rows), 's' if len(rows) != 1
                                       else ''))
        if not rows:
            self.statusBar().showMessage('No matches')
        elif self.autoplay_chk.isChecked():
            self.play_index(0)

    def _append_rows(self, rows):
        self.table.setSortingEnabled(False)
        base = self.table.rowCount()
        self.table.setRowCount(base + len(rows))
        for i, r in enumerate(rows):
            vals = (r['title'] or os.path.basename(r['path']),
                    r['artist'], r['album'], r['genre'],
                    fmt_time((r['duration'] or 0) * 1000))
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setData(Qt.UserRole, r['path'])
                self.table.setItem(base + i, c, it)

    def clear_search(self):
        self.any_edit.clear()
        for e in self.edits.values():
            e.clear()

    def _table_menu(self, pos):
        m = QMenu(self)
        row = self.table.rowAt(pos.y())
        if row >= 0:
            m.addAction('Play', lambda: self.play_index(row))
            m.addAction('Play next', lambda r=row:
                        self._queue_next(r))
        sel = sorted({i.row() for i in self.table.selectedIndexes()})
        if sel:
            m.addAction('Remove %d from playlist' % len(sel),
                        lambda: self._remove_rows(sel))
        m.addAction('Clear playlist', self._clear_playlist)
        m.exec_(self.table.viewport().mapToGlobal(pos))

    def _queue_next(self, row):
        if not (0 <= row < len(self.queue)) or row == self.idx:
            return
        d = self.queue.pop(row)
        if row < self.idx:
            self.idx -= 1
        self.queue.insert(self.idx + 1, d)
        self._rebuild_table()

    def _remove_rows(self, rows):
        for r in reversed(rows):
            if 0 <= r < len(self.queue):
                self.queue_set.discard(self.queue[r]['path'])
                del self.queue[r]
                self.table.removeRow(r)
                if r < self.idx:
                    self.idx -= 1
                elif r == self.idx:
                    self.idx -= 1
                    self.next()
        self.results_lbl.setText('Playlist — %d tracks' % len(self.queue))

    def _clear_playlist(self):
        self.stop()
        self.queue, self.queue_set = [], set()
        self._shuffle_played.clear()
        self.idx = -1
        self.table.setRowCount(0)
        self.results_lbl.setText('Playlist')
        self.np_title.setText('Nothing playing')
        self.np_sub.setText('')
        self.np_tags.setText('')

    def _rebuild_table(self):
        self.table.setRowCount(0)
        self._append_rows(self.queue)
        if self.idx >= 0:
            self._highlight_row(self.idx)

    # ------------------------------------------------------- fullscreen
    def enter_fullscreen(self):
        if self._in_fs:
            return
        self._in_fs = True
        self._fs_guard = True
        # remember the pre-fullscreen (windowed) geometry to restore to
        self._pre_fs_geom = self.normalGeometry()
        self.stack.setCurrentIndex(1)
        self._fs_art_scale()
        self.showFullScreen()
        QTimer.singleShot(400, lambda: setattr(self, '_fs_guard', False))

    def exit_fullscreen(self):
        if not self._in_fs:
            return
        self._in_fs = False
        self._fs_guard = True
        self.stack.setCurrentIndex(0)
        self.showNormal()
        g = getattr(self, '_pre_fs_geom', None)
        if g is not None and g.isValid():
            self.setGeometry(g)
        QTimer.singleShot(400, lambda: setattr(self, '_fs_guard', False))

    def changeEvent(self, e):
        if e.type() == QEvent.WindowStateChange and not self._fs_guard:
            if (self.windowState() & Qt.WindowMaximized) and \
                    not self._in_fs:
                self.enter_fullscreen()
        super().changeEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_F11:
            if self._in_fs:
                self.exit_fullscreen()
            else:
                self.enter_fullscreen()
        elif e.key() == Qt.Key_Escape and self._in_fs:
            self.exit_fullscreen()
        elif e.matches(QKeySequence.Find) or \
                (e.modifiers() == Qt.ControlModifier
                 and e.key() == Qt.Key_Slash):
            if self._in_fs:
                self.exit_fullscreen()
            self.any_edit.setFocus()
            self.any_edit.selectAll()
        else:
            super().keyPressEvent(e)

    def _set_shuffle(self, on):
        """Keep the browser + fullscreen shuffle buttons in sync."""
        for b in (self.shuffle_btn, self.fs_shuffle):
            if b.isChecked() != on:
                b.blockSignals(True)
                b.setChecked(on)
                b.blockSignals(False)
        self.history.clear()
        self._shuffle_played = {self.idx} if self.idx >= 0 else set()

    def closeEvent(self, e):
        if self.scanner and self.scanner.isRunning():
            self.scanner.cancel()
            self.scanner.wait(3000)
        self.cfg['volume'] = self.vol.value()
        self.cfg['shuffle'] = self.shuffle_btn.isChecked()
        g = self.normalGeometry()
        self.cfg['w'], self.cfg['h'] = g.width(), g.height()
        save_config(self.cfg)
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
