import tkinter as tk
from theme import T          # warm eye-comfort colours (see theme.py)
from PIL import ImageTk
from neo_ui import (NeuButton, NeuText, NeuScrollbar, GlassPanel, GlassCard, Backdrop,
                    OnScreenKeyboard, render_glass)   # neumorphic + glass kit (see neo_ui.py)
from tkinter import font as tkfont, filedialog
import subprocess, sys, os, datetime, random, json, csv

# ── Heatmap generation (imported lazily to avoid blocking startup) ─────────────
def _try_generate_heatmap(gaze_pts, out_path, screen_w, screen_h, label):
    """Fire-and-forget heatmap generation in a background thread."""
    import threading
    def _worker():
        try:
            from heatmap_generator import generate_heatmap
            generate_heatmap(gaze_pts, out_path,
                             screen_w=screen_w, screen_h=screen_h,
                             session_label=label)
        except Exception as e:
            print(f"[HeatMap] Experiment heatmap error: {e}")
    threading.Thread(target=_worker, daemon=True).start()

# ── palette ───────────────────────────────────────────────────────────────────
BG      = T("#F5F6F8")
SURFACE = T("#FFFFFF")
BORDER  = T("#DDE1E7")
SEP     = T("#E5E7EB")
TEXT    = T("#1A1D23")
MUTED   = T("#6B7280")
ACCENT  = T("#2563EB")
GREEN   = T("#16A34A")
AMBER   = T("#D97706")
PURPLE  = T("#7C3AED")
DANGER  = T("#DC2626")

# ── font stack (larger for fullscreen) ───────────────────────────────────────
FH  = ("Segoe UI", 15, "bold")   # card heading
FB  = ("Segoe UI", 12)           # body
FS  = ("Segoe UI", 10)           # small / muted
FT  = ("Segoe UI", 28, "bold")   # app title
FM  = ("Consolas", 12)           # mono

# ── auto-start disabled ───────────────────────────────────────────────────────
AUTO_START_DELAY_MS = 1500


def _sep(parent):
    tk.Frame(parent, bg=SEP, height=1).pack(fill="x")


class _Dot:
    """Status dot on the home canvas; answers to .config(fg=...) like the old Label."""
    def __init__(self, color):
        self.color, self.canvas = color, None

    def config(self, **kw):
        if "fg" in kw:
            self.color = kw["fg"]
        if self.canvas is not None:
            try: self.canvas.itemconfigure("status_dot", fill=self.color)
            except Exception: pass
    configure = config


class _Slot:
    """A widget living on the home canvas that still answers to pack()/pack_forget()."""
    def __init__(self, widget):
        self.widget, self.visible, self.canvas, self.item = widget, False, None, None

    def attach(self, canvas, x, y, anchor):
        self.canvas = canvas
        self.item = canvas.create_window(x, y, window=self.widget, anchor=anchor,
                                         state="normal" if self.visible else "hidden")

    def _apply(self):
        if self.canvas is not None and self.item is not None:
            try: self.canvas.itemconfigure(self.item, state="normal" if self.visible else "hidden")
            except Exception: pass

    def pack(self, *a, **k):
        self.visible = True; self._apply()

    def pack_forget(self):
        self.visible = False; self._apply()


class _GlassPrompt:
    """Glass dialog drawn onto the experiment canvas (replaces the old bordered Frame box)."""
    def __init__(self, canvas, bd, cx, cy, title, sub, buttons, tag, fg, dim):
        self.c, self.tag, self.btns = canvas, tag, []
        w, h = 800, 300
        bd.draw_glass(cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2, r=32, tags=tag)
        canvas.create_text(cx, cy - 78, text=title, fill=fg, font=("Segoe UI", 20, "bold"), tags=tag)
        canvas.create_text(cx, cy - 36, text=sub, fill=dim, font=("Segoe UI", 12), tags=tag)
        for text, cmd, variant in buttons:
            self.btns.append(NeuButton(canvas, text=text, command=cmd, variant=variant,
                                       font=("Segoe UI", 15, "bold"), padx=26, pady=12))
        for b in self.btns:
            b.update_idletasks()
        gap = 18
        total = sum(b.winfo_reqwidth() for b in self.btns) + gap * (len(self.btns) - 1)
        x = cx - total // 2
        for b in self.btns:
            canvas.create_window(x, cy + 50, window=b, anchor="w", tags=tag)
            x += b.winfo_reqwidth() + gap

    def destroy(self):
        for b in self.btns:
            try: b.destroy()
            except Exception: pass
        try: self.c.delete(self.tag)
        except Exception: pass


# ─────────────────────────────────────────────────────────────────────────────
#  LAUNCHER
# ─────────────────────────────────────────────────────────────────────────────
class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.attributes('-alpha', 0.0)  # Make completely transparent to prevent flashing
        self.withdraw()  # Hide UI initially
        
        self.configure(bg=BG)

        # ── Fullscreen ────────────────────────────────────────────────────────
        self.resizable(True, True)
        self.attributes('-fullscreen', True)
        self.bind("<Escape>", lambda e: self.attributes('-fullscreen', False))
        self.bind("<F11>", lambda e: self.attributes('-fullscreen', not self.attributes('-fullscreen')))
        self._proc = None
        self._build()
        self._tick()

        # ── Status bar initial state ──────────────────────────────────────────
        self._sv.set("Tracker starting...")
        
        # ── Auto-start tracker immediately ─────────────────────────────────────
        self.after(100, self._start_tracker)


    def _build(self):
        # ── glass home screen: one canvas, soft colour backdrop, frosted cards ─────
        self._usage_v = tk.StringVar(value="Total Usage: 0h 0m")
        self._clock_v = tk.StringVar()
        self._sv      = tk.StringVar(value="  Initialising …")
        self._dot     = _Dot(BORDER)

        c = tk.Canvas(self, highlightthickness=0, bd=0)
        c.place(x=0, y=0, relwidth=1, relheight=1)
        self._home  = c
        self._bdrop = Backdrop(c, base=BG)

        self.modules = [
            ("Emergency Communication", "Preset & custom emergency phrase alerts to contact number", DANGER, self._launch_emergency, "🚨"),
            ("Eye Tracker", "Calibrate & start gaze tracking",  GREEN, self._start_tracker, "👁"),
            ("Notepad","Text editor  ·  save / open files", AMBER,  lambda: NotepadWindow(self), "📝"),
            ("Text-Entry Experiment", "Gaze-based text entry  ·  measure typing speed & accuracy", PURPLE, self._launch_text_experiment, "⌨"),
        ]
        self.cards = [GlassCard(c, n, d, col, cmd, icon=ic, width=420, height=190,
                                title_font=("Segoe UI", 18, "bold"), sub_font=("Segoe UI", 12))
                      for (n, d, col, cmd, ic) in self.modules]

        self._stop_btn = _Slot(NeuButton(c, text="Stop Tracker", command=self._stop, variant="danger",
                                         font=("Segoe UI", 15, "bold"), padx=22, pady=8))

        for var, tag in ((self._usage_v, "usage_txt"), (self._clock_v, "clock_txt"), (self._sv, "status_txt")):
            var.trace_add("write", lambda *_a, v=var, t=tag: self._set_item_text(t, v.get()))

        c.bind("<<NeoBackdropChanged>>", lambda e: self._layout_home())
        self.bind("<Escape>", lambda e: self.destroy())
        self._refresh_stats()

    def _set_item_text(self, tag, text):
        try: self._home.itemconfigure(tag, text=text)
        except Exception: pass

    def _layout_home(self):
        c = self._home
        W, H = c.winfo_width(), c.winfo_height()
        if W < 400 or H < 400:
            return
        c.delete("all")
        self._bdrop.draw()
        bd, m = self._bdrop, 40
        # header bar
        hy1, hy2 = 28, 118
        bd.draw_glass(m, hy1, W - m, hy2, r=30)
        hc = (hy1 + hy2) // 2
        c.create_oval(m + 36, hc - 7, m + 50, hc + 7, fill=ACCENT, outline="")
        c.create_text(m + 66, hc, anchor="w", text="Group 10  ·  Mini Project", fill=TEXT, font=("Segoe UI", 15, "bold"))
        c.create_text(W - m - 36, hc - 14, anchor="e", text=self._usage_v.get(), fill=ACCENT,
                      font=FM, tags="usage_txt")
        c.create_text(W - m - 36, hc + 14, anchor="e", text=self._clock_v.get(), fill=MUTED,
                      font=FM, tags="clock_txt")
        # status bar
        sy1, sy2 = H - 108, H - 28
        bd.draw_glass(m, sy1, W - m, sy2, r=30)
        sc = (sy1 + sy2) // 2
        c.create_oval(m + 34, sc - 8, m + 50, sc + 8, fill=self._dot.color, outline="", tags="status_dot")
        self._dot.canvas = c
        c.create_text(m + 64, sc, anchor="w", text=self._sv.get(), fill=MUTED, font=FB, tags="status_txt")
        self._stop_btn.attach(c, W - m - 30, sc, "e")
        # 2 x 2 glass cards, centred between the bars
        gap = 36
        cw = int(min(560, (W - 2 * m - gap - 80) / 2))
        ch = int(min(230, (sy1 - hy2 - 3 * gap) / 2))
        gx = (W - (2 * cw + gap)) // 2
        gy = hy2 + (sy1 - hy2 - (2 * ch + gap)) // 2
        for i, card in enumerate(self.cards):
            x = gx + (i % 2) * (cw + gap)
            y = gy + (i // 2) * (ch + gap)
            c.create_window(x, y, window=card, width=cw, height=ch, anchor="nw")

    # ── stats & reports ───────────────────────────────────────────────────────
    def _refresh_stats(self):
        stats_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage_stats.json")
        try:
            if os.path.exists(stats_file):
                with open(stats_file, "r") as f:
                    stats = json.load(f)
                sec = stats.get("total_seconds", 0)
                self._usage_v.set(f"Total Usage: {int(sec//3600)}h {int((sec%3600)//60)}m")
            else:
                self._usage_v.set("Total Usage: 0h 0m")
        except Exception:
            pass

    def _show_report(self):
        report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_report.png")
        if os.path.exists(report_path):
            try:
                if sys.platform == "win32":
                    os.startfile(report_path)
                else:
                    opener = "open" if sys.platform == "darwin" else "xdg-open"
                    subprocess.call([opener, report_path])
                self._sv.set("  Opening session report …")
            except Exception as e:
                self._sv.set(f"  Error opening report: {e}")
        else:
            self._sv.set("  No session report found. Run tracker first.")

    def _launch_external(self, app_name):
        try:
            if sys.platform == "win32":
                os.startfile(app_name)
            else:
                subprocess.Popen([app_name])
            self._flash(f"Launching {app_name}...")
        except Exception as e:
            self._flash(f"Failed to launch {app_name}")
            print(f"[WARN] Could not launch {app_name}: {e}")

    def _launch_emergency(self):
        self._flash("Opening Emergency Communication…")
        from emergency import EmergencyWindow
        EmergencyWindow(self)

    def _launch_text_experiment(self):
        self._flash("Opening Text-Entry Experiment…")
        TextEntryExperiment(self)

    # ── tracker control ───────────────────────────────────────────────────────
    def _start_tracker(self):
        if self._proc and self._proc.poll() is None:
            self._flash("Tracker is already running...")
            return
            
        self.withdraw()  # Hide UI during calibration
        
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "_run.py")
        flag_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calib_done.flag")
        
        if os.path.exists(flag_file):
            try: os.remove(flag_file)
            except: pass

        # A leftover rest-pause flag would keep the tracker frozen on "TRACKER PAUSED"
        stale_pause = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker_paused.flag")
        if os.path.exists(stale_pause):
            try: os.remove(stale_pause)
            except: pass

        with open(script, "w") as f:
            f.write("from tracker import AttentionTracker\n"
                    "import os\n"
                    "t = AttentionTracker()\n"
                    "t.calibrate(duration=3)\n"
                    "with open('calib_done.flag', 'w') as flag: flag.write('1')\n"
                    "t.run()\n")
                    
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        self._proc = subprocess.Popen(
            [sys.executable, script],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            startupinfo=startupinfo)
        self._dot.config(fg=GREEN)
        self._sv.set("Tracker running  properly ESC = stop")
        self._stop_btn.pack(side="right")
        self._poll()
        self._wait_for_calibration()

    def _restore_ui(self):
        self.attributes('-alpha', 1.0)
        self.deiconify()
        self.attributes('-fullscreen', True)
        self.lift()
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))
        self.focus_force()

    def _wait_for_calibration(self):
        flag_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calib_done.flag")
        # Check if tracker process ended prematurely
        if self._proc and self._proc.poll() is not None:
            self._restore_ui()
            return

        if os.path.exists(flag_file):
            try:
                os.remove(flag_file)
            except:
                pass
            self._restore_ui()
        else:
            self.after(500, self._wait_for_calibration)

    def _stop(self):
        if self._proc: self._proc.terminate()
        self._dot.config(fg=BORDER)
        self._sv.set("  Tracker is stopped")
        self._refresh_stats()   # Update stats immediately after stopping
        self._stop_btn.pack_forget()

    def _poll(self):
        if self._proc and self._proc.poll() is not None:
            self._dot.config(fg=BORDER)
            self._sv.set("  Tracker finished")
            self._stop_btn.pack_forget()
            self._refresh_stats()   # Update stats after session ends
        else:
            self.after(1000, self._poll)

    def _flash(self, msg):
        old = self._sv.get()
        self._sv.set(f"  {msg}")
        self.after(3000, lambda: self._sv.set(old))

    def _tick(self):
        self._clock_v.set(datetime.datetime.now().strftime("%H:%M:%S"))
        self.after(1000, self._tick)

    def destroy(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        try:
            _pf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker_paused.flag")
            if os.path.exists(_pf): os.remove(_pf)
        except Exception:
            pass
        super().destroy()


# ─────────────────────────────────────────────────────────────────────────────
#  NOTEPAD  — with integrated on-screen virtual keyboard
# ─────────────────────────────────────────────────────────────────────────────
class NotepadWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Notepad")
        self.configure(bg=BG)
        self.state("zoomed")
        self._path = None
        self._kb_win = None          # keep reference to keyboard window
        self._build()
        # ── Auto-open virtual keyboard on launch ──────────────────────────────
        self.after(300, self._open_keyboard)

    def _build(self):
        menu = tk.Menu(self, bg=SURFACE, fg=TEXT,
                       activebackground=ACCENT, activeforeground=SURFACE,
                       relief="flat", tearoff=0)
        self.config(menu=menu)

        fm = tk.Menu(menu, bg=SURFACE, fg=TEXT,
                     activebackground=ACCENT, activeforeground=SURFACE, tearoff=0)
        menu.add_cascade(label="File", menu=fm)
        fm.add_command(label="Open Keyboard", command=self._open_keyboard, accelerator="Ctrl+Shift+K")
        fm.add_separator()
        fm.add_command(label="Exit", command=self.destroy)

        # glass toolbar
        panel = GlassPanel(self, padx=14, pady=6)
        panel.pack(fill="x", padx=18, pady=(14, 4))
        tb, bb = panel.body, panel.body_bg

        def tbtn(text, cmd, fg=TEXT, bold=False):
            f = ("Segoe UI", 11, "bold") if bold else ("Segoe UI", 11)
            NeuButton(tb, text=text, command=cmd, fg=fg, font=f, padx=14, pady=6,
                      radius=12, depth=3).pack(side="left", padx=3)

        tbtn("Alphabetical Keyboard", lambda: self._open_keyboard("alpha"), fg=PURPLE, bold=True)
        tbtn("Normal Keyboard", lambda: self._open_keyboard("normal"), fg=PURPLE, bold=True)
        tbtn("Cluster Keyboard", lambda: self._open_keyboard("cluster"), fg=PURPLE, bold=True)

        tk.Label(tb, text="|", bg=bb, fg=BORDER, font=FB).pack(side="left", padx=8)
        tk.Label(tb, text="Size", bg=bb, fg=MUTED, font=FS).pack(side="left")
        self._fsize = tk.IntVar(value=25)
        tk.Spinbox(tb, from_=8, to=32, textvariable=self._fsize, width=3,
                   relief="flat", bg=BG, fg=TEXT, font=FM, buttonbackground=BG,
                   command=self._resize).pack(side="left", padx=8)

        self._wrap_v = tk.BooleanVar(value=True)
        tk.Checkbutton(tb, text="Wrap", variable=self._wrap_v,
                       command=self._toggle_wrap, bg=bb, fg=MUTED,
                       activebackground=bb, activeforeground=MUTED, selectcolor=BG,
                       font=FS).pack(side="left")

        NeuButton(tb, text="Stop Tracker", command=self.master._stop, variant="danger",
                  font=("Segoe UI", 11, "bold"), padx=14, pady=6, radius=12,
                  depth=3).pack(side="right", padx=6)

        self._sv = tk.StringVar(value="Ready")
        tk.Label(tb, textvariable=self._sv, bg=bb, fg=MUTED,
                 font=FS).pack(side="right", padx=12)

        frame = tk.Frame(self, bg=BG)
        frame.pack(fill="both", expand=True)

        text_wrapper = tk.Frame(frame, bg=BG)
        text_wrapper.place(relx=0, rely=0, relwidth=1, relheight=0.33)

        self.kb_wrapper = tk.Frame(frame, bg=BG)
        self.kb_wrapper.place(relx=0, rely=0.33, relwidth=1, relheight=0.67)

        self._tfont = tkfont.Font(family="Consolas", size=16)
        vsb = NeuScrollbar(text_wrapper)
        vsb.pack(side="right", fill="y", padx=(0, 18), pady=14)
        self._txt = NeuText(
            text_wrapper, fg=TEXT,
            insertbackground=ACCENT,
            selectbackground=T("#BFDBFE"), selectforeground=TEXT,
            font=self._tfont, wrap="word", undo=True,
            padx=22, pady=14, spacing1=3, spacing3=3)
        vsb.configure(command=self._txt.yview)
        self._txt.configure(yscrollcommand=vsb.set)
        self._txt.pack(fill="both", expand=True, padx=(18, 0), pady=(8, 8))
        self._txt.bind("<KeyRelease>", self._update_sv)

        self.bind("<Control-s>",       lambda e: self._save())
        self.bind("<Control-S>",       lambda e: self._save_as())
        self.bind("<Control-n>",       lambda e: self._new())
        self.bind("<Control-o>",       lambda e: self._open())
        self.bind("<Control-K>",       lambda e: self._open_keyboard())

    # ── keyboard integration ──────────────────────────────────────────────────
    def _open_keyboard(self, layout="normal"):
        if hasattr(self, '_kb_win') and self._kb_win is not None:
            try:
                if self._kb_win.winfo_exists():
                    self._kb_win.set_layout(layout)
                    return
            except Exception:
                pass
            self._kb_win = None

        self._kb_win = OnScreenKeyboard(self.kb_wrapper, self._txt, layout=layout, notepad_app=self)
        self._kb_win.pack(fill="both", expand=True)

    def insert_text(self, text):
        self._txt.insert("end", text)
        self._update_sv()
        self.lift(); self.focus_force()

    def _new(self):
        self._txt.delete("1.0","end")
        self._path = None
        self.title("Notepad  —  untitled")
        self._sv.set("New file")

    def _open(self):
        p = filedialog.askopenfilename(
            filetypes=[("Text","*.txt"),("All","*.*")])
        if not p: return
        with open(p, encoding="utf-8") as f:
            self._txt.delete("1.0","end")
            self._txt.insert("1.0", f.read())
        self._path = p
        self.title(f"Notepad  —  {os.path.basename(p)}")
        self._update_sv()

    def _save(self):
        if not self._path:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self._path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"typed_text_{ts}.txt")
        with open(self._path,"w",encoding="utf-8") as f:
            f.write(self._txt.get("1.0","end").rstrip())
        self._sv.set(f"Saved  —  {os.path.basename(self._path)}")
        self.title(f"Notepad  —  {os.path.basename(self._path)}")

    def _save_as(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        p  = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"typed_text_{ts}.txt",
            filetypes=[("Text","*.txt"),("All","*.*")])
        if not p: return
        self._path = p; self._save()
        self.title(f"Notepad  —  {os.path.basename(p)}")

    def _toggle_wrap(self):
        self._txt.configure(wrap="word" if self._wrap_v.get() else "none")

    def _resize(self):
        self._tfont.configure(size=self._fsize.get())

    def _update_sv(self, _=None):
        c = self._txt.get("1.0","end").strip()
        self._sv.set(f"{len(c)} chars  ·  {len(c.split()) if c else 0} words")


# The on-screen keyboard now lives in neo_ui.py (OnScreenKeyboard = NeoKeyboard).
# 'Delete' (clear everything) moved to an isolated top-right 'Clear all' key with a 2-tap confirm.

# ─────────────────────────────────────────────────────────────────────────────
#  CUSTOM WEBVIEW2 WIDGET — to bypass E_ACCESSDENIED by using a custom user data folder
# ─────────────────────────────────────────────────────────────────────────────
try:
    import clr
    import ctypes
    from uuid import uuid4
    from webview.window import Window
    from webview.platforms.edgechromium import EdgeChrome
    
    _webview_windows = []
    
    class CustomWebView2(tk.Frame):
        def __init__(self, parent, width: int, height: int, url: str = '', **kw):
            tk.Frame.__init__(self, parent, width=width, height=height, **kw)
            
            # Use a writable directory in AppData to avoid E_ACCESSDENIED
            cache_dir = os.path.join(os.getenv('APPDATA', os.path.expanduser('~')), 'SSDB_ChatBox_WebView2')
            os.makedirs(cache_dir, exist_ok=True)
            
            clr.AddReference('System.Windows.Forms')
            from System.Windows.Forms import Control
            
            control = Control()
            uid = 'master' if len(_webview_windows) == 0 else 'child_' + uuid4().hex[:8]
            window = Window(uid, str(id(self)), url=None, html=None, js_api=None, width=width, height=height, x=None, y=None,
                          resizable=True, fullscreen=False, min_size=(200, 100), hidden=False,
                          frameless=False, easy_drag=True,
                          minimized=False, on_top=False, confirm_close=False, background_color=T('#FFFFFF'),
                          transparent=False, text_select=True, localization=None,
                          zoomable=True, draggable=True, vibrancy=False)
            self.window = window
            
            self.web_view = EdgeChrome(control, window, cache_dir)
            self.control = control
            if hasattr(self.web_view, 'web_view'):
                self.web = self.web_view.web_view
            else:
                self.web = self.web_view.webview
            _webview_windows.append(window)
            self.width = width
            self.height = height
            self.parent = parent
            self.chwnd = int(str(self.control.Handle))
            
            user32 = ctypes.windll.user32
            user32.SetParent(self.chwnd, self.winfo_id())
            user32.MoveWindow(self.chwnd, 0, 0, width, height, True)
            self.loaded = window.events.loaded
            
            self.bind('<Destroy>', lambda event: self.web.Dispose())
            self.bind('<Configure>', self.__resize_webview)
            self.newwindow = None
            
            if url != '':
                self.load_url(url)
            self.core = None
            self.web.CoreWebView2InitializationCompleted += self.__load_core

        def __resize_webview(self, event):
            ctypes.windll.user32.MoveWindow(self.chwnd, 0, 0, self.winfo_width(), self.winfo_height(), True)

        def __load_core(self, sender, _):
            self.core = sender.CoreWebView2
            self.core.NewWindowRequested -= self.web_view.on_new_window_request
            if self.newwindow != None:
                self.core.NewWindowRequested += self.newwindow
            settings = sender.CoreWebView2.Settings
            settings.AreDefaultContextMenusEnabled = True
            settings.AreDevToolsEnabled = True

        def load_url(self, url):
            self.web_view.load_url(url)

        def reload(self):
            if self.core:
                self.core.Reload()

        def event_new_window(self, command=None):
            self.newwindow = command
except Exception as e:
    import traceback
    traceback.print_exc()
    CustomWebView2 = None


# ─────────────────────────────────────────────────────────────────────────────
#  CHATTING WINDOW — with integrated WebView2 browser
# ─────────────────────────────────────────────────────────────────────────────
class ChatWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Chatting - SSDB Real-Time Chat")
        self.geometry("1100x850")
        self.configure(bg=SURFACE)
        self.state("zoomed")
        
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Header
        self.hdr = tk.Frame(self, bg=SURFACE, padx=24, pady=12)
        self.hdr.pack(fill="x")
        
        tk.Label(self.hdr, text="SSDB ChatBox", bg=SURFACE, fg=TEXT, font=("Segoe UI", 14, "bold")).pack(side="left")
        
        self.status_lbl = tk.Label(self.hdr, text="Loading secure chat session...", bg=SURFACE, fg=MUTED, font=FS)
        self.status_lbl.pack(side="right", padx=10)
        
        _sep(self)
        
        # Frame for webview
        self.web_frame = tk.Frame(self, bg=BG)
        self.web_frame.pack(fill="both", expand=True)
        
        self.after(100, self._load_webview)
        
    def _load_webview(self):
        try:
            if CustomWebView2 is None:
                raise ImportError("Required webview libraries or runtime not available.")
            
            # Create CustomWebView2 widget inside the web_frame
            self.webview = CustomWebView2(self.web_frame, 1100, 800, url="https://test-real-mk6w.onrender.com")
            self.webview.pack(fill="both", expand=True)
            self.status_lbl.config(text="Connected", fg=GREEN)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_lbl.config(text="Connection Error", fg=DANGER)
            self._show_fallback_error(e)
            
    def _show_fallback_error(self, error):
        # Clear the web_frame and show a friendly error
        for widget in self.web_frame.winfo_children():
            widget.destroy()
            
        err_container = tk.Frame(self.web_frame, bg=BG, padx=40, pady=40)
        err_container.place(relx=0.5, rely=0.5, anchor="center")
        
        tk.Label(err_container, text="Could not load Chatting UI", bg=BG, fg=DANGER, font=("Segoe UI", 16, "bold")).pack(pady=(0, 10))
        
        msg = (
            "The 'tkwebview2' and 'pywebview' libraries are required to embed the chat interface.\n\n"
            "If you see this error, please make sure they are installed and you have the WebView2 runtime.\n"
            "Otherwise, you can open the chatting website in your external browser instead."
        )
        tk.Label(err_container, text=msg, bg=BG, fg=TEXT, font=FB, justify="center", wraplength=500).pack(pady=10)
        
        btn_frame = tk.Frame(err_container, bg=BG)
        btn_frame.pack(pady=20)
        
        # Button to open in external browser
        tk.Button(
            btn_frame, text="Open in Browser", command=self._open_external,
            bg=ACCENT, fg=SURFACE, activebackground=ACCENT, activeforeground=SURFACE,
            relief="flat", font=("Segoe UI", 11, "bold"), padx=15, pady=8, cursor="hand2"
        ).pack(side="left", padx=10)
        
        # Button to retry loading
        tk.Button(
            btn_frame, text="Retry", command=self._retry_load,
            bg=SURFACE, fg=TEXT, activebackground=BG, activeforeground=TEXT,
            relief="flat", highlightbackground=BORDER, highlightthickness=1,
            font=("Segoe UI", 11), padx=15, pady=8, cursor="hand2"
        ).pack(side="left", padx=10)
        
    def _open_external(self):
        import webbrowser
        webbrowser.open("https://test-real-mk6w.onrender.com")
        self.destroy()
        
    def _retry_load(self):
        for widget in self.web_frame.winfo_children():
            widget.destroy()
        self.status_lbl.config(text="Retrying connection...", fg=MUTED)
        self.after(500, self._load_webview)
        
    def _on_close(self):
        # Explicitly destroy the webview to free resources
        if hasattr(self, 'webview') and self.webview is not None:
            try:
                self.webview.web.Dispose()
            except:
                pass
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
#  EMBEDDED BROWSER WINDOW — with back, forward, reload, and search/address bar
# ─────────────────────────────────────────────────────────────────────────────
class BrowserWindow(tk.Toplevel):
    def __init__(self, master, title, url):
        super().__init__(master)
        self.title(title)
        self.geometry("1200x850")
        self.configure(bg=SURFACE)
        self.state("zoomed")
        
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Header
        self.hdr = tk.Frame(self, bg=SURFACE, padx=24, pady=8)
        self.hdr.pack(fill="x")
        
        # Left side: Title + Navigation buttons
        tk.Label(self.hdr, text=title, bg=SURFACE, fg=TEXT, font=("Segoe UI", 14, "bold")).pack(side="left", padx=(0, 15))
        
        btn_font = ("Segoe UI", 11, "bold")
        self.back_btn = tk.Button(
            self.hdr, text="◀ Back", command=self._go_back,
            bg=SURFACE, fg=ACCENT, activebackground=BG, activeforeground=ACCENT,
            relief="flat", font=btn_font, padx=8, pady=4, cursor="hand2"
        )
        self.back_btn.pack(side="left", padx=2)
        
        self.fwd_btn = tk.Button(
            self.hdr, text="Forward ▶", command=self._go_forward,
            bg=SURFACE, fg=ACCENT, activebackground=BG, activeforeground=ACCENT,
            relief="flat", font=btn_font, padx=8, pady=4, cursor="hand2"
        )
        self.fwd_btn.pack(side="left", padx=2)
        
        self.reload_btn = tk.Button(
            self.hdr, text="Reload ⟳", command=self._reload,
            bg=SURFACE, fg=MUTED, activebackground=BG, activeforeground=TEXT,
            relief="flat", font=btn_font, padx=8, pady=4, cursor="hand2"
        )
        self.reload_btn.pack(side="left", padx=2)
        
        # Address bar (URL entry)
        self.url_var = tk.StringVar(value=url)
        self.url_entry = tk.Entry(
            self.hdr, textvariable=self.url_var, font=("Segoe UI", 11),
            bg=BG, fg=TEXT, relief="flat", highlightbackground=BORDER, highlightthickness=1
        )
        self.url_entry.pack(side="left", fill="x", expand=True, padx=15, pady=4)
        self.url_entry.bind("<Return>", self._navigate_to_entry)
        
        # Right side: Status label
        self.status_lbl = tk.Label(self.hdr, text="Loading secure browser session...", bg=SURFACE, fg=MUTED, font=FS)
        self.status_lbl.pack(side="right", padx=10)
        
        _sep(self)
        
        # Frame for webview
        self.web_frame = tk.Frame(self, bg=BG)
        self.web_frame.pack(fill="both", expand=True)
        
        self.initial_url = url
        self.after(100, self._load_webview)
        
    def _load_webview(self):
        try:
            if CustomWebView2 is None:
                raise ImportError("Required webview libraries or runtime not available.")
            
            # Create CustomWebView2 widget inside the web_frame
            self.webview = CustomWebView2(self.web_frame, 1200, 800, url=self.initial_url)
            self.webview.pack(fill="both", expand=True)
            self.status_lbl.config(text="Connected", fg=GREEN)
            
            # Start loop to update address bar URL as navigation occurs
            self.after(1000, self._check_url_loop)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_lbl.config(text="Connection Error", fg=DANGER)
            self._show_fallback_error(e)
            
    def _check_url_loop(self):
        if hasattr(self, 'webview') and self.webview is not None:
            try:
                if hasattr(self.webview, 'web') and self.webview.web is not None:
                    current_uri = self.webview.web.Source
                    if current_uri is not None:
                        current_url = str(current_uri)
                        # Avoid updating if user is actively editing (has focus)
                        if self.focus_get() != self.url_entry and current_url != self.url_var.get():
                            self.url_var.set(current_url)
            except:
                pass
        try:
            if self.winfo_exists():
                self.after(1000, self._check_url_loop)
        except:
            pass
            
    def _navigate_to_entry(self, event=None):
        url = self.url_var.get().strip()
        if not url:
            return
        
        # Handle search vs URL
        if not (url.startswith("http://") or url.startswith("https://")):
            if "." in url and " " not in url:
                url = "https://" + url
            else:
                import urllib.parse
                query = urllib.parse.quote(url)
                url = f"https://www.google.com/search?q={query}"
        
        self.url_var.set(url)
        if hasattr(self, 'webview') and self.webview is not None:
            try:
                self.webview.load_url(url)
            except Exception as e:
                print("[ERROR] Navigation failed:", e)
                
    def _go_back(self):
        if hasattr(self, 'webview') and self.webview is not None:
            try:
                if hasattr(self.webview, 'web') and self.webview.web is not None:
                    self.webview.web.GoBack()
            except Exception as e:
                print("[ERROR] GoBack failed:", e)
                
    def _go_forward(self):
        if hasattr(self, 'webview') and self.webview is not None:
            try:
                if hasattr(self.webview, 'web') and self.webview.web is not None:
                    self.webview.web.GoForward()
            except Exception as e:
                print("[ERROR] GoForward failed:", e)
                
    def _reload(self):
        if hasattr(self, 'webview') and self.webview is not None:
            try:
                self.webview.reload()
            except Exception as e:
                print("[ERROR] Reload failed:", e)
                
    def _show_fallback_error(self, error):
        for widget in self.web_frame.winfo_children():
            widget.destroy()
            
        err_container = tk.Frame(self.web_frame, bg=BG, padx=40, pady=40)
        err_container.place(relx=0.5, rely=0.5, anchor="center")
        
        tk.Label(err_container, text=f"Could not load {self.title()}", bg=BG, fg=DANGER, font=("Segoe UI", 16, "bold")).pack(pady=(0, 10))
        
        msg = (
            "The 'tkwebview2' and 'pywebview' libraries are required to embed the browser interface.\n\n"
            "If you see this error, please make sure they are installed and you have the WebView2 runtime.\n"
            "Otherwise, you can open the website in your external browser instead."
        )
        tk.Label(err_container, text=msg, bg=BG, fg=TEXT, font=FB, justify="center", wraplength=500).pack(pady=10)
        
        btn_frame = tk.Frame(err_container, bg=BG)
        btn_frame.pack(pady=20)
        
        tk.Button(
            btn_frame, text="Open in Browser", command=self._open_external,
            bg=ACCENT, fg=SURFACE, activebackground=ACCENT, activeforeground=SURFACE,
            relief="flat", font=("Segoe UI", 11, "bold"), padx=15, pady=8, cursor="hand2"
        ).pack(side="left", padx=10)
        
        tk.Button(
            btn_frame, text="Retry", command=self._retry_load,
            bg=SURFACE, fg=TEXT, activebackground=BG, activeforeground=TEXT,
            relief="flat", highlightbackground=BORDER, highlightthickness=1,
            font=("Segoe UI", 11), padx=15, pady=8, cursor="hand2"
        ).pack(side="left", padx=10)
        
    def _open_external(self):
        import webbrowser
        webbrowser.open(self.url_var.get())
        self.destroy()
        
    def _retry_load(self):
        for widget in self.web_frame.winfo_children():
            widget.destroy()
        self.status_lbl.config(text="Retrying connection...", fg=MUTED)
        self.after(500, self._load_webview)
        
    def _on_close(self):
        if hasattr(self, 'webview') and self.webview is not None:
            try:
                self.webview.web.Dispose()
            except:
                pass
        self.destroy()





#Testing part pore changes hoibo eliga  seperate koira rakhsi #


# ─────────────────────────────────────────────────────────────────────────────
#  TEXT-ENTRY EXPERIMENT
# ─────────────────────────────────────────────────────────────────────────────
class TextEntryExperiment(tk.Toplevel):
   

    # ── Test stimuli — 20 research phrases ────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────
    # ── FIXED STIMULUS SETS — 15 stimuli per session ─────────────────────────
    # Words   : 10 common vocabulary words
    # Phrases : 5 pangrams / test sentences
    # ─────────────────────────────────────────────────────────────────────────
    ALL_PHRASES = [
        "The quick brown fox jumps over the lazy dog.",          # long
        "I agree with you",              # short
        "a little encouragement is needed",                 # medium
        "I would like to go home",
        "the computer is running slowly", #long 
    ]
    ALL_WORDS = [
        "help", "food", "sleep", "Doctor", "Medicine", "Water", "Pain", "Uncomfortable", "family", "Friends",
    ]
    TRIALS_PER_SESSION = 15  # 10 words + 5 phrases

    MEMORIZE_SECS = 15                     # overt: memorization window (15 seconds)

    # ── Experiment colours (plain white theme) ──────────────────────────────
    _C_BG  = T("#FFFFFF")   # white background
    _C_FG  = T("#1A1D23")   # dark text
    _C_ACC = T("#2563EB")   # blue accent  (overt)
    _C_BLU = T("#2563EB")   # blue accent  (covert)
    _C_PUR = T("#7C3AED")   # purple accent (random mode)
    _C_DIM = T("#6B7280")   # muted gray
    _C_FIX = T("#000000")   # black fixation cross
    _C_GRN = T("#16A34A")

    # ── Fonts ─────────────────────────────────────────────────────────────────
    _F_TITLE = ("Segoe UI", 32, "bold")
    _F_HEAD  = ("Segoe UI", 22, "bold")
    _F_STIM  = ("Segoe UI", 36, "bold")   # word/sentence display
    _F_BODY  = ("Segoe UI", 15)
    _F_SMALL = ("Segoe UI", 12)
    _F_FIX   = ("Segoe UI", 120, "bold")

    # ── Per-method instruction text ───────────────────────────────────────────
    _OVERT_INSTR = (
        "Overt Method — Instructions",
        (
            "A word or sentence will appear on screen.\n\n"
            "• You have 15 seconds to memorize it carefully.\n"
            "• After the timer, the word will disappear.\n"
            "• Type what you remember using the gaze keyboard.\n"
            "• Press Save & Next when done.\n\n"
            "Look at the fixation cross  +  before each trial.\n"
            "Press  Esc  at any time to abort."
        )
    )
    _COVERT_INSTR = (
        "Covert Method — Instructions",
        (
            "A word or sentence will remain visible on screen.\n\n"
            "• The word / sentence stays visible the whole time.\n"
            "• Type exactly what you see using the gaze keyboard.\n"
            "• Press Save & Next when done.\n\n"
            "Look at the fixation cross  +  before each trial.\n"
            "Press  Esc  at any time to abort."
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    def __init__(self, master):
        super().__init__(master)
        self.title("Text-Entry Experiment")
        self.configure(bg=self._C_BG)
        self.attributes("-fullscreen", True)
        self.bind("<Escape>", lambda e: (self.attributes("-fullscreen", False), self.destroy()))

        self._method            = None   # "overt" or "covert"
        self._sequence_mode     = None   # "fixed" or "random"
        self._keyboard_layout   = "normal"  # "normal", "alpha", or "cluster"
        self._idx               = 0
        self._responses         = []
        self._stimuli           = []     # list of words and phrases for the session
        self._participant_name  = ""     # entered on the name screen
        self._after_id          = None
        self._typing_frame      = None
        # ── Memorize-phase extras (skip button + head-pose beep) ───────────────
        self._mem_prompt_open   = False
        self._mem_resume_secs   = None
        self._mem_skipped       = False
        self._mem_skip_btn      = None
        self._mem_skip_box      = None
        self._pose_after_id     = None
        self._pose_last_beep    = 0.0
        # ── Per-trial keystroke tracking ───────────────────────────────────────
        self._trial_start_time  = None
        self._spacebar_count    = 0
        self._backspace_count   = 0
        self._first_key_pressed = False
        self._prev_typed_text   = ""

        # Canvas used by display-only phases
        self._canvas = tk.Canvas(self, bg=self._C_BG, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)
        self._bd = Backdrop(self._canvas, base=self._C_BG)   # soft glass backdrop (see neo_ui.py)

        # ── Heatmap tracking ───────────────────────────────────────────────────
        self._exp_start_time  = None   # datetime when typing phase begins
        self._gaze_csv_path   = None   # path to the live gaze log CSV

        self._show_name_entry()

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _cancel_after(self):
        if self._after_id:
            try: self.after_cancel(self._after_id)
            except Exception: pass
            self._after_id = None

    def _use_canvas(self):
        """Show canvas, destroy any typing frame."""
        if self._typing_frame:
            try: self._typing_frame.destroy()
            except Exception: pass
            self._typing_frame = None
        self._canvas.pack(fill="both", expand=True)

    def _use_frame(self):
        """Hide canvas, return a fresh typing frame."""
        self._cancel_after()
        self._stop_memorize_extras()
        self._canvas.pack_forget()
        self._canvas.delete("all")
        self._bd.draw()
        if self._typing_frame:
            try: self._typing_frame.destroy()
            except Exception: pass
        f = tk.Frame(self, bg=self._C_BG)
        f.pack(fill="both", expand=True)
        self._typing_frame = f
        return f

    def _clear(self):
        self._cancel_after()
        self._destroy_rest_widgets()
        self._stop_memorize_extras()
        self._canvas.delete("all")
        self._bd.draw()

    def _reset_trial_tracking(self):
        """Reset per-trial keystroke counters before each typing phase."""
        self._trial_start_time  = None
        self._spacebar_count    = 0
        self._backspace_count   = 0
        self._first_key_pressed = False
        self._prev_typed_text   = ""
        self._keystroke_log     = []   # [(char, rel_sec), ...]

    def _cx(self): return self._canvas.winfo_width()  // 2 or self.winfo_screenwidth()  // 2
    def _cy(self): return self._canvas.winfo_height() // 2 or self.winfo_screenheight() // 2
    def _cw(self): return self._canvas.winfo_width()  or self.winfo_screenwidth()
    def _ch(self): return self._canvas.winfo_height() or self.winfo_screenheight()

    def _countdown_text(self, secs, tag="countdown"):
        self._canvas.delete(tag)
        self._canvas.create_text(
            self._cx(), self._cy() + int(self._ch() * 0.38),
            text=f"continuing in  {secs}s …",
            fill=self._C_DIM, font=self._F_SMALL, tags=tag)

    def _current_stim(self):
        return self._stimuli[self._idx] if self._idx < len(self._stimuli) else None

    # ─────────────────────────────────────────────────────────────────────────
    #  PHASE –1 — NAME ENTRY
    # ─────────────────────────────────────────────────────────────────────────
    def _show_name_entry(self):
        frame = self._use_frame()

        # Title block
        title_row = tk.Frame(frame, bg=self._C_BG, pady=28)
        title_row.pack(fill="x")
        tk.Label(title_row, text="Text-Entry Experiment",
                 bg=self._C_BG, fg=self._C_FG,
                 font=self._F_TITLE).pack()
        tk.Label(title_row,
                 text="Enter your name using the eye-gaze keyboard below, then press  Continue",
                 bg=self._C_BG, fg=self._C_DIM,
                 font=self._F_SMALL).pack(pady=(8, 0))

        # Name input
        inp_row = tk.Frame(frame, bg=self._C_BG, padx=40, pady=10)
        inp_row.pack(fill="x")
        tk.Label(inp_row, text="Your Name:",
                 bg=self._C_BG, fg=self._C_DIM, font=self._F_SMALL).pack(anchor="w")

        txt = NeuText(inp_row, fg=self._C_FG,
                      insertbackground=self._C_FG,
                      font=("Segoe UI", 22), height=2, wrap="word",
                      relief="flat", padx=14, pady=12,
                      highlightbackground=self._C_DIM, highlightthickness=1)
        txt.pack(fill="x", pady=(6, 0))
        txt.focus_set()

        warn_lbl = tk.Label(inp_row, text="",
                            bg=self._C_BG, fg=T("#DC2626"), font=self._F_SMALL)
        warn_lbl.pack(anchor="w", pady=(4, 0))

        def _continue():
            name = txt.get("1.0", "end").strip()
            if not name:
                warn_lbl.config(text="⚠  Please enter your name before continuing.")
                txt.set_error(True)
                self.after(2000, lambda: (
                    warn_lbl.config(text=""),
                    txt.set_error(False)
                ))
                return
            self._participant_name = name
            self._show_intro()

        NeuButton(inp_row, text="  Continue  →  ",
                  command=_continue,
                  bg=self._C_ACC, fg=T("#FFFFFF"),
                  activebackground=T("#1d4ed8"), activeforeground=T("#FFFFFF"),
                  relief="flat", variant="accent",
                  font=("Segoe UI", 13, "bold"),
                  padx=18, pady=8, cursor="hand2").pack(anchor="e", pady=(12, 0))

        # On-screen keyboard
        kb = tk.Frame(frame, bg=self._C_BG)
        kb.pack(fill="both", expand=True, padx=8, pady=4)
        OnScreenKeyboard(kb, txt, layout="normal", notepad_app=None).pack(fill="both", expand=True)

    # ─────────────────────────────────────────────────────────────────────────
    #  PHASE 0 — INTRO  (method selection)
    # ─────────────────────────────────────────────────────────────────────────
    def _show_intro(self):
        self._bd.set_strength(1.0)
        self._use_canvas()
        self._clear()
        self.update_idletasks()

        c  = self._canvas
        cx, cy = self._cx(), self._cy()
        w, h   = self._cw(), self._ch()

        c.create_text(cx, cy-155, text="Text-Entry Experiment",
                      fill=self._C_FG, font=self._F_TITLE, anchor="center")
        c.create_line(cx-250, cy-115, cx+250, cy-115, fill=self._C_DIM, width=1)
        c.create_text(cx, cy-85,
                      text="Eye-gaze typing  ·  Choose your method below",
                      fill=self._C_DIM, font=self._F_SMALL, anchor="center")

        c.create_text(cx, cy-40,
                      text="Select Overt or Covert to begin the experiment:",
                      fill=self._C_FG, font=self._F_BODY, anchor="center")

        # ── Method buttons ────────────────────────────────────────────────────
        def method_btn(parent, title, sub, color, cmd):
            return GlassCard(parent, title, sub, color, cmd, width=330, height=200, orb=False,
                             title_font=("Segoe UI", 21, "bold"), sub_font=self._F_SMALL)

        overt_f = method_btn(c,
            "OVERT",
            "Word shown for 15s\nthen type from memory",
            self._C_ACC,
            lambda: self._show_sequence_mode_selection("overt"))

        covert_f = method_btn(c,
            "COVERT",
            "Word stays visible;\ntype while reading",
            self._C_BLU,
            lambda: self._show_sequence_mode_selection("covert"))

        c.create_window(cx - 170, cy + 130, window=overt_f,  anchor="center")
        c.create_window(cx + 170, cy + 130, window=covert_f, anchor="center")

        c.create_text(cx, h - 32,
                      text="Press  Esc  to close",
                      fill=self._C_DIM, font=self._F_SMALL, anchor="center")

    # ─────────────────────────────────────────────────────────────────────────
    #  PHASE 0-B — SEQUENCE MODE SELECTION (Fixed vs Random)
    # ─────────────────────────────────────────────────────────────────────────
    def _show_sequence_mode_selection(self, method):
        self._bd.set_strength(1.0)
        self._use_canvas()
        self._clear()
        self.update_idletasks()

        c  = self._canvas
        cx, cy = self._cx(), self._cy()
        w, h   = self._cw(), self._ch()

        method_color = self._C_ACC if method == "overt" else self._C_BLU

        c.create_text(cx, cy - 180, text=f"{method.upper()} METHOD",
                      fill=method_color, font=("Segoe UI", 14, "bold"), anchor="center")
        c.create_text(cx, cy - 140, text="Select Sequence Mode",
                      fill=self._C_FG, font=self._F_TITLE, anchor="center")
        c.create_line(cx - 260, cy - 100, cx + 260, cy - 100, fill=self._C_DIM, width=1)
        c.create_text(cx, cy - 70,
                      text="Choose how words and phrases will be presented during testing:",
                      fill=self._C_FG, font=self._F_BODY, anchor="center")

        def mode_card(parent, title, sub, color, cmd):
            return GlassCard(parent, title, sub, color, cmd, width=370, height=250, orb=False,
                             title_font=("Segoe UI", 22, "bold"), sub_font=self._F_SMALL)

        fixed_f = mode_card(
            c,
            "FIXED",
            "Structured order:\n2 Words  →  1 Phrase\n(repeated 5 times)\n\n(15 Structured Trials)",
            self._C_ACC,
            lambda: self._show_keyboard_selection(method, "fixed")
        )

        random_f = mode_card(
            c,
            "RANDOM",
            "Fully randomized order of\n10 words and 5 phrases\n\n(15 Randomized Trials)",
            self._C_PUR,
            lambda: self._show_keyboard_selection(method, "random")
        )

        c.create_window(cx - 200, cy + 100, window=fixed_f, anchor="center")
        c.create_window(cx + 200, cy + 100, window=random_f, anchor="center")

        # Back button
        back_btn = NeuButton(
            c, text="←  Back to Method Selection",
            command=self._show_intro,
            bg=self._C_BG, fg=self._C_DIM,
            activebackground=T("#EFEFEF"), activeforeground=self._C_FG,
            relief="solid", bd=1,
            font=self._F_SMALL, padx=14, pady=6, cursor="hand2"
        )
        c.create_window(cx, cy + 265, window=back_btn, anchor="center")

        c.create_text(cx, h - 32,
                      text="Press  Esc  to close",
                      fill=self._C_DIM, font=self._F_SMALL, anchor="center")

    # ─────────────────────────────────────────────────────────────────────────
    #  PHASE 0-C — KEYBOARD SELECTION
    # ─────────────────────────────────────────────────────────────────────────
    def _show_keyboard_selection(self, method, sequence_mode):
        self._bd.set_strength(1.0)
        self._use_canvas()
        self._clear()
        self.update_idletasks()

        c  = self._canvas
        cx, cy = self._cx(), self._cy()
        w, h   = self._cw(), self._ch()

        method_color = self._C_ACC if method == "overt" else self._C_BLU
        seq_color    = self._C_ACC if sequence_mode == "fixed" else self._C_PUR

        # Breadcrumb
        c.create_text(cx, cy - 200, text=f"{method.upper()}  ·  {sequence_mode.upper()} SEQUENCE",
                      fill=method_color, font=("Segoe UI", 13, "bold"), anchor="center")
        c.create_text(cx, cy - 162, text="Select Keyboard Layout",
                      fill=self._C_FG, font=self._F_TITLE, anchor="center")
        c.create_line(cx - 290, cy - 122, cx + 290, cy - 122, fill=self._C_DIM, width=1)
        c.create_text(cx, cy - 90,
                      text="Choose the on-screen keyboard arrangement for all typing trials:",
                      fill=self._C_FG, font=self._F_BODY, anchor="center")

        # ── Keyboard option cards ─────────────────────────────────────────────
        KB_OPTIONS = [
            (
                "QWERTY",
                "normal",
                "Standard QWERTY layout\n(familiar, most common)",
                self._C_ACC,
            ),
            (
                "ALPHABETICAL",
                "alpha",
                "A → Z alphabetical order\n(systematic arrangement)",
                self._C_BLU,
            ),
            (
                "FREQUENCY",
                "cluster",
                "Letter-frequency clustered\n(common letters centred)",
                self._C_PUR,
            ),
        ]

        def kb_card(parent, title, sub, color, cmd):
            return GlassCard(parent, title, sub, color, cmd, width=265, height=210, orb=False,
                             title_font=("Segoe UI", 17, "bold"), sub_font=self._F_SMALL)

        positions = [cx - 280, cx, cx + 280]
        for pos, (title, layout_key, sub, color) in zip(positions, KB_OPTIONS):
            card = kb_card(
                c, title, sub, color,
                lambda lk=layout_key: self._begin(method, sequence_mode, lk)
            )
            c.create_window(pos, cy + 70, window=card, anchor="center")

        # Back button
        back_btn = NeuButton(
            c, text="←  Back to Sequence Selection",
            command=lambda: self._show_sequence_mode_selection(method),
            bg=self._C_BG, fg=self._C_DIM,
            activebackground=T("#EFEFEF"), activeforeground=self._C_FG,
            relief="solid", bd=1,
            font=self._F_SMALL, padx=14, pady=6, cursor="hand2"
        )
        c.create_window(cx, cy + 230, window=back_btn, anchor="center")

        c.create_text(cx, h - 32,
                      text="Press  Esc  to close",
                      fill=self._C_DIM, font=self._F_SMALL, anchor="center")

    # ─────────────────────────────────────────────────────────────────────────
    def _begin(self, method, sequence_mode="fixed", keyboard_layout="normal"):
        self._method          = method
        self._sequence_mode   = sequence_mode
        self._keyboard_layout = keyboard_layout
        self._idx           = 0
        self._responses     = []

        # ── Build stimulus list from the FIXED canonical sets ─────────────────
        # Both lists are deterministic — every participant sees all 15 items.
        words   = list(self.ALL_WORDS)    # exactly 10 words
        phrases = list(self.ALL_PHRASES)  # exactly 5 phrases

        if sequence_mode == "fixed":
            # Fixed interleaved order: 5 blocks of (2 Words + 1 Phrase) = 15 trials
            self._stimuli = [
                words[0], words[1],
                phrases[0],
                words[2], words[3],
                phrases[1],
                words[4], words[5],
                phrases[2],
                words[6], words[7],
                phrases[3],
                words[8], words[9],
                phrases[4],
            ]
        else:
            # Random mode: shuffle the full pool of 10 words and 5 phrases (15 trials)
            pool = words + phrases
            random.shuffle(pool)
            self._stimuli = pool

        # ── Mark experiment start time for heatmap ─────────────────────────────
        self._exp_start_time = datetime.datetime.now()
        # ── Find the active gaze log CSV from the running tracker ───────────────
        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidate_csvs = sorted(
            [f for f in os.listdir(base_dir)
             if f.endswith("_gaze_log.csv") or f == "gaze_log.csv"],
            key=lambda f: os.path.getmtime(os.path.join(base_dir, f)),
            reverse=True
        )
        self._gaze_csv_path = os.path.join(base_dir, candidate_csvs[0]) \
            if candidate_csvs else None
        print(f"[HeatMap] Experiment started ({method.upper()} - {sequence_mode.upper()}). Gaze CSV: {self._gaze_csv_path}")
        self._center_cursor()   # centre cursor before first trial
        self._show_instructions()


    # ─────────────────────────────────────────────────────────────────────────
    #  PHASE 1 — INSTRUCTIONS  (5 s auto-advance)
    # ─────────────────────────────────────────────────────────────────────────
    def _show_instructions(self, secs=5):
        if secs == 5:
            self._bd.set_strength(1.0)
            self._use_canvas(); self._clear(); self.update_idletasks()

        c = self._canvas
        cx, cy = self._cx(), self._cy()
        instr = self._OVERT_INSTR if self._method == "overt" else self._COVERT_INSTR
        acc   = self._C_ACC if self._method == "overt" else self._C_BLU

        if secs == 5:
            self._bd.draw_glass(cx - 440, cy - 255, cx + 440, cy + 175, r=36)
            c.create_text(cx, cy - 210, text=instr[0],
                          fill=self._C_FG, font=self._F_HEAD, anchor="center")
            c.create_line(cx-250, cy-175, cx+250, cy-175, fill=self._C_DIM, width=1)
            c.create_text(cx, cy - 20, text=instr[1],
                          fill=self._C_FG, font=self._F_BODY,
                          anchor="center", justify="center")

        self._countdown_text(secs)

        if secs > 0:
            self._after_id = self.after(1000, lambda: self._show_instructions(secs - 1))
        else:
            self._show_fixation()

    # ─────────────────────────────────────────────────────────────────────────
    #  PHASE 2 — FIXATION CROSS  (5 s auto-advance, shown before each trial)
    # ─────────────────────────────────────────────────────────────────────────
    def _show_fixation(self, secs=5):
        self._bd.set_strength(0.0)      # plain background for the fixation cross
        if secs == 5:
            self._use_canvas(); self._clear(); self.update_idletasks()

        c = self._canvas
        cx, cy = self._cx(), self._cy()
        acc    = self._C_ACC if self._method == "overt" else self._C_BLU

        if secs == 5:
            c.create_text(cx, cy - 190,
                          text=f"Trial  {self._idx + 1}  of  {len(self._stimuli)}",
                          fill=self._C_DIM, font=self._F_SMALL, anchor="center")
            c.create_text(cx, cy - 145,
                          text="Focus on the cross below",
                          fill=self._C_DIM, font=self._F_SMALL, anchor="center")
            c.create_text(cx, cy, text="+",
                          fill=self._C_FIX, font=self._F_FIX, anchor="center")

        self._countdown_text(secs)

        if secs > 0:
            self._after_id = self.after(1000, lambda: self._show_fixation(secs - 1))
        else:
            if self._method == "overt":
                self._show_overt_memorize()
            else:
                self._show_covert_typing()

    # ─────────────────────────────────────────────────────────────────────────
    #  PHASE 3-A — OVERT: memorize  (15-second countdown)
    # ─────────────────────────────────────────────────────────────────────────
    def _show_overt_memorize(self, secs=None):
        if secs is None:
            secs = self.MEMORIZE_SECS
            self._bd.set_strength(0.0)      # plain background while memorizing
            self._use_canvas(); self._clear(); self.update_idletasks()
            self._mem_skipped = False            # reset for this trial
            self._create_memorize_skip_button()  # optional "Skip memorizing"
            self._start_pose_monitor()           # beep if head leaves the frame

        c  = self._canvas
        cx, cy = self._cx(), self._cy()
        ch     = self._ch()
        stim   = self._current_stim()

        if secs == self.MEMORIZE_SECS:
            c.create_text(cx, cy - 265, text="MEMORIZE  —  OVERT",
                          fill=self._C_DIM, font=("Segoe UI", 11, "bold"),
                          anchor="center")
            c.create_line(cx-250, cy-240, cx+250, cy-240, fill=self._C_DIM, width=1)
            # Word / sentence (large)
            c.create_text(cx, cy - 130, text=stim,
                          fill=self._C_FG, font=self._F_STIM,
                          anchor="center", justify="center",
                          width=int(self._cw() * 0.85 or 1000))
            # Hint
            c.create_text(cx, cy + 70,
                          text="Memorize this carefully.\nThe keyboard will appear after the timer ends.",
                          fill=self._C_DIM, font=self._F_SMALL,
                          anchor="center", justify="center")

        # Live countdown timer
        mins = secs // 60
        secs_r = secs % 60
        self._canvas.delete("timer")
        self._canvas.create_text(
            cx, ch - 55,
            text=f"⏱  {mins}:{secs_r:02d}  remaining",
            fill=self._C_DIM, font=("Segoe UI", 18, "bold"),
            tags="timer", anchor="center")

        if secs > 0:
            self._after_id = self.after(1000, lambda: self._mem_tick(secs - 1))
        else:
            self._show_overt_typing()

    # ── Skip-memorizing feature (optional, user decides) ─────────────────────
    def _mem_tick(self, secs):
        """Advance the memorize countdown, unless the skip prompt is open."""
        if self._mem_prompt_open:
            self._mem_resume_secs = secs      # continue from here on "No"
            return
        self._show_overt_memorize(secs)

    def _create_memorize_skip_button(self):
        c = self._canvas
        cx, cy = self._cx(), self._cy()
        self._mem_skip_btn = NeuButton(
            c, text="  ⏭  Skip Memorizing  ",
            command=self._ask_skip_memorize,
            bg=self._C_BG, fg=self._C_FG,
            activebackground=T("#EFEFEF"), activeforeground=self._C_FG,
            relief="solid", bd=1, font=("Segoe UI", 14, "bold"),
            padx=24, pady=10, cursor="hand2")
        c.create_window(cx, cy + 190, window=self._mem_skip_btn,
                        anchor="center", tags="mem_skip")

    def _ask_skip_memorize(self):
        """Pop up 'Skip memorizing?' — the countdown is held until answered."""
        if self._mem_prompt_open:
            return
        self._mem_prompt_open = True
        c = self._canvas
        cx, cy = self._cx(), self._cy()
        box = _GlassPrompt(
            c, self._bd, cx, cy, "Skip memorizing and go straight to typing?",
            "The countdown is on hold until you choose.",
            [("Yes, skip", self._skip_memorize_yes, "accent"),
             ("No, keep memorizing", self._skip_memorize_no, None)],
            "mem_skip", self._C_FG, self._C_DIM)
        self._mem_skip_box = box
        c.tag_raise("mem_skip")

    def _close_memorize_prompt(self):
        self._mem_prompt_open = False
        box = self._mem_skip_box
        if box is not None:
            try: box.destroy()
            except Exception: pass
            self._mem_skip_box = None

    def _skip_memorize_no(self):
        self._close_memorize_prompt()
        secs = self._mem_resume_secs
        self._mem_resume_secs = None
        if secs is not None:                  # tick was held -> continue now
            self._show_overt_memorize(secs)

    def _skip_memorize_yes(self):
        self._close_memorize_prompt()
        self._mem_resume_secs = None
        self._mem_skipped = True
        self._cancel_after()
        self._show_overt_typing()

    # ── Head-pose guard: beep while the head is out of position ──────────────
    _POSE_FILE        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "head_pose_status.json")
    POSE_POLL_MS      = 250     # how often to read the tracker's status
    POSE_BEEP_EVERY   = 1.2     # seconds between warning beeps
    POSE_STALE_SEC    = 2.0     # ignore status older than this (tracker not running)
    _POSE_MESSAGES    = {
        "NO_FACE"      : "Face not detected — move back into the camera frame",
        "OUT_OF_FRAME" : "Face is at the edge — move to the centre of the frame",
        "TURNED LEFT"  : "Head turned left — face the screen",
        "TURNED RIGHT" : "Head turned right — face the screen",
        "LOOKING UP"   : "Head tilted up — face the screen",
        "LOOKING DOWN" : "Head tilted down — face the screen",
    }

    def _start_pose_monitor(self):
        self._pose_last_beep = 0.0
        self._poll_pose()

    def _poll_pose(self):
        import time
        status = None
        try:
            with open(self._POSE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if time.time() - float(data.get("t", 0)) <= self.POSE_STALE_SEC:
                status = data.get("status")
        except Exception:
            status = None            # no tracker / unreadable -> stay silent

        bad = status is not None and status != "OK"
        try:
            self._canvas.delete("pose_warn")
            if bad:
                self._canvas.create_text(
                    self._cx(), self._cy() + 110,
                    text="⚠  " + self._POSE_MESSAGES.get(status, "Keep your head inside the frame"),
                    fill=DANGER, font=("Segoe UI", 16, "bold"),
                    anchor="center", tags="pose_warn")
        except Exception:
            pass
        if bad and time.time() - self._pose_last_beep >= self.POSE_BEEP_EVERY:
            self._pose_last_beep = time.time()
            self._beep_async(900, 220)

        self._pose_after_id = self.after(self.POSE_POLL_MS, self._poll_pose)

    def _stop_memorize_extras(self):
        """Stop the pose beep and remove skip widgets (called on phase change)."""
        if self._pose_after_id:
            try: self.after_cancel(self._pose_after_id)
            except Exception: pass
            self._pose_after_id = None
        for name in ("_mem_skip_box", "_mem_skip_btn"):
            w = getattr(self, name, None)
            if w is not None:
                try: w.destroy()
                except Exception: pass
                setattr(self, name, None)
        self._mem_prompt_open = False
        self._mem_resume_secs = None
        try:
            self._canvas.delete("mem_skip")
            self._canvas.delete("pose_warn")
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    #  PHASE 3-B — OVERT: type from memory
    # ─────────────────────────────────────────────────────────────────────────
    def _show_overt_typing(self):
        frame = self._use_frame()
        self._reset_trial_tracking()

        # Header
        _hp = GlassPanel(frame, padx=24, pady=10)
        _hp.pack(fill="x", padx=14, pady=(12, 2))
        hdr, hbg = _hp.body, _hp.body_bg
        mode_tag = f" ({self._sequence_mode.upper()})" if self._sequence_mode else ""
        tk.Label(hdr, text=f"OVERT{mode_tag}  ·  Type from memory",
                 bg=hbg, fg=self._C_FG,
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        tk.Label(hdr,
                 text=f"Trial  {self._idx + 1} / {len(self._stimuli)}",
                 bg=hbg, fg=self._C_DIM,
                 font=self._F_SMALL).pack(side="right")

        # Input row
        inp_row = tk.Frame(frame, bg=self._C_BG, padx=32, pady=14)
        inp_row.pack(fill="x")
        tk.Label(inp_row, text="Type what you memorized:",
                 bg=self._C_BG, fg=self._C_DIM, font=self._F_SMALL).pack(anchor="w")

        txt = NeuText(inp_row, fg=self._C_FG,
                      insertbackground=self._C_FG,
                      font=("Segoe UI", 20), height=2, wrap="word",
                      relief="flat", padx=14, pady=12,
                      highlightbackground=self._C_DIM, highlightthickness=1)
        txt.pack(fill="x", pady=(6, 0))
        txt.focus_set()

        # ── Keystroke tracking (works for both physical & on-screen keyboard) ──
        def _track_changes(event=None):
            if not txt.edit_modified():
                return
            txt.edit_modified(False)
            current = txt.get("1.0", "end-1c")
            prev    = self._prev_typed_text
            now     = datetime.datetime.now()
            if not self._first_key_pressed and current != prev:
                self._trial_start_time  = now
                self._first_key_pressed = True
            rel_time = round((now - self._trial_start_time).total_seconds(), 3) \
                       if self._trial_start_time else 0.0
            if len(current) > len(prev):
                added = current[len(prev):]
                self._spacebar_count += added.count(" ")
                for ch in added:
                    self._keystroke_log.append([ch if ch != " " else "<SP>", rel_time])
            elif len(current) < len(prev):
                n_del = len(prev) - len(current)
                self._backspace_count += n_del
                for _ in range(n_del):
                    self._keystroke_log.append(["<BS>", rel_time])
            self._prev_typed_text = current

        txt.bind("<<Modified>>", _track_changes, add="+")

        def _save():
            typed      = txt.get("1.0", "end").strip()
            end_time   = datetime.datetime.now()
            start_time = self._trial_start_time
            duration   = round((end_time - start_time).total_seconds(), 3) \
                         if start_time else ""
            self._responses.append({
                "participant_name"   : self._participant_name,
                "trial_number"       : self._idx + 1,
                "method"             : "overt",
                "sequence_mode"      : self._sequence_mode or "fixed",
                "keyboard_layout"    : self._keyboard_layout,
                "stimulus"           : self._current_stim(),
                "typed_response"     : typed,
                "is_correct"         : typed.strip().lower() == (self._current_stim() or "").strip().lower(),
                "trial_start_time"   : start_time.isoformat() if start_time else "",
                "trial_end_time"     : end_time.isoformat(),
                "typing_duration_sec": duration,
                "spacebar_count"     : self._spacebar_count,
                "backspace_count"    : self._backspace_count,
                "char_count"         : len(typed),
                "word_count"         : len(typed.split()) if typed else 0,
                "letter_timestamps"  : json.dumps(self._keystroke_log),
                "memorize_skipped"   : self._mem_skipped,
            })
            self._advance()

        NeuButton(inp_row, text="  ✔  Save & Next  ",
                  command=_save, variant="accent",
                  bg=self._C_BG, fg=self._C_FG,
                  activebackground=T("#EFEFEF"), activeforeground=self._C_FG,
                  relief="solid", bd=1,
                  font=("Segoe UI", 13, "bold"),
                  padx=18, pady=8, cursor="hand2").pack(anchor="e", pady=(10, 0))

        # Keyboard
        kb = tk.Frame(frame, bg=self._C_BG)
        kb.pack(fill="both", expand=True, padx=8, pady=4)
        OnScreenKeyboard(kb, txt, layout=self._keyboard_layout, notepad_app=None).pack(fill="both", expand=True)

    # ─────────────────────────────────────────────────────────────────────────
    #  PHASE 4 — COVERT: word visible + keyboard
    # ─────────────────────────────────────────────────────────────────────────
    def _show_covert_typing(self):
        frame = self._use_frame()
        stim  = self._current_stim()
        self._reset_trial_tracking()

        # Header
        _hp = GlassPanel(frame, padx=24, pady=10)
        _hp.pack(fill="x", padx=14, pady=(12, 2))
        hdr, hbg = _hp.body, _hp.body_bg
        mode_tag = f" ({self._sequence_mode.upper()})" if self._sequence_mode else ""
        tk.Label(hdr, text=f"COVERT{mode_tag}  ·  Type what you see",
                 bg=hbg, fg=self._C_FG,
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        tk.Label(hdr,
                 text=f"Trial  {self._idx + 1} / {len(self._stimuli)}",
                 bg=hbg, fg=self._C_DIM,
                 font=self._F_SMALL).pack(side="right")

        # Permanently visible stimulus
        _sp = GlassPanel(frame, padx=10, pady=8, accent=self._C_BLU)
        _sp.pack(fill="x", padx=14, pady=4)
        stim_row, sbg = _sp.body, _sp.body_bg
        tk.Label(stim_row, text="Read & type →",
                 bg=sbg, fg=self._C_DIM, font=self._F_SMALL).pack()
        tk.Label(stim_row, text=stim,
                 bg=sbg, fg=self._C_FG, font=self._F_STIM,
                 wraplength=int(self.winfo_screenwidth() * 0.85),
                 justify="center").pack(pady=(2, 0))

        # Input row
        inp_row = tk.Frame(frame, bg=self._C_BG, padx=32, pady=4)
        inp_row.pack(fill="x")
        tk.Label(inp_row, text="Your typed response:",
                 bg=self._C_BG, fg=self._C_DIM, font=self._F_SMALL).pack(anchor="w")

        txt = NeuText(inp_row, fg=self._C_FG,
                      insertbackground=self._C_FG,
                      font=("Segoe UI", 20), height=2, wrap="word",
                      relief="flat", padx=14, pady=8,
                      highlightbackground=self._C_DIM, highlightthickness=1)
        txt.pack(fill="x", pady=(2, 0))
        txt.focus_set()

        # ── Keystroke tracking (works for both physical & on-screen keyboard) ──
        def _track_changes(event=None):
            if not txt.edit_modified():
                return
            txt.edit_modified(False)
            current = txt.get("1.0", "end-1c")
            prev    = self._prev_typed_text
            now     = datetime.datetime.now()
            if not self._first_key_pressed and current != prev:
                self._trial_start_time  = now
                self._first_key_pressed = True
            rel_time = round((now - self._trial_start_time).total_seconds(), 3) \
                       if self._trial_start_time else 0.0
            if len(current) > len(prev):
                added = current[len(prev):]
                self._spacebar_count += added.count(" ")
                for ch in added:
                    self._keystroke_log.append([ch if ch != " " else "<SP>", rel_time])
            elif len(current) < len(prev):
                n_del = len(prev) - len(current)
                self._backspace_count += n_del
                for _ in range(n_del):
                    self._keystroke_log.append(["<BS>", rel_time])
            self._prev_typed_text = current

        txt.bind("<<Modified>>", _track_changes, add="+")

        def _save():
            typed      = txt.get("1.0", "end").strip()
            end_time   = datetime.datetime.now()
            start_time = self._trial_start_time
            duration   = round((end_time - start_time).total_seconds(), 3) \
                         if start_time else ""
            self._responses.append({
                "participant_name"   : self._participant_name,
                "trial_number"       : self._idx + 1,
                "method"             : "covert",
                "sequence_mode"      : self._sequence_mode or "fixed",
                "keyboard_layout"    : self._keyboard_layout,
                "stimulus"           : self._current_stim(),
                "typed_response"     : typed,
                "is_correct"         : typed.strip().lower() == (self._current_stim() or "").strip().lower(),
                "trial_start_time"   : start_time.isoformat() if start_time else "",
                "trial_end_time"     : end_time.isoformat(),
                "typing_duration_sec": duration,
                "spacebar_count"     : self._spacebar_count,
                "backspace_count"    : self._backspace_count,
                "char_count"         : len(typed),
                "word_count"         : len(typed.split()) if typed else 0,
                "letter_timestamps"  : json.dumps(self._keystroke_log),
            })
            self._advance()

        NeuButton(inp_row, text="  ✔  Save & Next  ",
                  command=_save, variant="accent",
                  bg=self._C_BG, fg=self._C_FG,
                  activebackground=T("#EFEFEF"), activeforeground=self._C_FG,
                  relief="solid", bd=1,
                  font=("Segoe UI", 13, "bold"),
                  padx=18, pady=8, cursor="hand2").pack(anchor="e", pady=(10, 0))

        # Keyboard
        kb = tk.Frame(frame, bg=self._C_BG)
        kb.pack(fill="both", expand=True, padx=8, pady=4)
        OnScreenKeyboard(kb, txt, layout=self._keyboard_layout, notepad_app=None).pack(fill="both", expand=True)

    def _advance(self):
        self._idx += 1
        if self._idx < len(self._stimuli):
            self._show_rest_screen()    # rest + audio countdown before next trial
        else:
            self._save_csv_and_finish()

    # ─────────────────────────────────────────────────────────────────────────
    #  REST SCREEN — pause between trials with audio countdown
    # ─────────────────────────────────────────────────────────────────────────
    REST_DURATION = 30   # seconds of rest before next trial

    def destroy(self):
        # Never leave the tracker paused if the experiment is closed during a rest break
        try:
            if os.path.exists(self._PAUSE_FLAG):
                os.remove(self._PAUSE_FLAG)
        except Exception:
            pass
        super().destroy()

    _PAUSE_FLAG   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker_paused.flag")

    def _show_rest_screen(self, secs=None):
        """Display a rest/break screen between trials with a spoken countdown."""
        if secs is None:
            secs = self.REST_DURATION
            self._bd.set_strength(1.0)
            self._use_canvas(); self._clear(); self.update_idletasks()
            # ── Pause the tracker by creating the flag file ────────────────────
            try:
                with open(self._PAUSE_FLAG, "w") as f:
                    f.write("paused")
            except Exception:
                pass
            # Play initial TTS announcement in a background thread
            self._speak_async("Tracker is paused. Take a rest.")
            # Skip-rest state + button
            self._rest_prompt_open  = False
            self._rest_resume_secs  = None
            self._create_skip_button()

        c  = self._canvas
        cx, cy = self._cx(), self._cy()
        h      = self._ch()

        if secs == self.REST_DURATION:
            c.create_text(cx, cy - 160,
                          text="REST  BREAK",
                          fill=self._C_FG, font=self._F_TITLE, anchor="center")
            c.create_line(cx-200, cy-115, cx+200, cy-115, fill=self._C_DIM, width=1)
            c.create_text(cx, cy - 80,
                          text=f"Trial  {self._idx}  of  {len(self._stimuli)}  completed",
                          fill=self._C_DIM, font=self._F_BODY, anchor="center")
            c.create_text(cx, cy - 40,
                          text="Relax your eyes. The tracker is paused.\nNext trial begins after the countdown.",
                          fill=self._C_DIM, font=self._F_SMALL, anchor="center",
                          justify="center")

        # ── Countdown number (large, animated) ────────────────────────────────
        c.delete("rest_count")
        c.delete("rest_bar")
        c.delete("rest_label")

        if secs > 0:
            # Large countdown number
            count_color = self._C_GRN if secs <= 3 else self._C_ACC
            c.create_text(cx, cy + 50, text=str(secs),
                          fill=count_color, font=("Segoe UI", 96, "bold"),
                          anchor="center", tags="rest_count")
            c.create_text(cx, cy + 130,
                          text="seconds remaining",
                          fill=self._C_DIM, font=self._F_SMALL,
                          anchor="center", tags="rest_label")

            # Progress bar
            bar_w = int(self._cw() * 0.5)
            bar_x = cx - bar_w // 2
            bar_y = cy + 170
            frac  = 1.0 - (secs / self.REST_DURATION)
            c.create_line(bar_x, bar_y + 6, bar_x + bar_w, bar_y + 6, width=14, capstyle="round",
                          fill=T("#E5E7EB"), tags="rest_bar")
            if frac > 0.01:
                c.create_line(bar_x, bar_y + 6, bar_x + max(1, int(bar_w * frac)), bar_y + 6, width=14,
                              capstyle="round", fill=self._C_ACC, tags="rest_bar")

            # Audio beep only for the last 10 seconds of countdown
            if secs <= 10:
                self._beep_async(800 if secs > 3 else 1200, 150)
            # TTS announcement when 10 seconds remain
            if secs == 10:
                self._speak_async("Tracker is starting in 10")

            self._after_id = self.after(1000, lambda: self._rest_tick(secs - 1))
        else:
            self._destroy_rest_widgets()
            # ── Resume tracker by deleting the pause flag ──────────────────────
            try:
                if os.path.exists(self._PAUSE_FLAG):
                    os.remove(self._PAUSE_FLAG)
            except Exception:
                pass
            # Move OS cursor to screen centre so gaze tracking resumes from centre
            self._center_cursor()
            # Countdown finished — announce tracker resuming and proceed
            c.create_text(cx, cy + 50, text="GO!",
                          fill=self._C_GRN, font=("Segoe UI", 72, "bold"),
                          anchor="center", tags="rest_count")
            self._beep_async(1400, 300)
            self._speak_async("Tracker is starting.")
            self._after_id = self.after(800, self._show_fixation)

    # ── Skip-rest feature ────────────────────────────────────────────────────
    def _rest_tick(self, secs):
        """Advance the countdown, unless the skip prompt is open (then wait)."""
        if getattr(self, "_rest_prompt_open", False):
            self._rest_resume_secs = secs      # continue from here on "No"
            return
        self._show_rest_screen(secs)

    def _create_skip_button(self):
        self._destroy_rest_widgets()
        c = self._canvas
        cx, cy = self._cx(), self._cy()
        self._skip_btn = NeuButton(
            c, text="  ⏭  Skip Rest  ",
            command=self._ask_skip_rest,
            bg=self._C_BG, fg=self._C_FG,
            activebackground=T("#EFEFEF"), activeforeground=self._C_FG,
            relief="solid", bd=1, font=("Segoe UI", 14, "bold"),
            padx=24, pady=10, cursor="hand2")
        self._skip_btn_win = c.create_window(cx, cy + 235, window=self._skip_btn,
                                             anchor="center", tags="rest_skip")

    def _ask_skip_rest(self):
        """Pop up 'Do you want to skip the rest time?' (countdown is held)."""
        if getattr(self, "_rest_prompt_open", False):
            return
        self._rest_prompt_open = True
        c = self._canvas
        cx, cy = self._cx(), self._cy()
        box = _GlassPrompt(
            c, self._bd, cx, cy, "Do you want to skip the rest time?",
            "The countdown is on hold until you choose.",
            [("Yes, skip", self._skip_rest_yes, "accent"),
             ("No, keep resting", self._skip_rest_no, None)],
            "rest_skip", self._C_FG, self._C_DIM)
        self._skip_box = box
        c.tag_raise("rest_skip")

    def _close_skip_prompt(self):
        self._rest_prompt_open = False
        box = getattr(self, "_skip_box", None)
        if box is not None:
            try: box.destroy()
            except Exception: pass
            self._skip_box = None

    def _skip_rest_no(self):
        self._close_skip_prompt()
        secs = getattr(self, "_rest_resume_secs", None)
        self._rest_resume_secs = None
        if secs is not None:               # tick was held -> continue now
            self._show_rest_screen(secs)

    def _skip_rest_yes(self):
        self._close_skip_prompt()
        self._rest_resume_secs = None
        self._cancel_after()
        self._show_rest_screen(0)          # jumps to the "GO!" branch

    def _destroy_rest_widgets(self):
        for name in ("_skip_box", "_skip_btn"):
            w = getattr(self, name, None)
            if w is not None:
                try: w.destroy()
                except Exception: pass
                setattr(self, name, None)
        try: self._canvas.delete("rest_skip")
        except Exception: pass
        self._rest_prompt_open = False

    def _center_cursor(self):
        """Warp the OS mouse pointer to the exact centre of this window's screen."""
        try:
            import ctypes
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            ctypes.windll.user32.SetCursorPos(sw // 2, sh // 2)
        except Exception:
            pass   # silently ignore on non-Windows or permission errors

    def _beep_async(self, freq, duration_ms):
        """Play a beep sound in a background thread so UI doesn't freeze."""
        import threading
        def _worker():
            try:
                import winsound
                winsound.Beep(freq, duration_ms)
            except Exception:
                pass
        threading.Thread(target=_worker, daemon=True).start()

    def _speak_async(self, text):
        """Speak text using Windows SAPI via PowerShell in a background thread."""
        import threading
        def _worker():
            try:
                import subprocess as sp
                ps_cmd = (
                    f"Add-Type -AssemblyName System.Speech; "
                    f"(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{text}')"
                )
                sp.run(["powershell", "-Command", ps_cmd],
                       capture_output=True, timeout=10)
            except Exception:
                pass
        threading.Thread(target=_worker, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    #  HEATMAP — generated from tracker gaze data during this experiment
    # ─────────────────────────────────────────────────────────────────────────
    def _generate_experiment_heatmap(self, csv_filepath: str):
        """
        Read gaze points that were logged by tracker.py during this experiment
        session and generate a heatmap PNG named after the experiment CSV.

        The tracker's gaze CSV contains a `timestamp` column (seconds since
        session start).  We use the wall-clock start time we recorded in
        _begin() to extract only the rows that fall within the experiment
        window.
        """
        if not self._gaze_csv_path or not os.path.exists(self._gaze_csv_path):
            print("[HeatMap] No gaze CSV found — skipping experiment heatmap.")
            return
        if not self._exp_start_time:
            return

        try:
            import pandas as pd
            df = pd.read_csv(self._gaze_csv_path)
            if "gaze_x" not in df.columns or "gaze_y" not in df.columns:
                print("[HeatMap] Gaze CSV missing required columns.")
                return

            gaze_pts = list(zip(df["gaze_x"].tolist(), df["gaze_y"].tolist()))

            if not gaze_pts:
                print("[HeatMap] No gaze points collected.")
                return

            # Output: same folder as the experiment CSV, same base name
            hm_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "heatmaps")
            os.makedirs(hm_dir, exist_ok=True)
            base   = os.path.basename(os.path.splitext(csv_filepath)[0])
            outf   = os.path.join(hm_dir, base + "_heatmap.png")
            label  = os.path.basename(csv_filepath)

            sw = self.winfo_screenwidth()  or 1920
            sh = self.winfo_screenheight() or 1080

            _try_generate_heatmap(gaze_pts, outf, sw, sh, label)
            print(f"[HeatMap] Generating experiment heatmap -> {outf}")

        except Exception as e:
            print(f"[HeatMap] Could not generate experiment heatmap: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    #  PHASE 5 — SAVE CSV & FINISH
    # ─────────────────────────────────────────────────────────────────────────

    def _save_csv_and_finish(self):
        # ── Determine output path ────────────────────────────────────────────
        base_dir = os.path.dirname(os.path.abspath(__file__))
        csv_dir  = os.path.join(base_dir, "Real_test", "real_test_csv")
        os.makedirs(csv_dir, exist_ok=True)

        ts        = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = self._participant_name.strip().lower().replace(" ", "_") or "unknown"
        mode_str  = f"_{self._sequence_mode}" if self._sequence_mode else ""
        kb_str    = f"_{self._keyboard_layout}" if self._keyboard_layout else ""
        filename  = f"experiment_{self._method}{mode_str}{kb_str}_{safe_name}_{ts}.csv"
        filepath  = os.path.join(csv_dir, filename)

        # ── Write CSV ────────────────────────────────────────────────────────
        fieldnames = [
            "participant_name", "trial_number", "method", "sequence_mode",
            "keyboard_layout",
            "stimulus", "typed_response", "is_correct",
            "trial_start_time", "trial_end_time",
            "typing_duration_sec", "spacebar_count", "backspace_count",
            "char_count", "word_count", "letter_timestamps",
            "memorize_skipped",
        ]
        try:
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self._responses)
            save_ok = True

            # Automatically run latex.py to generate the LaTeX report
            try:
                latex_script = os.path.join(base_dir, "latex.py")
                subprocess.Popen([sys.executable, latex_script, filepath])
            except Exception as e:
                print(f"[ERROR] Failed to auto-generate LaTeX: {e}")
        except Exception as exc:
            save_ok  = False
            err_msg  = str(exc)

        # ── Generate gaze heatmap for this experiment session ─────────────────
        if save_ok:
            self._generate_experiment_heatmap(filepath)

        # ── Confirmation screen ──────────────────────────────────────────────
        self._bd.set_strength(1.0)
        self._use_canvas(); self._clear(); self.update_idletasks()
        c  = self._canvas
        cx, cy = self._cx(), self._cy()
        h      = self._ch()

        if save_ok:
            c.create_text(cx, cy - 90,
                          text="✓  Experiment Complete",
                          fill=self._C_GRN, font=self._F_HEAD, anchor="center")
            mode_desc = f" ({self._sequence_mode.upper()})" if self._sequence_mode else ""
            c.create_text(cx, cy - 45,
                          text=f"{self._method.upper()}{mode_desc}  ·  {len(self._responses)} trial(s) saved to CSV",
                          fill=self._C_DIM, font=self._F_BODY, anchor="center")
            c.create_text(cx, cy,
                          text="Saved to:",
                          fill=self._C_DIM, font=self._F_SMALL, anchor="center")
            c.create_text(cx, cy + 32,
                          text=f"Real_test/real_test_csv/{filename}",
                          fill=self._C_FG, font=("Segoe UI", 13, "bold"), anchor="center")
        else:
            c.create_text(cx, cy - 60,
                          text="⚠  Could not save CSV",
                          fill=T("#DC2626"), font=self._F_HEAD, anchor="center")
            c.create_text(cx, cy,
                          text=err_msg,
                          fill=self._C_DIM, font=self._F_SMALL, anchor="center",
                          width=int(self._cw() * 0.7))

        # Buttons
        b1 = NeuButton(c, text="  ↺  Restart  ", command=self._show_name_entry,
                       font=("Segoe UI", 13, "bold"), padx=16, pady=8)
        b2 = NeuButton(c, text="  ✕  Close  ", command=self.destroy,
                       font=("Segoe UI", 13, "bold"), padx=16, pady=8)
        c.create_window(cx - 20, cy + 100, window=b1, anchor="e")
        c.create_window(cx + 20, cy + 100, window=b2, anchor="w")





# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # To support WebView2, the Tkinter event loop must run in a Single-Threaded Apartment (STA) thread.
    # Since pythonnet initializes the main thread as MTA, we start the Tkinter app in a new STA thread.
    try:
        import clr
        clr.AddReference('System.Threading')
        from System.Threading import Thread, ApartmentState, ThreadStart
        
        def start_gui():
            app = Launcher()
            app.mainloop()
            
        t = Thread(ThreadStart(start_gui))
        t.ApartmentState = ApartmentState.STA
        t.Start()
        t.Join()
    except Exception as e:
        # Fallback to running on the main thread if pythonnet/CLR is not available
        app = Launcher()
        app.mainloop()