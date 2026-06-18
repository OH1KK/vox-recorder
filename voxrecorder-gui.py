#!/usr/bin/env python3
"""
VOX-recorder GUI - records audio when sound is present, with tkinter interface
Copyright (C) 2015-2024 Kari Karvonen <oh1kk@toimii.fi>

GNU GPL v3 or later.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import threading
import time
import os
import uuid
import json
import subprocess
import queue
from sys import byteorder
from array import array
from struct import pack

try:
    import pyaudio
    import wave
    PYAUDIO_OK = True
except ImportError:
    PYAUDIO_OK = False

__version__ = "2026.06.18.01"

RATE        = 44100
CHUNK_SIZE  = 1024
FORMAT_STR  = "paInt16"
MAXIMUMVOL  = 32767
NUM_VU_BARS = 40

# ── Stuck-detection: if no bytes arrive within this many seconds, restart ──────
STUCK_TIMEOUT = 4.0

# ── Colours ───────────────────────────────────────────────────────────────────
BG        = "#0d0d0d"
BG2       = "#141414"
BG3       = "#1c1c1c"
BORDER    = "#2a2a2a"
GREEN     = "#00e676"
GREEN_DIM = "#004d26"
AMBER     = "#ffab00"
RED       = "#ff1744"
MUTED     = "#4a4a4a"
TEXT      = "#c8c8c8"
TEXT_DIM  = "#6a6a6a"
MONO_SM   = "Monospace 8"
MONO_LG   = "Monospace 11 bold"
SANS      = "Sans 9"

PX = 16   # standard horizontal padding for settings page widgets


# ══════════════════════════════════════════════════════════════════════════════
class VoxRecorderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"VOX Recorder  v{__version__}")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(640, 540)

        # ── Runtime state ──
        self.recording      = False
        self.vox_listening  = False   # True while VOX is armed but not yet recording
        self.manual_active  = False
        self.stop_event     = threading.Event()
        self.audio_thread   = None
        self.vu_queue       = queue.Queue(maxsize=4)
        self.log_queue      = queue.Queue()
        self.rec_start_time = 0
        self.session_count  = 0
        self._last_vu_level = 0
        self._vu_rects      = []
        self._thr_line      = None
        self._thr_tri       = None
        self._thr_lbl_id    = None

        # ── Config vars ──
        self.vox_threshold   = tk.IntVar(value=2000)
        self.tail_silence    = tk.DoubleVar(value=5.0)
        self.filename_prefix = tk.StringVar(value="voxrecord")
        self.save_path       = tk.StringVar(value=os.path.expanduser("~/vox-records"))
        self.meta_script     = tk.StringVar(value="")
        self.channel_name    = tk.StringVar(value="")
        self.normalize_audio = tk.BooleanVar(value=True)
        self.trim_audio      = tk.BooleanVar(value=True)
        self.add_silence_pad = tk.BooleanVar(value=True)
        self.mode_var        = tk.StringVar(value="vox")
        self.audio_device_idx= tk.IntVar(value=-1)   # -1 = default

        # Populated after pyaudio init
        self._device_names  = []   # list of (index, name) for input devices
        self._device_map    = {}   # display_name -> index

        self._build_ui()
        self._populate_devices()
        self._start_vu_updater()
        self._start_log_updater()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if not PYAUDIO_OK:
            self._log("⚠  pyaudio not found. Install:  pip install pyaudio", color=AMBER)

    # ═══════════════════════════════════════════════════════════════════════════
    # UI Construction
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        # Top bar
        top = tk.Frame(self, bg=BG, pady=6, padx=10)
        top.pack(fill="x")
        tk.Label(top, text="▐ VOX RECORDER", font="Monospace 13 bold",
                 bg=BG, fg=GREEN).pack(side="left")
        tk.Label(top, text=f"v{__version__}", font=MONO_SM,
                 bg=BG, fg=TEXT_DIM).pack(side="left", padx=(8, 0))
        self._rec_indicator = tk.Label(top, text="●", font="Monospace 16",
                                        bg=BG, fg=MUTED)
        self._rec_indicator.pack(side="right", padx=(0, 4))
        self._rec_label = tk.Label(top, text="IDLE", font=MONO_LG,
                                    bg=BG, fg=MUTED)
        self._rec_label.pack(side="right", padx=(0, 8))
        self._timer_label = tk.Label(top, text="00:00", font=MONO_LG,
                                      bg=BG, fg=TEXT_DIM)
        self._timer_label.pack(side="right", padx=(0, 12))

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Tab bar
        tab_bar = tk.Frame(self, bg=BG2)
        tab_bar.pack(fill="x")
        self._page_main     = tk.Frame(self, bg=BG)
        self._page_settings = tk.Frame(self, bg=BG)
        self._tab_btns = {}
        for key, label in [("main", "  MAIN  "), ("settings", "  SETTINGS  ")]:
            b = tk.Button(tab_bar, text=label, font=MONO_SM,
                          bg=BG2, fg=TEXT_DIM, relief="flat", bd=0,
                          padx=6, pady=5, cursor="hand2",
                          command=lambda k=key: self._show_page(k))
            b.pack(side="left")
            self._tab_btns[key] = b

        self._show_page("main")
        self._build_main_page(self._page_main)
        self._build_settings_page(self._page_settings)

        # Status bar
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        sb = tk.Frame(self, bg=BG2, pady=3, padx=10)
        sb.pack(fill="x")
        self._status_var = tk.StringVar(value="Ready.")
        tk.Label(sb, textvariable=self._status_var, font=MONO_SM,
                 bg=BG2, fg=TEXT_DIM, anchor="w").pack(side="left")
        self._session_label = tk.Label(sb, text="Sessions: 0", font=MONO_SM,
                                        bg=BG2, fg=TEXT_DIM)
        self._session_label.pack(side="right")

    def _show_page(self, key):
        self._page_main.pack_forget()
        self._page_settings.pack_forget()
        {"main": self._page_main, "settings": self._page_settings}[key].pack(
            fill="both", expand=True)
        for k, b in self._tab_btns.items():
            b.config(bg=BG if k == key else BG2,
                     fg=GREEN if k == key else TEXT_DIM)

    def _section_hdr(self, parent, title):
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="x", pady=(0, 4))
        tk.Label(f, text=f"  {title}", font=MONO_SM, bg=BG,
                 fg=GREEN, anchor="w").pack(fill="x")
        tk.Frame(f, bg=GREEN_DIM, height=1).pack(fill="x")

    # ── Main page ──────────────────────────────────────────────────────────────

    def _build_main_page(self, parent):
        self._build_vu(parent)
        self._build_controls(parent)
        self._build_log(parent)

    # ── VU meter ───────────────────────────────────────────────────────────────

    def _build_vu(self, parent):
        self._section_hdr(parent, "INPUT LEVEL")
        vu_wrap = tk.Frame(parent, bg=BG3, pady=6, padx=8)
        vu_wrap.pack(fill="x", pady=(2, 2))

        self._vu_canvas = tk.Canvas(vu_wrap, height=40, bg=BG3,
                                     highlightthickness=0)
        self._vu_canvas.pack(fill="x")
        self._vu_canvas.bind("<Configure>", self._redraw_vu_bars)

        thr_row = tk.Frame(vu_wrap, bg=BG3)
        thr_row.pack(fill="x", pady=(4, 0))
        tk.Label(thr_row, text="THRESHOLD:", font=MONO_SM,
                 bg=BG3, fg=TEXT_DIM).pack(side="left")
        tk.Scale(thr_row, variable=self.vox_threshold,
                 from_=200, to=10000, orient="horizontal",
                 bg=BG3, fg=TEXT, troughcolor=BG,
                 highlightthickness=0, sliderlength=12,
                 showvalue=False, bd=0).pack(side="left", fill="x",
                                              expand=True, padx=4)
        tk.Label(thr_row, textvariable=self.vox_threshold, width=5,
                 font=MONO_SM, bg=BG3, fg=GREEN).pack(side="left")
        self.vox_threshold.trace_add("write", self._on_threshold_change)

    def _redraw_vu_bars(self, event=None):
        self._vu_canvas.delete("all")
        self._vu_rects   = []
        self._thr_line   = None
        self._thr_tri    = None
        self._thr_lbl_id = None
        w = self._vu_canvas.winfo_width()
        if w < 10:
            return
        seg_w  = w / NUM_VU_BARS
        gap    = max(1, int(seg_w * 0.18))
        h      = self._vu_canvas.winfo_height()
        bar_h  = h - 10   # bottom 10 px reserved for triangle marker
        for i in range(NUM_VU_BARS):
            x0 = int(i * seg_w)
            x1 = int((i + 1) * seg_w) - gap
            r  = self._vu_canvas.create_rectangle(x0, 4, x1, bar_h - 2,
                                                    fill=BG2, outline="")
            self._vu_rects.append(r)
        self._draw_threshold_marker(w, bar_h, h)
        self._apply_vu_level(self._last_vu_level)

    def _draw_threshold_marker(self, canvas_w=None, bar_h=None, canvas_h=None):
        if canvas_w is None:
            canvas_w = self._vu_canvas.winfo_width()
        if canvas_w < 10:
            return
        if canvas_h is None:
            canvas_h = self._vu_canvas.winfo_height()
        if bar_h is None:
            bar_h = canvas_h - 10
        for item in [self._thr_line, self._thr_tri, self._thr_lbl_id]:
            if item is not None:
                self._vu_canvas.delete(item)
        x = int(min(self.vox_threshold.get() / MAXIMUMVOL, 1.0) * canvas_w)
        self._thr_line = self._vu_canvas.create_line(
            x, 2, x, bar_h, fill=AMBER, width=2, dash=(3, 2))
        half = 5
        self._thr_tri = self._vu_canvas.create_polygon(
            x - half, bar_h + 1,
            x + half, bar_h + 1,
            x,        canvas_h - 1,
            fill=AMBER, outline="")
        lbl_x  = x + 4 if x < canvas_w - 32 else x - 4
        anchor = "nw"  if x < canvas_w - 32 else "ne"
        self._thr_lbl_id = self._vu_canvas.create_text(
            lbl_x, 4, text="THR", font="Monospace 7",
            fill=AMBER, anchor=anchor)

    def _on_threshold_change(self, *_):
        if self._vu_canvas.winfo_width() > 10:
            self._draw_threshold_marker()
            self._apply_vu_level(self._last_vu_level)

    def _apply_vu_level(self, level_0_to_1):
        self._last_vu_level = level_0_to_1
        thr_ratio = self.vox_threshold.get() / MAXIMUMVOL
        lit_count = int(level_0_to_1 * NUM_VU_BARS)
        thr_bar   = int(thr_ratio * NUM_VU_BARS)
        for i, r in enumerate(self._vu_rects):
            if i < lit_count:
                col = (RED if self.recording else AMBER) if i >= thr_bar \
                      else (GREEN if i >= max(0, thr_bar - 4) else GREEN_DIM)
            else:
                col = BG2
            self._vu_canvas.itemconfig(r, fill=col)

    # ── Controls ───────────────────────────────────────────────────────────────

    def _build_controls(self, parent):
        self._section_hdr(parent, "CONTROLS")
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(4, 6), padx=8)

        # ── Mode selector: custom toggle buttons ──
        mode_frame = tk.Frame(row, bg=BG3, bd=0)
        mode_frame.pack(side="left", padx=(0, 16))

        self._mode_vox_btn = tk.Button(
            mode_frame, text="◉  VOX Auto",
            font="Monospace 9 bold", relief="flat", bd=0,
            padx=10, pady=6, cursor="hand2",
            command=lambda: self._set_mode("vox"))
        self._mode_vox_btn.pack(side="left")

        tk.Frame(mode_frame, bg=BG, width=1).pack(side="left")   # divider gap

        self._mode_man_btn = tk.Button(
            mode_frame, text="◉  Manual",
            font="Monospace 9 bold", relief="flat", bd=0,
            padx=10, pady=6, cursor="hand2",
            command=lambda: self._set_mode("manual"))
        self._mode_man_btn.pack(side="left")

        self._refresh_mode_buttons()   # paint initial state

        # ── Action buttons ──
        btn_frame = tk.Frame(row, bg=BG)
        btn_frame.pack(side="left")
        self._start_btn = self._btn(btn_frame, "▶  START VOX", self._start,
                                     fg=BG, bg=GREEN, abg="#00c853")
        self._start_btn.pack(side="left", padx=(0, 6))
        self._stop_btn  = self._btn(btn_frame, "■  STOP", self._stop,
                                     fg=BG, bg=RED, abg="#d50000",
                                     state="disabled")
        self._stop_btn.pack(side="left", padx=(0, 6))
        self._rec_btn   = self._btn(btn_frame, "⏺  REC NOW", self._manual_rec,
                                     fg=BG, bg=AMBER, abg="#ff6f00",
                                     state="disabled")
        self._rec_btn.pack(side="left")

        ts_row = tk.Frame(parent, bg=BG)
        ts_row.pack(fill="x", padx=8, pady=(0, 4))
        tk.Label(ts_row, text="VOX tail silence (s):", font=MONO_SM,
                 bg=BG, fg=TEXT_DIM).pack(side="left")
        tk.Spinbox(ts_row, from_=1, to=60, increment=0.5,
                   textvariable=self.tail_silence, width=5,
                   font=MONO_SM, bg=BG3, fg=TEXT, insertbackground=GREEN,
                   buttonbackground=BG2, relief="flat").pack(side="left", padx=4)

        # Channel name (quick access on main page)
        ch_row = tk.Frame(parent, bg=BG)
        ch_row.pack(fill="x", padx=8, pady=(0, 4))
        tk.Label(ch_row, text="Channel name:", font=MONO_SM,
                 bg=BG, fg=TEXT_DIM).pack(side="left")
        tk.Entry(ch_row, textvariable=self.channel_name, font=MONO_SM,
                 bg=BG3, fg=TEXT, insertbackground=GREEN,
                 relief="flat", bd=2, width=24).pack(side="left", padx=4)

    def _btn(self, parent, text, cmd, fg=TEXT, bg=BG3, abg=BG2, state="normal"):
        return tk.Button(parent, text=text, command=cmd,
                         font="Monospace 9 bold",
                         fg=fg, bg=bg, activeforeground=fg,
                         activebackground=abg, relief="flat",
                         padx=10, pady=5, state=state,
                         cursor="hand2", bd=0)

    def _build_log(self, parent):
        self._section_hdr(parent, "ACTIVITY LOG")
        self._log_box = scrolledtext.ScrolledText(
            parent, height=10, font=MONO_SM,
            bg=BG2, fg=TEXT, insertbackground=GREEN,
            selectbackground=GREEN_DIM, relief="flat", bd=0,
            wrap="word", state="disabled")
        self._log_box.pack(fill="both", expand=True, pady=(2, 0))
        for tag, col in [("green", GREEN), ("amber", AMBER),
                          ("red", RED), ("dim", TEXT_DIM), ("normal", TEXT)]:
            self._log_box.tag_config(tag, foreground=col)

    # ── Settings page ──────────────────────────────────────────────────────────

    def _build_settings_page(self, parent):
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        vsb    = tk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner  = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>",
                   lambda e: canvas.configure(
                       scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(
                            int(-1 * (e.delta / 120)), "units"))

        # helper: pack a row with consistent left/right padding
        def row(pady_bottom=8):
            f = tk.Frame(inner, bg=BG)
            f.pack(fill="x", padx=PX, pady=(0, pady_bottom))
            return f

        # ── Audio device ──
        self._s_section(inner, "AUDIO INPUT DEVICE")
        self._s_lbl(inner, "Sound card / input device")
        dev_row = row(8)
        self._device_var = tk.StringVar(value="Default input device")
        self._device_combo = tk.OptionMenu(dev_row, self._device_var, "Default input device")
        self._device_combo.config(font=MONO_SM, bg=BG3, fg=TEXT,
                                   activebackground=BG2, activeforeground=GREEN,
                                   highlightthickness=0, relief="flat", bd=0)
        self._device_combo["menu"].config(font=MONO_SM, bg=BG2, fg=TEXT,
                                           activebackground=GREEN_DIM,
                                           activeforeground=GREEN)
        self._device_combo.pack(side="left", fill="x", expand=True)
        tk.Button(dev_row, text="↺ Refresh", command=self._populate_devices,
                  font=MONO_SM, bg=BG2, fg=TEXT, relief="flat",
                  padx=6, pady=2, cursor="hand2", bd=0).pack(side="left", padx=(4, 0))

        # ── File storage ──
        self._s_section(inner, "FILE STORAGE")
        self._s_lbl(inner, "Save path")
        path_row = row(8)
        tk.Entry(path_row, textvariable=self.save_path, font=MONO_SM,
                 bg=BG3, fg=TEXT, insertbackground=GREEN,
                 relief="flat", bd=2).pack(side="left", fill="x", expand=True)
        tk.Button(path_row, text="…", command=self._browse_path,
                  font=MONO_SM, bg=BG2, fg=TEXT, relief="flat",
                  padx=4, cursor="hand2", bd=0).pack(side="left", padx=(2, 0))

        self._s_lbl(inner, "Filename prefix")
        tk.Entry(row(4), textvariable=self.filename_prefix, font=MONO_SM,
                 bg=BG3, fg=TEXT, insertbackground=GREEN,
                 relief="flat", bd=2).pack(fill="x")
        tk.Button(inner, text="Create save directory",
                  command=self._ensure_dir, font=MONO_SM,
                  bg=BG3, fg=TEXT, relief="flat", padx=8, pady=4,
                  cursor="hand2", bd=0, anchor="w").pack(
                      fill="x", padx=PX, pady=(0, 12))

        # ── VOX settings ──
        self._s_section(inner, "VOX SETTINGS")
        self._s_lbl(inner, "Silence threshold  (200 – 10000)")
        thr_row = row(4)
        tk.Scale(thr_row, variable=self.vox_threshold,
                 from_=200, to=10000, orient="horizontal",
                 bg=BG, fg=TEXT, troughcolor=BG3,
                 highlightthickness=0, sliderlength=14,
                 showvalue=False, bd=0).pack(side="left", fill="x", expand=True)
        tk.Label(thr_row, textvariable=self.vox_threshold, width=6,
                 font=MONO_SM, bg=BG, fg=GREEN, anchor="e").pack(side="left")

        self._s_lbl(inner, "Tail silence (seconds after audio drops)")
        ts_row = row(12)
        tk.Spinbox(ts_row, from_=1, to=60, increment=0.5,
                   textvariable=self.tail_silence, width=6,
                   font=MONO_SM, bg=BG3, fg=TEXT,
                   insertbackground=GREEN, buttonbackground=BG2,
                   relief="flat").pack(side="left")

        # ── Channel / metadata ──
        self._s_section(inner, "CHANNEL & METADATA")
        self._s_lbl(inner, "Channel name (stored in JSON sidecar)")
        tk.Entry(row(4), textvariable=self.channel_name, font=MONO_SM,
                 bg=BG3, fg=TEXT, insertbackground=GREEN,
                 relief="flat", bd=2).pack(fill="x")
        tk.Label(inner,
                 text="  e.g.  'Tampere-pyörre 145.600 MHz'  or  'PORT VHF 156.8'",
                 font="Monospace 7", bg=BG, fg=TEXT_DIM, anchor="w").pack(
                     fill="x", padx=PX, pady=(0, 6))

        self._s_lbl(inner, "Metadata script (optional executable)")
        tk.Label(inner,
                 text="  Called before each recording. Must print JSON to stdout.\n"
                      '  Example output:  {"frequency": 145600000, "mode": "NFM"}',
                 font="Monospace 7", bg=BG, fg=TEXT_DIM, justify="left").pack(
                     anchor="w", padx=PX, pady=(0, 4))
        ms_row = row(4)
        tk.Entry(ms_row, textvariable=self.meta_script, font=MONO_SM,
                 bg=BG3, fg=TEXT, insertbackground=GREEN,
                 relief="flat", bd=2).pack(side="left", fill="x", expand=True)
        tk.Button(ms_row, text="…", command=self._browse_script,
                  font=MONO_SM, bg=BG2, fg=TEXT, relief="flat",
                  padx=4, cursor="hand2", bd=0).pack(side="left", padx=(2, 0))
        tk.Button(inner, text="Test script now",
                  command=self._test_meta_script, font=MONO_SM,
                  bg=BG3, fg=TEXT, relief="flat", padx=8, pady=4,
                  cursor="hand2", bd=0, anchor="w").pack(
                      fill="x", padx=PX, pady=(0, 12))

        # ── Audio processing ──
        self._s_section(inner, "AUDIO PROCESSING")
        for var, txt, detail in [
            (self.normalize_audio, "Normalize level",    "Scale peak to maximum"),
            (self.trim_audio,      "Trim silence",        "Remove leading/trailing silence"),
            (self.add_silence_pad, "Add 0.5 s padding",  "Prepend and append short silence"),
        ]:
            r = tk.Frame(inner, bg=BG)
            r.pack(fill="x", padx=PX, pady=(2, 0))
            tk.Checkbutton(r, text=txt, variable=var, font=MONO_SM,
                           bg=BG, fg=TEXT, selectcolor=BG3,
                           activebackground=BG, activeforeground=GREEN,
                           highlightthickness=0).pack(side="left")
            tk.Label(r, text=f"— {detail}", font="Monospace 7",
                     bg=BG, fg=TEXT_DIM).pack(side="left", padx=(4, 0))

        tk.Frame(inner, bg=BG, height=16).pack()

    def _s_section(self, parent, title):
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="x", pady=(10, 2))
        tk.Label(f, text=f"  {title}", font=MONO_SM, bg=BG,
                 fg=GREEN, anchor="w").pack(fill="x", padx=PX)
        tk.Frame(f, bg=GREEN_DIM, height=1).pack(fill="x", padx=PX)

    def _s_lbl(self, parent, text):
        tk.Label(parent, text=text, font=MONO_SM, bg=BG,
                 fg=TEXT_DIM, anchor="w").pack(fill="x", padx=PX, pady=(6, 1))

    # ── Device enumeration ─────────────────────────────────────────────────────

    def _populate_devices(self):
        if not PYAUDIO_OK:
            return
        self._device_names = [("Default input device", -1)]
        try:
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    name = f"[{i}] {info['name']}"
                    self._device_names.append((name, i))
            p.terminate()
        except Exception as e:
            self._log(f"Device enumeration error: {e}", color=AMBER)

        self._device_map = {n: i for n, i in self._device_names}
        menu = self._device_combo["menu"]
        menu.delete(0, "end")
        current = self._device_var.get()
        names   = [n for n, _ in self._device_names]
        for name in names:
            menu.add_command(label=name,
                             command=lambda v=name: self._device_var.set(v))
        if current not in names:
            self._device_var.set(names[0])
        self._log(f"Found {len(self._device_names) - 1} input device(s).", color=TEXT_DIM)

    def _get_device_index(self):
        """Return pyaudio device index, or None for default."""
        chosen = self._device_var.get()
        idx    = self._device_map.get(chosen, -1)
        return None if idx == -1 else idx

    # ═══════════════════════════════════════════════════════════════════════════
    # Event handlers
    # ═══════════════════════════════════════════════════════════════════════════

    def _set_mode(self, mode):
        self.mode_var.set(mode)
        self._refresh_mode_buttons()
        if mode == "manual":
            self._start_btn.config(text="▶  MONITOR")
        else:
            self._start_btn.config(text="▶  START VOX")
        self._rec_btn.config(state="disabled")

    def _refresh_mode_buttons(self):
        mode = self.mode_var.get()
        if mode == "vox":
            self._mode_vox_btn.config(bg=GREEN, fg=BG,
                                       activebackground="#00c853",
                                       activeforeground=BG)
            self._mode_man_btn.config(bg=BG3, fg=MUTED,
                                       activebackground=BG2,
                                       activeforeground=TEXT)
        else:
            self._mode_vox_btn.config(bg=BG3, fg=MUTED,
                                       activebackground=BG2,
                                       activeforeground=TEXT)
            self._mode_man_btn.config(bg=AMBER, fg=BG,
                                       activebackground="#ff6f00",
                                       activeforeground=BG)

    def _browse_path(self):
        d = filedialog.askdirectory(initialdir=self.save_path.get())
        if d:
            self.save_path.set(d)

    def _browse_script(self):
        f = filedialog.askopenfilename(
            filetypes=[("Scripts", "*.py *.sh *.bash *.pl *.rb"), ("All", "*")])
        if f:
            self.meta_script.set(f)

    def _ensure_dir(self):
        p = self.save_path.get()
        try:
            os.makedirs(p, exist_ok=True)
            self._log(f"Directory ready: {p}", color=GREEN)
        except Exception as e:
            self._log(f"Could not create directory: {e}", color=RED)

    def _test_meta_script(self):
        result = self._get_metadata()
        self._log(f"Script → {json.dumps(result) if result else '(empty)'}", color=GREEN)
        self._show_page("main")

    def _start(self):
        if not PYAUDIO_OK:
            messagebox.showerror("Error", "pyaudio is not installed.\n\npip install pyaudio")
            return
        p = self.save_path.get()
        if not os.access(p, os.W_OK):
            if messagebox.askyesno("Directory missing",
                                   f"{p}\n\nCreate it now?"):
                self._ensure_dir()
            else:
                return
        self.stop_event.clear()
        self._start_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        if self.mode_var.get() == "manual":
            self._rec_btn.config(state="normal")
            self._log("Monitor started (manual mode).", color=GREEN)
            self._set_status("Monitoring – press REC NOW to record")
            self.vox_listening = False
            self._update_rec_ui(False)
            target = self._monitor_loop
        else:
            self._rec_btn.config(state="disabled")
            self._log("VOX started. Waiting for audio…", color=GREEN)
            self._set_status("Listening for audio…")
            self.vox_listening = True
            self._update_rec_ui(False)
            self._start_waiting_pulse()
            target = self._vox_loop
        self.audio_thread = threading.Thread(target=target, daemon=True)
        self.audio_thread.start()

    def _stop(self):
        self.stop_event.set()
        self.vox_listening = False
        self._start_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        self._rec_btn.config(state="disabled")
        self._update_rec_ui(False)
        self._log("Stopped.", color=TEXT_DIM)
        self._set_status("Ready.")
        self.recording = False

    def _manual_rec(self):
        if not self.recording:
            self.recording     = True
            self.manual_active = True
            self._rec_btn.config(text="■  STOP REC")
        else:
            self.recording     = False
            self.manual_active = False
            self._rec_btn.config(text="⏺  REC NOW")

    def _on_close(self):
        self.stop_event.set()
        self.destroy()

    # ═══════════════════════════════════════════════════════════════════════════
    # Audio – stream helper with stuck detection
    # ═══════════════════════════════════════════════════════════════════════════

    def _open_stream(self):
        import pyaudio as pa
        fmt    = getattr(pa, FORMAT_STR)
        p      = pa.PyAudio()
        kwargs = dict(format=fmt, channels=1, rate=RATE,
                      input=True, frames_per_buffer=CHUNK_SIZE)
        dev = self._get_device_index()
        if dev is not None:
            kwargs["input_device_index"] = dev
        stream = p.open(**kwargs)
        return p, stream, fmt

    def _read_chunk_with_stuck_detect(self, stream):
        """
        Read one chunk. Raises RuntimeError if the stream appears stuck
        (no data returned within STUCK_TIMEOUT seconds).
        Uses a short-timeout poll so we don't block the stop_event.
        """
        deadline = time.time() + STUCK_TIMEOUT
        while time.time() < deadline:
            if self.stop_event.is_set():
                return None
            avail = stream.get_read_available()
            if avail >= CHUNK_SIZE:
                raw = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                chunk = array('h', raw)
                if byteorder == 'big':
                    chunk.byteswap()
                return chunk
            time.sleep(0.02)
        raise RuntimeError("Audio stream stuck – no data received")

    def _push_vu(self, chunk):
        level = min(max(chunk) / MAXIMUMVOL, 1.0)
        try:
            self.vu_queue.put_nowait(level)
        except queue.Full:
            pass

    # ── VOX loop with auto-restart on stuck ────────────────────────────────────

    def _vox_loop(self):
        while not self.stop_event.is_set():
            try:
                p, stream, fmt = self._open_stream()
            except Exception as e:
                self._log(f"Audio open failed: {e}", color=RED)
                return
            self._log("Listening…", color=TEXT_DIM)
            try:
                while not self.stop_event.is_set():
                    # Wait for VOX trigger
                    triggered = False
                    while not self.stop_event.is_set():
                        chunk = self._read_chunk_with_stuck_detect(stream)
                        if chunk is None:
                            break
                        self._push_vu(chunk)
                        if max(chunk) > self.vox_threshold.get():
                            triggered = True
                            break
                    if not triggered:
                        break
                    self._do_record_session(p, stream, fmt, chunk)
                break   # clean exit
            except RuntimeError as e:
                self._log(f"⚠  {e} — restarting…", color=AMBER)
                self._set_status("Stream stuck – restarting audio…")
                try:
                    stream.stop_stream(); stream.close(); p.terminate()
                except Exception:
                    pass
                time.sleep(1.0)
                # loop continues → reopen stream
            finally:
                try:
                    stream.stop_stream(); stream.close(); p.terminate()
                except Exception:
                    pass

    # ── Manual monitor loop with auto-restart on stuck ─────────────────────────

    def _monitor_loop(self):
        while not self.stop_event.is_set():
            try:
                p, stream, fmt = self._open_stream()
            except Exception as e:
                self._log(f"Audio open failed: {e}", color=RED)
                return
            snd_data     = array('h')
            rec_start    = 0
            wav_filename = ""
            wf           = None
            try:
                while not self.stop_event.is_set():
                    chunk = self._read_chunk_with_stuck_detect(stream)
                    if chunk is None:
                        break
                    self._push_vu(chunk)

                    if not self.manual_active and wf is not None:
                        wf.close(); wf = None
                        self._finalise(p, fmt, snd_data, wav_filename, rec_start)
                        snd_data = array('h')
                        self._update_rec_ui(False)

                    if self.manual_active:
                        if wf is None:
                            rec_start    = time.time()
                            wav_filename = self._make_filename()
                            import pyaudio as pa2
                            wf = wave.open(f"{wav_filename}.wav", 'wb')
                            wf.setnchannels(1)
                            wf.setsampwidth(p.get_sample_size(
                                getattr(pa2, FORMAT_STR)))
                            wf.setframerate(RATE)
                            self._update_rec_ui(True, wav_filename)
                            self._log(f"Manual rec: {os.path.basename(wav_filename)}.wav",
                                      color=AMBER)
                        snd_data.extend(chunk)
                        wf.writeframes(chunk.tobytes())
                break   # clean exit
            except RuntimeError as e:
                self._log(f"⚠  {e} — restarting…", color=AMBER)
                self._set_status("Stream stuck – restarting audio…")
                if wf:
                    try: wf.close()
                    except Exception: pass
                    wf = None
                try:
                    stream.stop_stream(); stream.close(); p.terminate()
                except Exception:
                    pass
                time.sleep(1.0)
            finally:
                if wf:
                    try: wf.close()
                    except Exception: pass
                try:
                    stream.stop_stream(); stream.close(); p.terminate()
                except Exception:
                    pass

    def _do_record_session(self, p, stream, fmt, first_chunk):
        snd_data     = array('h', first_chunk)
        rec_start    = time.time()
        last_voice   = rec_start
        wav_filename = self._make_filename()
        meta         = self._get_metadata()

        self._update_rec_ui(True, wav_filename)
        self._log(f"Recording: {os.path.basename(wav_filename)}.wav", color=AMBER)

        tail = self.tail_silence.get()
        while not self.stop_event.is_set():
            chunk = self._read_chunk_with_stuck_detect(stream)
            if chunk is None:
                break
            snd_data.extend(chunk)
            self._push_vu(chunk)
            if max(chunk) > self.vox_threshold.get():
                last_voice = time.time()
            if time.time() > last_voice + tail:
                break

        self._finalise(p, fmt, snd_data, wav_filename, rec_start, meta)
        self._update_rec_ui(False)

    def _finalise(self, p, fmt, snd_data, wav_filename, rec_start, meta=None):
        if not snd_data:
            return
        if self.normalize_audio.get():
            snd_data = self._normalize(snd_data)
        if self.trim_audio.get():
            snd_data = self._trim(snd_data)
        if self.add_silence_pad.get():
            snd_data = self._add_silence(snd_data, 0.5)

        wav_path = f"{wav_filename}.wav"
        import pyaudio as pa
        with wave.open(wav_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(p.get_sample_size(getattr(pa, FORMAT_STR)))
            wf.setframerate(RATE)
            wf.writeframes(pack('<' + ('h' * len(snd_data)), *snd_data))

        duration = time.time() - rec_start
        if meta is None:
            meta = {}
        # Channel name from GUI field takes priority, then from script
        ch = self.channel_name.get().strip()
        if ch:
            meta["channel_name"] = ch
        meta.update({
            "start_time": time.strftime('%Y-%m-%d %H:%M:%S',
                                         time.localtime(rec_start)),
            "end_time":   time.strftime('%Y-%m-%d %H:%M:%S'),
            "duration_s": round(duration, 1),
        })
        json_path = f"{wav_filename}.json"
        with open(json_path, 'w') as jf:
            json.dump(meta, jf, indent=4)

        self.session_count += 1
        self.after(0, lambda: self._session_label.config(
            text=f"Sessions: {self.session_count}"))
        self._log(f"Saved: {os.path.basename(wav_path)} ({duration:.1f}s)", color=GREEN)
        self._log(f"Meta:  {os.path.basename(json_path)}", color=TEXT_DIM)
        self._set_status(f"Last: {os.path.basename(wav_path)}")

    # ═══════════════════════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════════════════════

    def _make_filename(self):
        prefix = self.filename_prefix.get() or "voxrecord"
        ts     = time.strftime("%Y%m%d%H%M%S")
        uid    = uuid.uuid4().hex[:6]
        return os.path.join(self.save_path.get(), f"{prefix}-{ts}-{uid}")

    def _get_metadata(self):
        script = self.meta_script.get().strip()
        if not script:
            return {}
        try:
            result = subprocess.run(
                [script], capture_output=True, text=True, timeout=5)
            raw = result.stdout.strip()
            if raw:
                return json.loads(raw)
        except Exception as e:
            self._log(f"Metadata script error: {e}", color=RED)
        return {}

    def _normalize(self, snd_data):
        mx = max(abs(i) for i in snd_data)
        if mx == 0:
            return snd_data
        t = float(MAXIMUMVOL) / mx
        return array('h', [int(min(MAXIMUMVOL, max(-MAXIMUMVOL, i * t)))
                            for i in snd_data])

    def _trim(self, snd_data):
        thr = self.vox_threshold.get()
        def _trim_one(d):
            started = False
            r = array('h')
            for i in d:
                if not started and abs(i) > thr:
                    started = True
                if started:
                    r.append(i)
            return r
        snd_data = _trim_one(snd_data)
        snd_data.reverse()
        snd_data = _trim_one(snd_data)
        snd_data.reverse()
        return snd_data

    def _add_silence(self, snd_data, secs):
        silence = array('h', [0] * int(secs * RATE))
        return silence + snd_data + silence

    def _update_rec_ui(self, active, filename=""):
        self.recording = active
        if active:
            self.vox_listening = False   # recording trumps waiting state
            self.rec_start_time = time.time()
            fn = os.path.basename(filename) + ".wav" if filename else ""
            self.after(0, lambda: (
                self._rec_label.config(text="REC", fg=RED),
                self._rec_indicator.config(fg=RED),
                self._set_status(f"Recording → {fn}")
            ))
            self._start_timer()
        else:
            # If VOX mode is still running (not stopped), go back to waiting
            if not self.stop_event.is_set() and self.mode_var.get() == "vox":
                self.vox_listening = True
                self._start_waiting_pulse()
            self.after(0, lambda: (
                self._timer_label.config(text="00:00"),
            ))

    def _start_waiting_pulse(self):
        """Pulse the top-right indicator and label green while waiting for VOX trigger."""
        _bright = True

        def _tick():
            nonlocal _bright
            if not self.vox_listening:
                # Restore to idle appearance
                self._rec_label.config(text="IDLE", fg=MUTED)
                self._rec_indicator.config(fg=MUTED)
                return
            if _bright:
                self._rec_label.config(text="WAITING", fg=GREEN)
                self._rec_indicator.config(fg=GREEN)
            else:
                self._rec_label.config(text="WAITING", fg=GREEN_DIM)
                self._rec_indicator.config(fg=GREEN_DIM)
            _bright = not _bright
            self.after(600, _tick)

        self.after(0, _tick)

    def _start_timer(self):
        def _tick():
            if self.recording:
                elapsed = int(time.time() - self.rec_start_time)
                mm, ss  = divmod(elapsed, 60)
                self._timer_label.config(text=f"{mm:02d}:{ss:02d}", fg=RED)
                self.after(500, _tick)
            else:
                self._timer_label.config(fg=TEXT_DIM)
        self.after(500, _tick)

    def _log(self, msg, color=None):
        ts  = time.strftime("%H:%M:%S")
        tag = {GREEN: "green", AMBER: "amber", RED: "red",
               TEXT_DIM: "dim"}.get(color, "normal")
        self.log_queue.put((f"[{ts}] {msg}\n", tag))

    def _set_status(self, msg):
        self.after(0, lambda: self._status_var.set(msg))

    def _start_vu_updater(self):
        def _loop():
            try:
                level = self.vu_queue.get_nowait()
                self._apply_vu_level(level)
            except queue.Empty:
                if self._last_vu_level > 0:
                    self._apply_vu_level(max(0, self._last_vu_level - 0.05))
            self.after(40, _loop)
        self.after(40, _loop)

    def _start_log_updater(self):
        def _loop():
            try:
                while True:
                    msg, tag = self.log_queue.get_nowait()
                    self._log_box.config(state="normal")
                    self._log_box.insert("end", msg, tag)
                    self._log_box.see("end")
                    self._log_box.config(state="disabled")
            except queue.Empty:
                pass
            self.after(100, _loop)
        self.after(100, _loop)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app = VoxRecorderApp()
    app.mainloop()

