#!/usr/bin/env python3
"""
Deezload TUI — a terminal user interface for deezload.py
Browse Deezer artists, albums, playlists, and download tracks.

Usage:
    python deezload_tui.py
    python deezload_tui.py --arl <YOUR_ARL_TOKEN>
"""

from __future__ import annotations

import argparse
import threading
from pathlib import Path
from typing import Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Log,
    ProgressBar,
    Static,
    TabbedContent,
    TabPane,
)
from textual.css.query import NoMatches

# ── Import deezload components ───────────────────────────────────────────────
import sys, os
sys.path.insert(0, str(Path(__file__).parent))

from deezload import (
    AudioQuality,
    DeezerDownloader,
    load_config,
    save_config,
    resolve_deezer_url,
    extract_id_and_type,
    sanitise_filename,
)

# ── CSS ───────────────────────────────────────────────────────────────────────
CSS = """
Screen {
    background: $surface;
}

/* ── Sidebar ── */
#sidebar {
    width: 28;
    border-right: solid $primary-darken-2;
    background: $surface-darken-1;
}

#sidebar-title {
    background: $primary;
    color: $text;
    text-align: center;
    padding: 1 0;
    text-style: bold;
}

#nav-list {
    height: 1fr;
}

ListItem {
    padding: 0 2;
}

ListItem.--highlight {
    background: $primary-darken-1;
}

/* ── Main area ── */
#main {
    width: 1fr;
}

/* ── Search bar ── */
#search-bar {
    height: 3;
    border-bottom: solid $primary-darken-2;
    padding: 0 1;
    align: left middle;
}

#search-input {
    width: 1fr;
}

#search-btn {
    margin-left: 1;
    min-width: 12;
}

/* ── Content panels ── */
#content {
    height: 1fr;
}

DataTable {
    height: 1fr;
}

/* ── Download panel ── */
#download-panel {
    height: 12;
    border-top: solid $primary-darken-2;
    background: $surface-darken-1;
    padding: 0 1;
}

#download-title {
    text-style: bold;
    color: $primary;
    padding: 1 0 0 0;
}

#dl-progress {
    margin: 1 0;
}

#dl-status {
    color: $text-muted;
    height: 3;
    overflow: hidden;
}

/* ── Auth modal ── */
AuthModal {
    align: center middle;
}

#auth-dialog {
    background: $surface;
    border: solid $primary;
    padding: 2 4;
    width: 60;
    height: auto;
}

#auth-dialog Label {
    margin-bottom: 1;
}

#auth-dialog Input {
    margin-bottom: 1;
}

#auth-buttons {
    align: right middle;
    margin-top: 1;
}

/* ── Detail modal ── */
DetailModal {
    align: center middle;
}

#detail-dialog {
    background: $surface;
    border: solid $primary;
    padding: 2 3;
    width: 80;
    height: 30;
}

#detail-table {
    height: 20;
}

#detail-buttons {
    align: right middle;
    margin-top: 1;
}

/* ── Config modal ── */
ConfigModal {
    align: center middle;
}

#config-dialog {
    background: $surface;
    border: solid $primary;
    padding: 2 4;
    width: 64;
    height: auto;
}

#config-dialog Label {
    margin-bottom: 1;
}

#config-dialog Input {
    margin-bottom: 1;
}

#quality-row {
    height: 3;
    margin-bottom: 1;
    align: left middle;
}

#config-buttons {
    align: right middle;
    margin-top: 1;
}

.section-label {
    color: $text-muted;
    text-style: italic;
    padding: 1 2 0 2;
}
"""

# ═══════════════════════════════════════════════════════════════════════════════
# Modal: Authentication
# ═══════════════════════════════════════════════════════════════════════════════

class AuthModal(ModalScreen):
    """Prompt the user for their ARL token."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, arl: str = ""):
        super().__init__()
        self._current_arl = arl

    def compose(self) -> ComposeResult:
        with Container(id="auth-dialog"):
            yield Label("🔑  Deezer Authentication", id="auth-heading")
            yield Label("Paste your ARL token below.\n(Find it in browser cookies: deezer.com → arl)")
            yield Input(
                value=self._current_arl,
                placeholder="ARL token (long hex string)…",
                password=True,
                id="arl-input",
            )
            with Horizontal(id="auth-buttons"):
                yield Button("Cancel", variant="default", id="auth-cancel")
                yield Button("Connect", variant="primary", id="auth-ok")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "auth-ok":
            arl = self.query_one("#arl-input", Input).value.strip()
            self.dismiss(arl if arl else None)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        arl = event.value.strip()
        self.dismiss(arl if arl else None)


# ═══════════════════════════════════════════════════════════════════════════════
# Modal: Config / Settings
# ═══════════════════════════════════════════════════════════════════════════════

class ConfigModal(ModalScreen):
    """Settings: quality + output dir."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, quality: str = "FLAC", output: str = "downloads"):
        super().__init__()
        self._quality = quality
        self._output = output

    def compose(self) -> ComposeResult:
        with Container(id="config-dialog"):
            yield Label("⚙  Settings")
            yield Label("Output directory")
            yield Input(value=self._output, placeholder="downloads", id="cfg-output")
            yield Label("Audio quality")
            with Horizontal(id="quality-row"):
                yield Button("MP3 128", id="q-128",
                             variant="primary" if self._quality == "MP3_128" else "default")
                yield Button("MP3 320", id="q-320",
                             variant="primary" if self._quality == "MP3_320" else "default")
                yield Button("FLAC",    id="q-flac",
                             variant="primary" if self._quality == "FLAC" else "default")
            with Horizontal(id="config-buttons"):
                yield Button("Cancel", variant="default", id="cfg-cancel")
                yield Button("Save",   variant="primary",  id="cfg-save")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id in ("q-128", "q-320", "q-flac"):
            # Update quality selection highlight
            for b_id in ("q-128", "q-320", "q-flac"):
                self.query_one(f"#{b_id}", Button).variant = "default"
            event.button.variant = "primary"
            self._quality = {"q-128": "MP3_128", "q-320": "MP3_320", "q-flac": "FLAC"}[btn_id]
        elif btn_id == "cfg-save":
            output = self.query_one("#cfg-output", Input).value.strip() or "downloads"
            self.dismiss({"quality": self._quality, "output": output})
        else:
            self.dismiss(None)


# ═══════════════════════════════════════════════════════════════════════════════
# Modal: Album / Playlist track list
# ═══════════════════════════════════════════════════════════════════════════════

class DetailModal(ModalScreen):
    """Show tracks in an album or playlist and let the user download the whole thing."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, title: str, tracks: list, content_type: str, content_id: str):
        super().__init__()
        self._title       = title
        self._tracks      = tracks
        self._ctype       = content_type  # 'album' | 'playlist'
        self._content_id  = content_id

    def compose(self) -> ComposeResult:
        with Container(id="detail-dialog"):
            yield Label(f"📋  {self._title}")
            t = DataTable(id="detail-table")
            t.add_columns("#", "Title", "Artist", "Duration")
            for i, tr in enumerate(self._tracks, 1):
                dur_s = int(tr.get("duration", 0))
                dur = f"{dur_s // 60}:{dur_s % 60:02d}" if dur_s else "—"
                artist = tr.get("artist", {}).get("name", "") if isinstance(tr.get("artist"), dict) else ""
                t.add_row(str(i), tr.get("title", "?"), artist, dur)
            yield t
            with Horizontal(id="detail-buttons"):
                yield Button("Close",          variant="default", id="det-close")
                yield Button(f"⬇ Download all", variant="primary", id="det-download")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "det-download":
            self.dismiss({"action": "download", "type": self._ctype, "id": self._content_id})
        else:
            self.dismiss(None)


# ═══════════════════════════════════════════════════════════════════════════════
# Main App
# ═══════════════════════════════════════════════════════════════════════════════

NAV_ITEMS = [
    ("🔍", "Search"),
    ("💿", "Albums"),
    ("🎵", "Playlists"),
    ("👤", "Artists"),
    ("⬇", "Downloads"),
]

class DeezloadTUI(App):
    """Deezload TUI — browse and download music from Deezer."""

    CSS = CSS
    TITLE = "Deezload"
    SUB_TITLE = "Deezer music browser"

    BINDINGS = [
        Binding("ctrl+q",  "quit",         "Quit"),
        Binding("ctrl+a",  "auth",         "Auth"),
        Binding("ctrl+s",  "settings",     "Settings"),
        Binding("ctrl+d",  "download_sel", "Download"),
        Binding("f5",      "refresh",      "Refresh"),
        Binding("escape",  "go_home",      "Home"),
    ]

    # Reactive state
    status_text: reactive[str] = reactive("Not authenticated — press Ctrl+A to connect")
    arl:         reactive[str] = reactive("")
    quality:     reactive[str] = reactive("FLAC")
    output_dir:  reactive[str] = reactive("downloads")

    def __init__(self, initial_arl: str = ""):
        super().__init__()
        self._downloader: Optional[DeezerDownloader] = None
        self._authenticated = False
        self._nav_index = 0
        self._dl_lock = threading.Lock()
        self._current_results: list = []   # raw API results shown in table
        self._current_type = "search"      # 'search' | 'album' | 'playlist' | 'artist'
        self.arl = initial_arl

        # Load saved config
        cfg = load_config()
        if cfg.get("arl_token") and not initial_arl:
            self.arl = cfg["arl_token"]
        if cfg.get("quality"):
            self.quality = cfg["quality"]
        if cfg.get("output"):
            self.output_dir = cfg["output"]

    # ── Layout ─────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            # Sidebar navigation
            with Vertical(id="sidebar"):
                yield Static("🎵 Deezload", id="sidebar-title")
                with ListView(id="nav-list"):
                    for icon, label in NAV_ITEMS:
                        yield ListItem(Label(f"{icon}  {label}"), id=f"nav-{label.lower()}")
                yield Static("", id="auth-badge")

            # Main content
            with Vertical(id="main"):
                # Search bar
                with Horizontal(id="search-bar"):
                    yield Input(
                        placeholder="Search artists, albums, tracks… or paste a Deezer URL",
                        id="search-input",
                    )
                    yield Button("Search", variant="primary", id="search-btn")

                # Results table
                with Container(id="content"):
                    t = DataTable(id="results-table")
                    t.cursor_type = "row"
                    t.add_columns("Type", "Title", "Artist / Info", "Extra")
                    yield t

                # Download panel
                with Vertical(id="download-panel"):
                    yield Static("⬇  Downloads", id="download-title")
                    yield ProgressBar(total=100, show_eta=False, id="dl-progress")
                    yield Log(id="dl-status", max_lines=6)

        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#dl-progress", ProgressBar).update(progress=0)
        if self.arl:
            self._connect()

    # ── Auth & connection ──────────────────────────────────────────────────────

    def action_auth(self) -> None:
        self.push_screen(AuthModal(self.arl), self._on_auth_result)

    def _on_auth_result(self, arl: Optional[str]) -> None:
        if arl:
            self.arl = arl
            self._connect()

    @work(thread=True)
    def _connect(self) -> None:
        self._set_status("Connecting to Deezer…")
        try:
            dl = DeezerDownloader(self.arl, AudioQuality(self.quality))
            ok = dl.authenticate()
            if ok:
                self._downloader = dl
                self._authenticated = True
                user = dl.client.current_user.get("name", "?")
                self.call_from_thread(self._set_status, f"✓ Authenticated as {user}")
                self.call_from_thread(self._update_auth_badge, f"👤 {user}")
            else:
                self.call_from_thread(self._set_status, "✗ Auth failed — check ARL token")
        except Exception as e:
            self.call_from_thread(self._set_status, f"✗ Error: {e}")

    def _update_auth_badge(self, text: str) -> None:
        try:
            self.query_one("#auth-badge", Static).update(text)
        except NoMatches:
            pass

    def _set_status(self, msg: str) -> None:
        self.sub_title = msg

    # ── Settings ───────────────────────────────────────────────────────────────

    def action_settings(self) -> None:
        self.push_screen(
            ConfigModal(self.quality, self.output_dir),
            self._on_config_result,
        )

    def _on_config_result(self, result: Optional[dict]) -> None:
        if result:
            self.quality    = result["quality"]
            self.output_dir = result["output"]
            if self._authenticated:
                # Re-create downloader with new quality
                self._downloader = DeezerDownloader(
                    self.arl, AudioQuality(self.quality)
                )
                self._downloader.authenticate()
            # Persist
            if self.arl:
                save_config(self.arl, self.quality, self.output_dir)
            self._set_status(f"Settings saved — quality: {self.quality}, output: {self.output_dir}")

    # ── Navigation ─────────────────────────────────────────────────────────────

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        nav_map = {
            "nav-search":    self._show_search_hint,
            "nav-albums":    self._browse_albums,
            "nav-playlists": self._browse_playlists,
            "nav-artists":   self._browse_artists,
            "nav-downloads": self._show_download_log,
        }
        fn = nav_map.get(item_id)
        if fn:
            fn()

    def _show_search_hint(self) -> None:
        self.query_one("#search-input", Input).focus()

    def action_go_home(self) -> None:
        self._show_search_hint()

    # ── Search ─────────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "search-btn":
            self._do_search()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            self._do_search()

    def _do_search(self) -> None:
        query = self.query_one("#search-input", Input).value.strip()
        if not query:
            return
        if not self._authenticated:
            self._set_status("Not connected — press Ctrl+A to authenticate first")
            return

        # URL pasted?
        if "deezer.com" in query or "deezer.page.link" in query:
            self._handle_url(query)
            return

        self._search_deezer(query)

    @work(thread=True)
    def _handle_url(self, url: str) -> None:
        self.call_from_thread(self._set_status, f"Resolving URL…")
        try:
            resolved = resolve_deezer_url(url)
            content_id, url_type = extract_id_and_type(resolved)
            if not content_id:
                self.call_from_thread(self._set_status, "✗ Could not parse Deezer URL")
                return
            if url_type == "track":
                self.call_from_thread(self._set_status, f"Track {content_id} — press Ctrl+D to download")
                self.call_from_thread(self._show_track_url, content_id)
            elif url_type == "album":
                self.call_from_thread(self._open_album, content_id)
            elif url_type == "playlist":
                self.call_from_thread(self._open_playlist, content_id)
            elif url_type == "artist":
                self.call_from_thread(self._open_artist, content_id)
        except Exception as e:
            self.call_from_thread(self._set_status, f"✗ URL error: {e}")

    def _show_track_url(self, track_id: str) -> None:
        """Show a single track in the results table."""
        info = self._downloader.get_track_info(track_id)
        if not info:
            self._set_status("✗ Could not fetch track info")
            return
        title  = info.get("SNG_TITLE") or info.get("title", "?")
        artist = info.get("ART_NAME") or ""
        dur_s  = int(info.get("DURATION") or info.get("duration", 0))
        dur    = f"{dur_s // 60}:{dur_s % 60:02d}" if dur_s else "—"
        self._current_results = [{"_type": "track", "_id": track_id, **info}]
        self._current_type = "track"
        table = self.query_one("#results-table", DataTable)
        table.clear()
        table.add_row("🎵 Track", title, artist, dur, key=track_id)

    @work(thread=True)
    def _search_deezer(self, query: str) -> None:
        self.call_from_thread(self._set_status, f"Searching for '{query}'…")
        try:
            sess = self._downloader.session
            resp = sess.get(f"https://api.deezer.com/2.0/search?q={query}&limit=50")
            resp.raise_for_status()
            data = resp.json().get("data", [])
            self.call_from_thread(self._populate_search, data)
        except Exception as e:
            self.call_from_thread(self._set_status, f"✗ Search error: {e}")

    def _populate_search(self, data: list) -> None:
        self._current_results = data
        self._current_type = "search"
        table = self.query_one("#results-table", DataTable)
        table.clear()
        for item in data:
            itype = item.get("type", "track")
            if itype == "track":
                icon = "🎵"
                title  = item.get("title", "?")
                artist = item.get("artist", {}).get("name", "") if isinstance(item.get("artist"), dict) else ""
                dur_s  = int(item.get("duration", 0))
                extra  = f"{dur_s // 60}:{dur_s % 60:02d}"
            elif itype == "album":
                icon = "💿"
                title  = item.get("title", "?")
                artist = item.get("artist", {}).get("name", "") if isinstance(item.get("artist"), dict) else ""
                extra  = str(item.get("nb_tracks", ""))
            elif itype == "artist":
                icon = "👤"
                title  = item.get("name", "?")
                artist = ""
                extra  = ""
            elif itype == "playlist":
                icon = "🎶"
                title  = item.get("title", "?")
                artist = item.get("user", {}).get("name", "") if isinstance(item.get("user"), dict) else ""
                extra  = str(item.get("nb_tracks", ""))
            else:
                icon = "?"
                title = str(item.get("title") or item.get("name", "?"))
                artist = ""
                extra = ""
            table.add_row(f"{icon} {itype.title()}", title, artist, extra,
                          key=str(item.get("id", "")))
        self._set_status(f"Found {len(data)} results for '{self.query_one('#search-input', Input).value}'")

    # ── Browse panels ──────────────────────────────────────────────────────────

    @work(thread=True)
    def _browse_playlists(self) -> None:
        if not self._authenticated:
            self.call_from_thread(self._set_status, "Not authenticated")
            return
        self.call_from_thread(self._set_status, "Loading your playlists…")
        try:
            sess = self._downloader.session
            user_id = self._downloader.user_id
            resp = sess.get(f"https://api.deezer.com/2.0/user/{user_id}/playlists?limit=100")
            resp.raise_for_status()
            data = resp.json().get("data", [])
            self.call_from_thread(self._populate_playlists, data)
        except Exception as e:
            self.call_from_thread(self._set_status, f"✗ {e}")

    def _populate_playlists(self, data: list) -> None:
        self._current_results = data
        self._current_type = "playlist"
        table = self.query_one("#results-table", DataTable)
        table.clear()
        for pl in data:
            table.add_row(
                "🎶 Playlist",
                pl.get("title", "?"),
                pl.get("user", {}).get("name", "") if isinstance(pl.get("user"), dict) else "",
                str(pl.get("nb_tracks", "")),
                key=str(pl.get("id", "")),
            )
        self._set_status(f"Loaded {len(data)} playlists  —  Enter or Ctrl+D to act")

    @work(thread=True)
    def _browse_albums(self) -> None:
        if not self._authenticated:
            self.call_from_thread(self._set_status, "Not authenticated")
            return
        self.call_from_thread(self._set_status, "Loading your favourite albums…")
        try:
            sess = self._downloader.session
            user_id = self._downloader.user_id
            resp = sess.get(f"https://api.deezer.com/2.0/user/{user_id}/albums?limit=100")
            resp.raise_for_status()
            data = resp.json().get("data", [])
            self.call_from_thread(self._populate_albums, data)
        except Exception as e:
            self.call_from_thread(self._set_status, f"✗ {e}")

    def _populate_albums(self, data: list) -> None:
        self._current_results = data
        self._current_type = "album"
        table = self.query_one("#results-table", DataTable)
        table.clear()
        for al in data:
            table.add_row(
                "💿 Album",
                al.get("title", "?"),
                al.get("artist", {}).get("name", "") if isinstance(al.get("artist"), dict) else "",
                str(al.get("nb_tracks", "")),
                key=str(al.get("id", "")),
            )
        self._set_status(f"Loaded {len(data)} albums  —  Enter or Ctrl+D to act")

    @work(thread=True)
    def _browse_artists(self) -> None:
        if not self._authenticated:
            self.call_from_thread(self._set_status, "Not authenticated")
            return
        self.call_from_thread(self._set_status, "Loading your favourite artists…")
        try:
            sess = self._downloader.session
            user_id = self._downloader.user_id
            resp = sess.get(f"https://api.deezer.com/2.0/user/{user_id}/artists?limit=100")
            resp.raise_for_status()
            data = resp.json().get("data", [])
            self.call_from_thread(self._populate_artists, data)
        except Exception as e:
            self.call_from_thread(self._set_status, f"✗ {e}")

    def _populate_artists(self, data: list) -> None:
        self._current_results = data
        self._current_type = "artist"
        table = self.query_one("#results-table", DataTable)
        table.clear()
        for ar in data:
            table.add_row(
                "👤 Artist",
                ar.get("name", "?"),
                "",
                str(ar.get("nb_album", "")),
                key=str(ar.get("id", "")),
            )
        self._set_status(f"Loaded {len(data)} artists  —  Enter or Ctrl+D to browse albums")

    def _show_download_log(self) -> None:
        self._set_status("Showing download log")
        self.query_one("#dl-status", Log).focus()

    # ── Row selection (Enter) ──────────────────────────────────────────────────

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = str(event.row_key.value)
        self._on_row_activated(row_key)

    def _on_row_activated(self, row_key: str) -> None:
        # Find the item in current results
        item = next(
            (r for r in self._current_results if str(r.get("id", "")) == row_key),
            None,
        )
        if not item:
            return

        itype = (item.get("type") or self._current_type or "track").lower()
        item_id = str(item.get("id", ""))

        if itype == "track":
            self._confirm_download_track(item_id, item)
        elif itype == "album":
            self._open_album(item_id)
        elif itype == "playlist":
            self._open_playlist(item_id)
        elif itype == "artist":
            self._open_artist(item_id)

    @work(thread=True)
    def _open_album(self, album_id: str) -> None:
        self.call_from_thread(self._set_status, f"Loading album {album_id}…")
        try:
            sess = self._downloader.session
            meta  = sess.get(f"https://api.deezer.com/2.0/album/{album_id}").json()
            resp  = sess.get(f"https://api.deezer.com/2.0/album/{album_id}/tracks?limit=200").json()
            tracks = resp.get("data", [])
            title  = meta.get("title", album_id)
            self.call_from_thread(
                lambda: self.push_screen(
                    DetailModal(f"💿 {title}", tracks, "album", album_id),
                    self._on_detail_result,
                )
            )
        except Exception as e:
            self.call_from_thread(self._set_status, f"✗ {e}")

    @work(thread=True)
    def _open_playlist(self, playlist_id: str) -> None:
        self.call_from_thread(self._set_status, f"Loading playlist {playlist_id}…")
        try:
            sess   = self._downloader.session
            meta   = sess.get(f"https://api.deezer.com/2.0/playlist/{playlist_id}").json()
            resp   = sess.get(f"https://api.deezer.com/2.0/playlist/{playlist_id}/tracks?limit=200").json()
            tracks = resp.get("data", [])
            title  = meta.get("title", playlist_id)
            self.call_from_thread(
                lambda: self.push_screen(
                    DetailModal(f"🎶 {title}", tracks, "playlist", playlist_id),
                    self._on_detail_result,
                )
            )
        except Exception as e:
            self.call_from_thread(self._set_status, f"✗ {e}")

    @work(thread=True)
    def _open_artist(self, artist_id: str) -> None:
        self.call_from_thread(self._set_status, f"Loading artist albums…")
        try:
            sess   = self._downloader.session
            meta   = sess.get(f"https://api.deezer.com/2.0/artist/{artist_id}").json()
            albums = sess.get(f"https://api.deezer.com/2.0/artist/{artist_id}/albums?limit=100").json().get("data", [])
            name   = meta.get("name", artist_id)
            # Show albums in results table
            self.call_from_thread(self._populate_albums_for_artist, albums, name)
        except Exception as e:
            self.call_from_thread(self._set_status, f"✗ {e}")

    def _populate_albums_for_artist(self, albums: list, artist_name: str) -> None:
        self._current_results = albums
        self._current_type = "album"
        table = self.query_one("#results-table", DataTable)
        table.clear()
        for al in albums:
            table.add_row(
                "💿 Album",
                al.get("title", "?"),
                artist_name,
                str(al.get("nb_tracks", "")),
                key=str(al.get("id", "")),
            )
        self._set_status(f"👤 {artist_name} — {len(albums)} albums  —  Enter to browse")

    def _on_detail_result(self, result: Optional[dict]) -> None:
        if result and result.get("action") == "download":
            ctype = result["type"]
            cid   = result["id"]
            if ctype == "album":
                self._download_album(cid)
            elif ctype == "playlist":
                self._download_playlist(cid)

    # ── Ctrl+D: download selected row ─────────────────────────────────────────

    def action_download_sel(self) -> None:
        table = self.query_one("#results-table", DataTable)
        if table.cursor_row < 0:
            self._set_status("No row selected")
            return
        row_key = str(table.get_row_at(table.cursor_row)[0])  # not reliable; use cursor_coordinate
        # Better: use row key from the DataTable coordinate
        coord = table.cursor_coordinate
        rows  = list(table.rows)
        if coord.row >= len(rows):
            return
        rkey = str(rows[coord.row].value)
        self._on_row_activated(rkey)

    # ── Download helpers ───────────────────────────────────────────────────────

    def _confirm_download_track(self, track_id: str, track_info: dict) -> None:
        title  = track_info.get("title") or track_info.get("SNG_TITLE", track_id)
        artist = ""
        if isinstance(track_info.get("artist"), dict):
            artist = track_info["artist"].get("name", "")
        self._set_status(f"Downloading: {artist} — {title}")
        self._download_track(track_id)

    @work(thread=True)
    def _download_track(self, track_id: str) -> None:
        log_widget = self.query_one("#dl-status", Log)
        progress   = self.query_one("#dl-progress", ProgressBar)

        def _prog(pct: float) -> None:
            self.call_from_thread(progress.update, progress=pct)

        self.call_from_thread(log_widget.write_line, f"⬇ Track {track_id}…")
        result = self._downloader.download_track(
            track_id,
            self.output_dir,
            progress_cb=_prog,
        )
        if result:
            self.call_from_thread(log_widget.write_line, f"✓ {Path(result).name}")
            self.call_from_thread(self._set_status, f"✓ Downloaded: {Path(result).name}")
        else:
            self.call_from_thread(log_widget.write_line, f"✗ Failed: track {track_id}")
        self.call_from_thread(progress.update, progress=0)

    @work(thread=True)
    def _download_album(self, album_id: str) -> None:
        log_widget = self.query_one("#dl-status", Log)
        self.call_from_thread(log_widget.write_line, f"⬇ Album {album_id}…")
        self.call_from_thread(self._set_status, f"Downloading album {album_id}…")
        try:
            self._downloader.download_album(album_id, self.output_dir)
            self.call_from_thread(log_widget.write_line, f"✓ Album {album_id} complete")
            self.call_from_thread(self._set_status, f"✓ Album {album_id} downloaded")
        except Exception as e:
            self.call_from_thread(log_widget.write_line, f"✗ Album error: {e}")

    @work(thread=True)
    def _download_playlist(self, playlist_id: str) -> None:
        log_widget = self.query_one("#dl-status", Log)
        self.call_from_thread(log_widget.write_line, f"⬇ Playlist {playlist_id}…")
        self.call_from_thread(self._set_status, f"Downloading playlist {playlist_id}…")
        try:
            self._downloader.download_playlist(playlist_id, self.output_dir)
            self.call_from_thread(log_widget.write_line, f"✓ Playlist {playlist_id} complete")
            self.call_from_thread(self._set_status, f"✓ Playlist {playlist_id} downloaded")
        except Exception as e:
            self.call_from_thread(log_widget.write_line, f"✗ Playlist error: {e}")

    # ── Misc actions ───────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        self._set_status("Refreshing…")
        if self.arl:
            self._connect()

    def action_quit(self) -> None:
        self.exit()


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(description="Deezload TUI — browse and download Deezer music")
    ap.add_argument("--arl", default="", help="Deezer ARL token (optional, saved if provided)")
    args = ap.parse_args()

    app = DeezloadTUI(initial_arl=args.arl)
    app.run()


if __name__ == "__main__":
    main()
