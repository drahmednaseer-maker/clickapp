# -*- coding: utf-8 -*-
"""RetryClicker - Template matching + OCR fallback auto-clicker."""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading, time, json, os, sys, re, glob

import mss
import pyautogui
import pytesseract
from PIL import Image, ImageTk, ImageDraw
import cv2
import numpy as np

# ── Tesseract ──────────────────────────────────────────────────────────────
_TESS_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\Users\{}\AppData\Local\Programs\Tesseract-OCR\tesseract.exe".format(
        os.environ.get("USERNAME", "")),
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
]
TESSERACT_EXE = next((p for p in _TESS_PATHS if os.path.isfile(p)), None)
if TESSERACT_EXE:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE

# ── Paths ──────────────────────────────────────────────────────────────────
APP_DIR       = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)

# ── Screen size ────────────────────────────────────────────────────────────
try:
    _SW, _SH = pyautogui.size()
except Exception:
    _SW, _SH = 1920, 1080

# ── Settings ───────────────────────────────────────────────────────────────
DEFAULTS = {
    "region":        {"x": 0, "y": 0, "w": _SW, "h": _SH},
    "interval":      0.2,
    "cooldown":      2.0,
    "keyword":       "Retry, Accept all",
    "confidence":    10,
    "case_sensitive": False,
    "click_offset_x": 0,
    "click_offset_y": 0,
    "tmatch_thresh":  0.72,
}

def load_settings():
    if os.path.isfile(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                d = json.load(f)
            out = {**DEFAULTS, **d}
            out["region"] = {**DEFAULTS["region"], **out.get("region", {})}
            return out
        except Exception:
            pass
    return dict(DEFAULTS)

def save_settings(s):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except Exception:
        pass

# ── Palette ────────────────────────────────────────────────────────────────
BG      = "#0d0f18"
BG2     = "#13151f"
BG3     = "#1c1f2e"
BG4     = "#242838"
BORDER  = "#2a2d3e"
ACCENT  = "#7c6fef"
ACCENT2 = "#a78bfa"
ACCENT3 = "#c4b5fd"
SUCCESS = "#10d9a0"
SUCCESS2= "#0ea882"
DANGER  = "#ef4565"
DANGER2 = "#c73652"
WARNING = "#f59e0b"
TEXT    = "#e8eaf6"
SUBTEXT = "#8892a4"
DIMTEXT = "#4a5568"

# Fonts
F_TITLE  = ("Segoe UI", 15, "bold")
F_HEAD   = ("Segoe UI", 9,  "bold")
F_BODY   = ("Segoe UI", 9)
F_SMALL  = ("Segoe UI", 8)
F_MICRO  = ("Segoe UI", 7)
F_MONO   = ("Consolas", 9)
F_NUM    = ("Segoe UI", 20, "bold")

# ══════════════════════════════════════════════════════════════════════════
# Template matching
# ══════════════════════════════════════════════════════════════════════════
def load_templates():
    out = {}
    for p in glob.glob(os.path.join(TEMPLATES_DIR, "*.png")):
        name = os.path.splitext(os.path.basename(p))[0]
        try:
            out[name] = Image.open(p).convert("RGB")
        except Exception:
            pass
    return out

def match_templates(pil_img, templates, threshold=0.72):
    if not templates:
        return False, "", 0, 0, None
    img_gray = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2GRAY)
    ih, iw = img_gray.shape[:2]
    for name, tmpl in templates.items():
        tg = cv2.cvtColor(np.array(tmpl), cv2.COLOR_RGB2GRAY)
        th0, tw0 = tg.shape[:2]
        for scale in [1.0, 0.9, 1.1, 0.8, 1.2, 0.75, 1.25]:
            sw, sh = max(4, int(tw0*scale)), max(4, int(th0*scale))
            if sh > ih or sw > iw:
                continue
            res = cv2.matchTemplate(img_gray,
                                    cv2.resize(tg, (sw, sh)),
                                    cv2.TM_CCOEFF_NORMED)
            _, val, _, loc = cv2.minMaxLoc(res)
            if val >= threshold:
                return True, name, loc[0]+sw//2, loc[1]+sh//2, (loc[0], loc[1], sw, sh)
    return False, "", 0, 0, None

# ══════════════════════════════════════════════════════════════════════════
# OCR (fallback only)
# ══════════════════════════════════════════════════════════════════════════
_OCR_CFGS = ["--psm 11 --oem 3", "--psm 3 --oem 3", "--psm 6 --oem 3"]

def _gray(pil): return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2GRAY)

def _ocr_variants(pil):
    g = _gray(pil)
    yield pil, 1.0
    yield Image.fromarray(cv2.bitwise_not(g)), 1.0
    if pil.width <= 800:
        up = cv2.resize(g, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
        thr = cv2.medianBlur(
            cv2.adaptiveThreshold(up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                  cv2.THRESH_BINARY, 15, 4), 3)
        yield Image.fromarray(thr), 2.5
        yield Image.fromarray(cv2.bitwise_not(thr)), 2.5

def ocr_find(pil_img, keyword, case_sensitive=False, confidence=10):
    """Scan image for keyword. Returns (found, matched_text, bbox_or_None).

    Uses full-text join + regex search so multi-word phrases like
    'Accept all' are found reliably even when individual words have
    low OCR confidence.  Confidence is checked as an average, not min.
    """
    if not TESSERACT_EXE:
        return False, "", None

    flags   = 0 if case_sensitive else re.IGNORECASE
    kw_words = keyword.split()
    # Allow any whitespace (including none) between words to handle
    # OCR glitches where words are merged or split oddly.
    pattern = re.compile(
        r'\s*'.join(re.escape(w) for w in kw_words), flags)

    for work, scale in _ocr_variants(pil_img):
        if work.width > 1024:
            r = 1024 / work.width
            work  = work.resize((1024, max(1, int(work.height * r))), Image.LANCZOS)
            scale *= r

        for cfg in _OCR_CFGS:
            try:
                data = pytesseract.image_to_data(
                    work, output_type=pytesseract.Output.DICT, config=cfg)
            except Exception:
                continue

            texts = data["text"]
            n     = len(texts)

            # Build flat list of valid (non-empty) word entries
            entries = []   # (orig_idx, text, conf, left, top, w, h)
            for i in range(n):
                t = texts[i].strip()
                if not t:
                    continue
                try:   c = int(data["conf"][i])
                except: c = -1
                entries.append((i, t, c,
                                data["left"][i], data["top"][i],
                                data["width"][i], data["height"][i]))

            if not entries:
                continue

            # Full-text search across all words joined by spaces
            full_text = " ".join(e[1] for e in entries)
            m = pattern.search(full_text)
            if not m:
                continue

            # Map match span back to individual word entries
            pos = 0
            spans = []
            for e in entries:
                spans.append((pos, pos + len(e[1])))
                pos += len(e[1]) + 1   # +1 for the space

            ms, me = m.start(), m.end()
            matched = [entries[i] for i, (ws, we) in enumerate(spans)
                       if ws < me and we > ms]

            if not matched:
                continue

            # Average-confidence gate (not min — short words like "all" score low)
            valid_confs = [e[2] for e in matched if e[2] >= 0]
            avg_conf = (sum(valid_confs) / len(valid_confs)) if valid_confs else 0
            if avg_conf < confidence:
                continue

            # Bounding box from union of all matched word rects
            x1 = int(min(e[3]      for e in matched) / scale)
            y1 = int(min(e[4]      for e in matched) / scale)
            x2 = int(max(e[3]+e[5] for e in matched) / scale)
            y2 = int(max(e[4]+e[6] for e in matched) / scale)
            phrase = " ".join(e[1] for e in matched)
            return True, phrase, (x1, y1, x2 - x1, y2 - y1)

    return False, "", None

# ══════════════════════════════════════════════════════════════════════════
# Region & Template selectors
# ══════════════════════════════════════════════════════════════════════════
class RegionSelector(tk.Toplevel):
    def __init__(self, master, callback):
        super().__init__(master)
        self.callback = callback
        self.sx = self.sy = 0
        self._rect = None
        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.3)
        self.configure(bg="black")
        c = tk.Canvas(self, cursor="crosshair", bg="black", highlightthickness=0)
        c.pack(fill="both", expand=True)
        c.create_text(self.winfo_screenwidth()//2, 40,
                      text="Drag to select watch region  |  ESC = cancel",
                      fill="white", font=("Helvetica", 13, "bold"))
        c.bind("<ButtonPress-1>",   lambda e: self._p(e, c))
        c.bind("<B1-Motion>",        lambda e: self._d(e, c))
        c.bind("<ButtonRelease-1>", lambda e: self._r(e))
        self.bind("<Escape>", lambda e: self.destroy())
        self._c = c

    def _p(self, e, c): self.sx, self.sy = e.x, e.y
    def _d(self, e, c):
        if self._rect: c.delete(self._rect)
        self._rect = c.create_rectangle(self.sx, self.sy, e.x, e.y,
                                         outline=ACCENT2, width=2)
    def _r(self, e):
        x1,y1 = min(self.sx,e.x), min(self.sy,e.y)
        x2,y2 = max(self.sx,e.x), max(self.sy,e.y)
        self.destroy()
        if x2-x1 > 10 and y2-y1 > 10:
            self.callback({"x":x1,"y":y1,"w":x2-x1,"h":y2-y1})

class TemplateSelector(tk.Toplevel):
    def __init__(self, master, on_done):
        super().__init__(master)
        self.on_done = on_done
        self.sx = self.sy = 0
        self._rect = None
        with mss.mss() as sct:
            s = sct.grab(sct.monitors[1])
        self._bg = Image.frombytes("RGB", s.size, s.bgra, "raw", "BGRX")
        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.35)
        self.configure(bg="black")
        c = tk.Canvas(self, cursor="crosshair", bg="black", highlightthickness=0)
        c.pack(fill="both", expand=True)
        c.create_text(self.winfo_screenwidth()//2, 40,
                      text="Draw a tight box around the button  |  ESC = cancel",
                      fill="white", font=("Helvetica", 13, "bold"))
        c.bind("<ButtonPress-1>",   lambda e: self._p(e, c))
        c.bind("<B1-Motion>",        lambda e: self._d(e, c))
        c.bind("<ButtonRelease-1>", lambda e: self._r(e))
        self.bind("<Escape>", lambda e: self.destroy())
        self._c = c

    def _p(self, e, c): self.sx, self.sy = e.x, e.y
    def _d(self, e, c):
        if self._rect: c.delete(self._rect)
        self._rect = c.create_rectangle(self.sx, self.sy, e.x, e.y,
                                         outline=SUCCESS, width=2)
    def _r(self, e):
        x1,y1 = min(self.sx,e.x), min(self.sy,e.y)
        x2,y2 = max(self.sx,e.x), max(self.sy,e.y)
        self.destroy()
        if x2-x1 > 4 and y2-y1 > 4:
            self.on_done(self._bg.crop((x1,y1,x2,y2)))

# ══════════════════════════════════════════════════════════════════════════
# Monitor thread
# ══════════════════════════════════════════════════════════════════════════
class MonitorThread(threading.Thread):
    TILE_W, TILE_H = 400, 200

    def __init__(self, settings, on_click, on_status, on_preview):
        super().__init__(daemon=True)
        self.settings   = settings
        self.on_click   = on_click
        self.on_status  = on_status
        self.on_preview = on_preview
        self._stop      = threading.Event()
        self._last      = 0.0

    def stop(self): self._stop.set()

    def run(self):
        with mss.mss() as sct:
            while not self._stop.is_set():
                try:
                    self._tick(sct)
                except Exception as exc:
                    self.on_status(f"ERR: {exc}")
                self._stop.wait(max(0.05, float(self.settings.get("interval", 0.2))))

    def _tick(self, sct):
        r   = self.settings["region"]
        rw, rh = r["w"], r["h"]

        full = sct.grab({"left":r["x"],"top":r["y"],"width":rw,"height":rh})
        img  = Image.frombytes("RGB", full.size, full.bgra, "raw", "BGRX")
        self.on_preview(img.copy())

        thresh = float(self.settings.get("tmatch_thresh", 0.72))

        # 1. Template matching (primary)
        templates = load_templates()
        if templates:
            found, name, cx, cy, bbox = match_templates(img, templates, thresh)
            if found:
                self._do_click(r["x"]+cx, r["y"]+cy, f"[T] {name}", bbox)
                return

        # 2. OCR tile scan fallback
        if not TESSERACT_EXE:
            self.on_status("watching")
            return

        keywords = [k.strip() for k in
                    self.settings.get("keyword","Retry").split(",") if k.strip()]
        conf   = int(self.settings.get("confidence", 10))
        case_s = bool(self.settings.get("case_sensitive", False))
        tw, th = self.TILE_W, self.TILE_H
        cols = max(1, -(-rw // tw))
        rows = max(1, -(-rh // th))

        for row in range(rows-1, -1, -1):
            for col in range(cols-1, -1, -1):
                tx = r["x"] + col*tw
                ty = r["y"] + row*th
                ta_w = min(tw, r["x"]+rw-tx)
                ta_h = min(th, r["y"]+rh-ty)
                if ta_w <= 0 or ta_h <= 0: continue
                if ty+ta_h <= 80: continue

                tile_shot = sct.grab({"left":tx,"top":ty,
                                      "width":ta_w,"height":ta_h})
                tile = Image.frombytes("RGB", tile_shot.size,
                                       tile_shot.bgra, "raw", "BGRX")
                for kw in keywords:
                    found, matched, bbox = ocr_find(tile, kw, case_s, conf)
                    if found:
                        bx = bbox[0]+bbox[2]//2 if bbox else ta_w//2
                        by = bbox[1]+bbox[3]//2 if bbox else ta_h//2
                        self._do_click(tx+bx, ty+by,
                                       f"[OCR] {matched}", bbox)
                        return

        self.on_status("watching")

    def _do_click(self, abs_cx, abs_cy, label, bbox):
        now = time.time()
        cd  = float(self.settings.get("cooldown", 2.0))
        if now - self._last < cd:
            self.on_status(f"cooldown {cd-(now-self._last):.1f}s")
            return
        abs_cx += int(self.settings.get("click_offset_x", 0))
        abs_cy += int(self.settings.get("click_offset_y", 0))
        pyautogui.click(abs_cx, abs_cy)
        self._last = time.time()
        self.on_click(label, abs_cx, abs_cy, bbox)

# ══════════════════════════════════════════════════════════════════════════
# Custom Slider widget (no native Windows chrome)
# ══════════════════════════════════════════════════════════════════════════
class DarkSlider(tk.Canvas):
    """A fully custom-drawn slider that respects our dark theme."""
    TRACK_H  = 4
    THUMB_R  = 7
    PAD      = 10

    def __init__(self, parent, lo, hi, value, resolution=None, on_change=None, **kw):
        super().__init__(parent, height=24, bg=BG3,
                         highlightthickness=0, cursor="hand2", **kw)
        self.lo = lo
        self.hi = hi
        self._val = float(value)
        self._res = resolution
        self._cb  = on_change
        self.bind("<Configure>",      self._draw)
        self.bind("<ButtonPress-1>",  self._click)
        self.bind("<B1-Motion>",      self._drag)
        self.bind("<MouseWheel>",     self._wheel)
        self._draw()

    def _draw(self, *_):
        self.delete("all")
        w  = self.winfo_width()
        if w < 20: w = 200
        h  = self.winfo_height()
        cy = h // 2
        pad = self.PAD
        tw  = w - pad*2
        frac = (self._val - self.lo) / (self.hi - self.lo) if self.hi != self.lo else 0
        frac = max(0.0, min(1.0, frac))
        tx   = pad + frac * tw

        # inactive track
        self.create_rounded_rect(pad, cy - self.TRACK_H//2,
                                 w - pad, cy + self.TRACK_H//2 + 1,
                                 r=2, fill=BG4, outline="")
        # active track
        if tx > pad:
            self.create_rounded_rect(pad, cy - self.TRACK_H//2,
                                     tx, cy + self.TRACK_H//2 + 1,
                                     r=2, fill=ACCENT, outline="")
        # thumb shadow
        r = self.THUMB_R
        self.create_oval(tx-r+1, cy-r+1, tx+r+1, cy+r+1,
                         fill="#000000", outline="", stipple="gray25")
        # thumb
        self.create_oval(tx-r, cy-r, tx+r, cy+r,
                         fill=ACCENT2, outline=ACCENT3, width=1)

    def create_rounded_rect(self, x1, y1, x2, y2, r=4, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
               x2, y2-r, x2, y2, x2-r, y2, x1+r, y2,
               x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _px_to_val(self, px):
        w   = self.winfo_width()
        pad = self.PAD
        tw  = max(1, w - pad*2)
        frac = (px - pad) / tw
        frac = max(0.0, min(1.0, frac))
        v = self.lo + frac * (self.hi - self.lo)
        if self._res:
            v = round(v / self._res) * self._res
        return v

    def _set(self, v):
        self._val = max(self.lo, min(self.hi, v))
        self._draw()
        if self._cb:
            self._cb(self._val)

    def _click(self, e): self._set(self._px_to_val(e.x))
    def _drag(self,  e): self._set(self._px_to_val(e.x))
    def _wheel(self, e):
        step = self._res if self._res else (self.hi-self.lo)/100
        self._set(self._val + (step if e.delta > 0 else -step))

    def get(self):  return self._val
    def set(self, v): self._set(float(v))


# ══════════════════════════════════════════════════════════════════════════
# Scrollable frame
# ══════════════════════════════════════════════════════════════════════════
class ScrollFrame(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self._canvas = tk.Canvas(self, bg=BG, highlightthickness=0,
                                 borderwidth=0)
        sb = tk.Scrollbar(self, orient="vertical",
                          command=self._canvas.yview,
                          bg=BG3, troughcolor=BG2, width=8)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self._canvas, bg=BG)
        self._win  = self._canvas.create_window((0, 0), window=self.inner,
                                                anchor="nw")
        self.inner.bind("<Configure>", self._on_cfg)
        self._canvas.bind("<Configure>", self._on_cv_cfg)
        self._canvas.bind("<MouseWheel>", self._mw)
        self.inner.bind("<MouseWheel>", self._mw)

    def _on_cfg(self, e):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_cv_cfg(self, e):
        self._canvas.itemconfig(self._win, width=e.width)

    def _mw(self, e):
        self._canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def bind_mousewheel(self, widget):
        widget.bind("<MouseWheel>", self._mw, add="+")


# ══════════════════════════════════════════════════════════════════════════
# GUI
# ══════════════════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings    = load_settings()
        self._thread     = None
        self._running    = False
        self._clicks     = 0
        self._last_str   = tk.StringVar(value="—")
        self._count_str  = tk.StringVar(value="0")
        self._status_str = tk.StringVar(value="Idle")
        self._prev_img   = None

        self.title("RetryClicker")
        self.configure(bg=BG)
        self.geometry("1020x700")
        self.minsize(860, 600)

        self._apply_ttk_style()
        self._build()
        self._refresh_region_lbl()
        self._refresh_templates()

        if not TESSERACT_EXE:
            self._log("Tesseract not found — OCR disabled. Use Template Matching.", "warn")
        if sys.platform == "darwin":
            self._log("macOS: grant Screen Recording + Accessibility in System Settings > Privacy & Security", "warn")

    # ── TTK style ──────────────────────────────────────────────────────────
    def _apply_ttk_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT,
                        fieldbackground=BG3, bordercolor=BORDER,
                        relief="flat", font=F_BODY)
        style.configure("TEntry", fieldbackground=BG3, foreground=TEXT,
                        insertcolor=ACCENT2, bordercolor=BORDER,
                        padding=4)
        style.map("TEntry", bordercolor=[("focus", ACCENT)])
        style.configure("TScrollbar", background=BG3, troughcolor=BG2,
                        bordercolor=BG2, arrowcolor=SUBTEXT, relief="flat")

    # ── Build UI ───────────────────────────────────────────────────────────
    def _build(self):
        # ── Title bar
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=18, pady=(14, 0))

        left_hdr = tk.Frame(hdr, bg=BG)
        left_hdr.pack(side="left", fill="y")
        # dot indicator
        self._dot = tk.Canvas(left_hdr, width=10, height=10,
                              bg=BG, highlightthickness=0)
        self._dot.pack(side="left", padx=(0, 8), pady=6)
        self._dot.create_oval(1, 1, 9, 9, fill=DIMTEXT, outline="", tags="dot")

        tk.Label(left_hdr, text="RetryClicker", font=F_TITLE,
                 bg=BG, fg=TEXT).pack(side="left")
        tk.Label(left_hdr, text="  auto-clicker", font=("Segoe UI", 9),
                 bg=BG, fg=DIMTEXT).pack(side="left", pady=(4, 0))

        # status pill
        self._pill = tk.Label(hdr, textvariable=self._status_str,
                              font=F_SMALL, bg=BG4, fg=SUBTEXT,
                              padx=12, pady=5)
        self._pill.pack(side="right")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=18, pady=(10, 0))

        # ── Body
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=10)

        # Left panel (scrollable)
        left_wrap = tk.Frame(body, bg=BG, width=340)
        left_wrap.pack(side="left", fill="y", padx=(0, 10))
        left_wrap.pack_propagate(False)

        self._scroll = ScrollFrame(left_wrap, bg=BG)
        self._scroll.pack(fill="both", expand=True)
        p = self._scroll.inner

        # Right panel
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        self._build_left(p)
        self._build_right(right)

    def _build_left(self, p):
        # ── Start / Stop row
        ctrl = tk.Frame(p, bg=BG)
        ctrl.pack(fill="x", pady=(0, 10))
        self._start_btn = self._btn(ctrl, "▶  Start Watching",
                                    self._start, SUCCESS, "black")
        self._start_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._stop_btn = self._btn(ctrl, "■  Stop", self._stop, DANGER, "white")
        self._stop_btn.pack(side="left", fill="x", expand=True)
        self._stop_btn.configure(state="disabled")

        # ── Stats
        sc = self._card(p, "STATS")
        sr = tk.Frame(sc, bg=BG2)
        sr.pack(fill="x")
        self._stat(sr, "Clicks", self._count_str, SUCCESS)
        self._stat(sr, "Last click", self._last_str, ACCENT2)

        # ── Region
        rc = self._card(p, "WATCH REGION")
        self._region_lbl = tk.Label(rc, text="", font=F_MONO,
                                    bg=BG2, fg=ACCENT2)
        self._region_lbl.pack(pady=(0, 4))
        self._region_warn = tk.Label(rc, text="", font=F_SMALL,
                                     bg=BG2, fg=WARNING, wraplength=280)
        self._region_warn.pack(pady=(0, 4))
        rr = tk.Frame(rc, bg=BG2)
        rr.pack(fill="x")
        self._btn(rr, "⊹  Select Region", self._select_region, ACCENT, "white")\
            .pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._btn(rr, "⛶  Full Screen", self._full_screen, BG4, ACCENT3)\
            .pack(side="left", fill="x", expand=True)

        # ── Templates
        tc = self._card(p, "BUTTON TEMPLATES  —  primary  ⚡ fast")
        self._btn(tc, "+  Capture Template", self._capture_template,
                  SUCCESS2, "white").pack(fill="x", pady=(0, 8))
        self._tmpl_frame = tk.Frame(tc, bg=BG2)
        self._tmpl_frame.pack(fill="x")

        # ── Settings
        sc2 = self._card(p, "SETTINGS")
        self._kw_var = self._entry_row(sc2, "Keywords (csv)", "keyword")
        self._iv_var = self._slider_row(sc2, "Interval (s)", "interval",
                                        0.05, 5.0, 0.05)
        self._cd_var = self._slider_row(sc2, "Cooldown (s)", "cooldown",
                                        0.5, 30.0, 0.5)
        self._cf_var = self._slider_row(sc2, "Confidence %", "confidence",
                                        5, 95, 1)
        self._tm_var = self._slider_row(sc2, "Match thresh", "tmatch_thresh",
                                        0.40, 0.99, 0.01)

        # Offset row
        row = tk.Frame(sc2, bg=BG2)
        row.pack(fill="x", pady=(6, 0))
        tk.Label(row, text="Click offset X/Y", font=F_BODY,
                 bg=BG2, fg=SUBTEXT, width=16, anchor="w").pack(side="left")
        self._ox = tk.StringVar(value=str(self.settings.get("click_offset_x", 0)))
        self._oy = tk.StringVar(value=str(self.settings.get("click_offset_y", 0)))
        for key, var in [("click_offset_x", self._ox), ("click_offset_y", self._oy)]:
            e = tk.Entry(row, textvariable=var, bg=BG3, fg=TEXT,
                         insertbackground=ACCENT2, relief="flat",
                         font=F_MONO, width=5,
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=ACCENT)
            e.pack(side="left", padx=(0, 6))
            var.trace_add("write", lambda *a, k=key, v=var: self._sync(k, v))

        # Spacer at bottom of scroll area
        tk.Frame(p, bg=BG, height=16).pack()

    def _build_right(self, p):
        # Live preview
        pc = self._card_r(p, "LIVE PREVIEW")
        pc.pack(fill="both", expand=True, pady=(0, 8))
        self._canvas = tk.Canvas(pc, bg="#08090f", highlightthickness=0)
        self._canvas.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        # placeholder text
        self._canvas.bind("<Configure>", self._draw_placeholder)

        # Activity log
        lc = self._card_r(p, "ACTIVITY LOG")
        lc.pack(fill="both", expand=True, pady=(0, 4))
        log_frame = tk.Frame(lc, bg="#08090f")
        log_frame.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        self._log_w = tk.Text(log_frame, bg="#08090f", fg=TEXT,
                              font=F_MONO, state="disabled",
                              relief="flat", wrap="word",
                              insertbackground=ACCENT2, padx=8, pady=6)
        sb = tk.Scrollbar(log_frame, command=self._log_w.yview,
                          bg=BG3, troughcolor=BG2, width=8, relief="flat")
        self._log_w.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log_w.pack(fill="both", expand=True)
        self._log_w.tag_config("success", foreground=SUCCESS)
        self._log_w.tag_config("warn",    foreground=WARNING)
        self._log_w.tag_config("error",   foreground=DANGER)
        self._log_w.tag_config("info",    foreground=SUBTEXT)
        self._log_w.tag_config("dim",     foreground=DIMTEXT)

        # Test OCR button
        self._btn(p, "🔍  Test OCR on Region", self._test_ocr, BG4, WARNING)\
            .pack(fill="x", pady=(0, 0))

    def _draw_placeholder(self, e=None):
        if self._prev_img:
            return
        self._canvas.delete("placeholder")
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw < 2 or ch < 2:
            return
        self._canvas.create_text(cw//2, ch//2,
                                 text="Preview will appear here\nwhen watching starts",
                                 fill=DIMTEXT, font=F_BODY, justify="center",
                                 tags="placeholder")

    # ── Widget helpers ─────────────────────────────────────────────────────
    def _card(self, parent, title):
        outer = tk.Frame(parent, bg=BG2,
                         highlightbackground=BORDER, highlightthickness=1)
        outer.pack(fill="x", pady=(0, 8))
        hf = tk.Frame(outer, bg=BG3)
        hf.pack(fill="x")
        tk.Label(hf, text=title, font=F_MICRO, bg=BG3,
                 fg=DIMTEXT, padx=12, pady=6).pack(anchor="w")
        inner = tk.Frame(outer, bg=BG2)
        inner.pack(fill="both", expand=True, padx=12, pady=10)
        # mousewheel propagation to scroller
        for w in [outer, hf, inner]:
            self._scroll.bind_mousewheel(w)
        return inner

    def _card_r(self, parent, title):
        outer = tk.Frame(parent, bg=BG2,
                         highlightbackground=BORDER, highlightthickness=1)
        hf = tk.Frame(outer, bg=BG3)
        hf.pack(fill="x")
        tk.Label(hf, text=title, font=F_MICRO, bg=BG3,
                 fg=DIMTEXT, padx=12, pady=6).pack(anchor="w")
        inner = tk.Frame(outer, bg=BG2)
        inner.pack(fill="both", expand=True)
        return outer

    def _btn(self, parent, text, cmd, bg=BG4, fg=TEXT, pady=8):
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                      font=F_BODY, activebackground=ACCENT,
                      activeforeground="white", relief="flat",
                      cursor="hand2", padx=10, pady=pady, bd=0)
        orig = bg
        b.bind("<Enter>", lambda e, b=b, o=orig: b.configure(
            bg=self._lighten(o)))
        b.bind("<Leave>", lambda e, b=b, o=orig: b.configure(bg=o))
        return b

    def _lighten(self, hex_color):
        """Return a slightly lighter version of hex_color."""
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            r = min(255, r + 25)
            g = min(255, g + 25)
            b = min(255, b + 25)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    def _entry_row(self, parent, label, key):
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill="x", pady=(0, 6))
        tk.Label(row, text=label, font=F_BODY, bg=BG2, fg=SUBTEXT,
                 width=14, anchor="w").pack(side="left")
        var = tk.StringVar(value=str(self.settings.get(key, "")))
        e = tk.Entry(row, textvariable=var, bg=BG3, fg=TEXT,
                     insertbackground=ACCENT2, relief="flat",
                     font=F_MONO,
                     highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=ACCENT)
        e.pack(side="left", fill="x", expand=True)
        var.trace_add("write", lambda *a: self._sync(key, var))
        self._scroll.bind_mousewheel(row)
        self._scroll.bind_mousewheel(e)
        return var

    def _slider_row(self, parent, label, key, lo, hi, res):
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill="x", pady=(0, 8))
        tk.Label(row, text=label, font=F_BODY, bg=BG2, fg=SUBTEXT,
                 width=14, anchor="w").pack(side="left")

        cur = float(self.settings.get(key, lo))
        val_lbl = tk.Label(row, text=f"{cur:.2f}", font=F_MONO,
                           bg=BG2, fg=ACCENT2, width=6, anchor="e")
        val_lbl.pack(side="right")

        sl_frame = tk.Frame(row, bg=BG2)
        sl_frame.pack(side="left", fill="x", expand=True, padx=(6, 4))

        def on_change(v, k=key, lbl=val_lbl):
            decimals = 0 if res >= 1 else (2 if res < 0.1 else 1)
            lbl.configure(text=f"{v:.{decimals}f}")
            self.settings[k] = v
            save_settings(self.settings)

        sl = DarkSlider(sl_frame, lo=lo, hi=hi, value=cur,
                        resolution=res, on_change=on_change)
        sl.pack(fill="x", expand=True, pady=4)
        self._scroll.bind_mousewheel(row)
        self._scroll.bind_mousewheel(sl)
        return sl

    def _stat(self, parent, label, var, color):
        f = tk.Frame(parent, bg=BG2, pady=6)
        f.pack(side="left", expand=True, fill="x")
        tk.Label(f, text=label, font=F_MICRO, bg=BG2, fg=DIMTEXT).pack()
        tk.Label(f, textvariable=var, font=F_NUM, bg=BG2, fg=color).pack()

    def _sync(self, key, var):
        try:
            raw = var.get()
            d   = DEFAULTS.get(key)
            self.settings[key] = type(d)(raw) if isinstance(d, (int, float)) else raw
            save_settings(self.settings)
        except Exception:
            pass

    # ── Region ─────────────────────────────────────────────────────────────
    def _full_screen(self):
        s = pyautogui.size()
        self._on_region({"x": 0, "y": 0, "w": s.width, "h": s.height})

    def _select_region(self):
        self.withdraw()
        self.after(300, self._open_region_sel)

    def _open_region_sel(self):
        self._sel = RegionSelector(self, self._on_region)
        self._sel.bind("<Destroy>", lambda e: self.after(100, self._show))

    def _on_region(self, r):
        self.settings["region"] = r
        save_settings(self.settings)
        self._refresh_region_lbl()
        self._show()
        self._log(f"Region set: {r['w']}×{r['h']} at ({r['x']},{r['y']})")

    def _show(self):
        if not self.winfo_viewable():
            self.deiconify()

    def _refresh_region_lbl(self):
        r = self.settings["region"]
        self._region_lbl.configure(
            text=f"x={r['x']}  y={r['y']}   {r['w']} × {r['h']} px")
        big = r["w"] > 1500 or r["h"] > 800
        self._region_warn.configure(
            text=("⚠  Large region — select a smaller area for best speed") if big else "")

    # ── Templates ──────────────────────────────────────────────────────────
    def _capture_template(self):
        self.withdraw()
        self.after(300, self._open_tmpl_sel)

    def _open_tmpl_sel(self):
        self._tsel = TemplateSelector(self, self._save_template)
        self._tsel.bind("<Destroy>", lambda e: self.after(100, self._show))

    def _save_template(self, crop):
        self._show()
        name = simpledialog.askstring(
            "Template Name",
            "Enter a name for this template (e.g. Retry, Accept all):",
            initialvalue="Retry", parent=self)
        if not name:
            return
        safe = re.sub(r'[^\w\s-]', '', name).strip().replace(" ", "_")
        path = os.path.join(TEMPLATES_DIR, f"{safe}.png")
        try:
            crop.save(path)
            self._log(f"Template saved: {safe}.png ({crop.width}×{crop.height}px)", "success")
            self._refresh_templates()
        except Exception as exc:
            self._log(f"Save failed: {exc}", "error")

    def _refresh_templates(self):
        for w in self._tmpl_frame.winfo_children():
            w.destroy()
        templates = load_templates()
        if not templates:
            tk.Label(self._tmpl_frame,
                     text="No templates yet.\nCapture one to enable fast matching.",
                     font=F_SMALL, bg=BG2, fg=DIMTEXT,
                     justify="left").pack(anchor="w", pady=4)
            return
        for name, img in templates.items():
            row = tk.Frame(self._tmpl_frame, bg=BG3,
                           highlightbackground=BORDER, highlightthickness=1)
            row.pack(fill="x", pady=3)
            thumb = img.copy()
            thumb.thumbnail((60, 28), Image.LANCZOS)
            photo = ImageTk.PhotoImage(thumb)
            lbl = tk.Label(row, image=photo, bg=BG3)
            lbl.image = photo
            lbl.pack(side="left", padx=(6, 8), pady=4)
            tk.Label(row, text=name.replace("_", " "),
                     font=F_BODY, bg=BG3, fg=TEXT)\
              .pack(side="left", expand=True, anchor="w")
            self._btn(row, "×", lambda n=name: self._del_template(n),
                      DANGER2, "white", pady=3)\
              .pack(side="right", padx=6, pady=4)

    def _del_template(self, name):
        p = os.path.join(TEMPLATES_DIR, f"{name}.png")
        try:
            os.remove(p)
            self._log(f"Template removed: {name}", "warn")
            self._refresh_templates()
        except Exception as exc:
            self._log(f"Error: {exc}", "error")

    # ── Start / Stop ───────────────────────────────────────────────────────
    def _start(self):
        if self._running:
            return
        self._running = True
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        kw = self.settings.get("keyword", "Retry")
        tmpl_count = len(load_templates())
        self._log(f"Started — templates: {tmpl_count}  keywords: {kw}")
        self._set_dot(True)
        self._thread = MonitorThread(
            settings   = self.settings,
            on_click   = lambda label, cx, cy, bb: self.after(
                0, self._on_click, label, cx, cy, bb),
            on_status  = lambda s: self.after(0, self._set_status, s),
            on_preview = lambda img: self.after(0, self._show_preview, img),
        )
        self._thread.start()

    def _stop(self):
        if self._thread:
            self._thread.stop()
            self._thread = None
        self._running = False
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._set_status("Idle")
        self._set_dot(False)
        self._log("Stopped", "dim")

    def _set_dot(self, active):
        self._dot.itemconfig("dot", fill=SUCCESS if active else DIMTEXT)

    # ── Callbacks ──────────────────────────────────────────────────────────
    def _on_click(self, label, cx, cy, bbox):
        self._clicks += 1
        self._count_str.set(str(self._clicks))
        self._last_str.set(time.strftime("%H:%M:%S"))
        self._log(f"CLICK  {label}  →  ({cx}, {cy})", "success")
        self._pill.configure(bg=SUCCESS, fg="black")
        self._status_str.set("CLICKED!")
        self.after(1500, lambda: self._set_status("watching"))

    def _set_status(self, s):
        self._status_str.set(s)
        if s in ("watching", "Idle"):
            self._pill.configure(bg=BG4, fg=SUBTEXT)
        elif "ERR" in s:
            self._pill.configure(bg=DANGER, fg="white")
            self._log(s, "error")
        elif "cooldown" in s:
            self._pill.configure(bg=WARNING, fg="black")

    def _show_preview(self, img, bbox=None):
        try:
            cw = max(self._canvas.winfo_width(),  10)
            ch = max(self._canvas.winfo_height(), 10)
            thumb = img.copy()
            thumb.thumbnail((cw, ch), Image.LANCZOS)
            if bbox:
                sx = thumb.width / img.width
                sy = thumb.height / img.height
                draw = ImageDraw.Draw(thumb)
                bx = int(bbox[0]*sx); by = int(bbox[1]*sy)
                bw = int(bbox[2]*sx); bh = int(bbox[3]*sy)
                draw.rectangle([bx-3, by-3, bx+bw+3, by+bh+3],
                               outline=SUCCESS, width=2)
            self._prev_img = ImageTk.PhotoImage(thumb)
            self._canvas.delete("all")
            self._canvas.create_image(cw//2, ch//2, anchor="center",
                                      image=self._prev_img)
        except Exception:
            pass

    def _log(self, msg, tag="info"):
        ts = time.strftime("%H:%M:%S")
        self._log_w.configure(state="normal")
        self._log_w.insert("end", f"[{ts}]  {msg}\n", tag)
        self._log_w.see("end")
        self._log_w.configure(state="disabled")

    def _test_ocr(self):
        r = self.settings["region"]
        with mss.mss() as sct:
            shot = sct.grab({"left": r["x"], "top": r["y"],
                             "width": r["w"], "height": r["h"]})
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        if not TESSERACT_EXE:
            self._log("Tesseract not installed — OCR unavailable", "error")
            return
        try:
            data = pytesseract.image_to_data(
                img, output_type=pytesseract.Output.DICT,
                config="--psm 11 --oem 3")
            words = [(t, int(c)) for t, c in zip(data["text"], data["conf"])
                     if t.strip() and str(c).lstrip("-").isdigit() and int(c) > 0]
            self._log(f"OCR words: {words[:20]}", "info")
        except Exception as exc:
            self._log(f"OCR error: {exc}", "error")

    def on_close(self):
        self._stop()
        self.destroy()


# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
