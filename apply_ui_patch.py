"""
apply_ui_patch.py  --  UI-only update (dark eye-comfort theme + distinct test cursor).

Run once, from your project folder:      python apply_ui_patch.py

It edits launcher.py (and keyboardaccuracy.py if present) IN PLACE after saving
a backup (launcher.py.bak).  tracker.py is NOT touched.  Safe to run twice.
Needs theme.py and test_cursor.py in the same folder.
"""
import os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(p):
    raw = open(p, "rb").read().decode("utf-8")
    return raw.replace("\r\n", "\n"), ("\r\n" in raw)


def save(p, s, crlf):
    open(p, "wb").write((s.replace("\n", "\r\n") if crlf else s).encode("utf-8"))


def rep(s, old, new, name, count=None):
    n = s.count(old)
    if n == 0:
        print(f"   ! skipped (not found): {name}")
        return s
    if count is not None and n != count:
        print(f"   ! skipped ({n} matches, expected {count}): {name}")
        return s
    print(f"   + {name}" + (f"  x{n}" if n > 1 else ""))
    return s.replace(old, new)


def patch_launcher(p):
    s, crlf = load(p)
    if "apply_test_cursor" in s:
        print("launcher.py already patched - nothing to do.")
        return
    shutil.copy(p, p + ".bak")
    print("launcher.py  (backup: launcher.py.bak)")

    s = rep(s, "from theme import T          # warm eye-comfort colours (see theme.py)\n",
            "from theme import T, TXT_LIGHT   # eye-comfort colours (see theme.py)\n"
            "from test_cursor import apply_test_cursor   # distinct cursor for the test screens\n",
            "imports")
    s = rep(s, 'fg_color=T("#F8FAFC")', "fg_color=TXT_LIGHT", "keyboard key text colour")
    s = rep(s, 'fg="white"', 'fg=T("#FFFFFF")', "button text on green")
    s = rep(s, 'activeforeground="white"', 'activeforeground=T("#FFFFFF")', "button active text")

    s = rep(s, """        self._show_name_entry()

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _cancel_after(self):""", """        self._show_name_entry()
        self._cursor_tick()

    # ── Distinct test cursor (re-applied because each screen builds new widgets) ──
    def _cursor_tick(self):
        try:
            if not self.winfo_exists():
                return
            apply_test_cursor(self)
            self._cursor_after = self.after(600, self._cursor_tick)
        except Exception:
            pass

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _cancel_after(self):""", "test cursor on the experiment window", count=1)
    save(p, s, crlf)


def patch_kbacc(p):
    s, crlf = load(p)
    if "TXT_LIGHT" in s:
        return
    shutil.copy(p, p + ".bak")
    print("keyboardaccuracy.py  (backup: keyboardaccuracy.py.bak)")
    s = rep(s, "from theme import T          # warm eye-comfort colours (see theme.py)\n",
            "from theme import T, TXT_LIGHT   # eye-comfort colours (see theme.py)\n", "import")
    s = rep(s, 'fg_color=T("#F8FAFC")', "fg_color=TXT_LIGHT", "keyboard key text colour")
    save(p, s, crlf)


if __name__ == "__main__":
    for need in ("theme.py", "test_cursor.py", "launcher.py"):
        if not os.path.exists(os.path.join(HERE, need)):
            sys.exit(f"Missing {need} in {HERE} - put all files in your project folder first.")
    patch_launcher(os.path.join(HERE, "launcher.py"))
    k = os.path.join(HERE, "keyboardaccuracy.py")
    if os.path.exists(k):
        patch_kbacc(k)
    print("\nDone. tracker.py was not changed.  Colour mode: edit THEME_MODE in theme.py.")
