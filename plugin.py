import base64
import html
import os
import re
import struct
import subprocess
import tempfile
import textwrap
import time
from urllib.parse import quote, unquote

import sublime
import sublime_plugin

SETTINGS_FILE = "MarkdownInline.sublime-settings"
SCHEME = "Packages/MarkdownInline/Markdown Inline.sublime-color-scheme"
MD_SELECTOR = "text.html.markdown"
STOCK_SYNTAX = "Packages/Markdown/Markdown.sublime-syntax"
SYNTAX = "Packages/MarkdownInline/Markdown Inline.sublime-syntax"

FENCE_RE = re.compile(r"^\s*(```|~~~)")
TASK_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(\[[ xX]\])")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING_RE = re.compile(r"^\s{0,3}#{1,2}\s+\S")
HR_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
DATA_URI_RE = re.compile(r"^data:image/(png|jpe?g|gif);base64,(.+)$", re.IGNORECASE | re.DOTALL)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif"}

CONT = "\u21b3"  # marks a continuation line of a wrapped table row (first cell)

_phantom_sets = {}  # view id -> PhantomSet
_tokens = {}  # view id -> int, used to debounce
_active_tables = {}  # view id -> set of start offsets of tables the cursor was in
_dirty_tables = {}  # view id -> set of start offsets of tables edited while the cursor was in
_last_change = {}  # view id -> last change_count seen by render()
_saved_tables = {}  # view id -> set of table texts at the last load or save


def plugin_loaded():
    for window in sublime.windows():
        for view in window.views():
            if is_markdown(view):
                snapshot_tables(view)
            schedule(view, 0)


def plugin_unloaded():
    for window in sublime.windows():
        for view in window.views():
            clear(view)


def snapshot_tables(view):
    _saved_tables[view.id()] = {view.substr(r) for r, _ in find_blocks(view)[0]}


def settings():
    return sublime.load_settings(SETTINGS_FILE)


def is_markdown(view):
    return bool(view.match_selector(0, MD_SELECTOR))


def is_enabled(view):
    if not is_markdown(view):
        return False
    return view.settings().get("markdown_inline.enabled", settings().get("auto_enable", True))


def clear(view):
    vid = view.id()
    ps = _phantom_sets.pop(vid, None)
    if ps:
        ps.update([])
    if view.settings().get("color_scheme") == SCHEME:
        view.settings().erase("color_scheme")
    if view.settings().get("syntax") == SYNTAX:
        view.assign_syntax(STOCK_SYNTAX)


def schedule(view, delay=None):
    vid = view.id()
    token = _tokens.get(vid, 0) + 1
    _tokens[vid] = token
    if delay is None:
        delay = settings().get("debounce_ms", 150)

    def run():
        if _tokens.get(vid) == token:
            sublime.set_timeout(lambda: render(view), 0)

    sublime.set_timeout_async(run, delay)


# ---------------------------------------------------------------- parsing

def inline_html(text):
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"(?<![*\w])\*([^*]+)\*(?!\w)", r"<i>\1</i>", out)
    return out


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def is_cont(line):
    """True if the line's first cell starts with the continuation marker."""
    return line.lstrip().startswith("|") and line.lstrip()[1:].lstrip().startswith(CONT)


def table_rows(lines):
    """Logical rows (lists of cells); a line whose first cell starts with CONT continues the previous row."""
    rows = []
    for line in lines:
        cells = split_row(line)
        if rows and len(rows) != 2 and cells and cells[0].startswith(CONT):
            cur = rows[-1]
            cells[0] = cells[0][len(CONT):].strip()
            for c, text in enumerate(cells):
                if c < len(cur):
                    cur[c] = (cur[c] + " " + text).strip()
                else:
                    cur.append(text)
        else:
            rows.append(cells)
    return rows


def table_html(rows, width_px=None):
    header = rows[0]
    aligns = []
    for cell in rows[1]:
        if cell.startswith(":") and cell.endswith(":"):
            aligns.append("center")
        elif cell.endswith(":"):
            aligns.append("right")
        else:
            aligns.append("left")

    rows = [header] + rows[2:]
    ncols = max(len(r) for r in rows)
    # proportional column widths from the longest cell (capped), so long text wraps
    longest = [max([min(len(r[c]), 60) for r in rows if c < len(r)] + [1]) for c in range(ncols)]
    total = float(sum(longest))
    pcts = [max(8, round(100 * n / total)) for n in longest]
    scale = 100.0 / sum(pcts)
    pcts = [max(1, int(p * scale)) for p in pcts]

    def row(cells, tag):
        tds = []
        for i in range(ncols):
            c = cells[i] if i < len(cells) else ""
            a = aligns[i] if i < len(aligns) else "left"
            tds.append('<{0} width="{3}%" style="text-align:{1}">{2}</{0}>'.format(
                tag, a, inline_html(c), pcts[i]))
        return "<tr>" + "".join(tds) + "</tr>"

    body = "".join(row(r, "td") for r in rows[1:])
    style = ' style="width:{}px"'.format(int(width_px)) if width_px else ""
    return '<table class="md"{}>{}{}</table>'.format(style, row(rows[0], "th"), body)


def table_width_px(view):
    margin = settings().get("table_margin_px", 40)
    avail = max(200, view.viewport_extent()[0] - margin)
    wrap = view.settings().get("wrap_width") or 0
    if wrap > 0:
        return min(avail, wrap * view.em_width())
    return avail


def table_max_chars(view):
    gap = settings().get("table_gap_chars", 12)
    wrap = view.settings().get("wrap_width") or 0
    if wrap > 0:
        return max(40, int(wrap) - gap)
    return max(40, int(table_width_px(view) / max(view.em_width(), 1)) - gap)


def fit_widths(natural, floors, avail):
    """Column widths that fit `avail` chars where possible.

    Narrow columns keep their natural width (max-min fairness), wide ones share
    the rest proportionally. No column goes below its floor (its longest
    unbreakable word), so pipes stay aligned even if the row ends up wider."""
    n = len(natural)
    widths = [None] * n
    remaining = list(range(n))
    left = avail
    while remaining:
        share = left / float(len(remaining))
        fits = [c for c in remaining if natural[c] <= share]
        if not fits:
            break
        for c in fits:
            widths[c] = natural[c]
            left -= natural[c]
            remaining.remove(c)
    if remaining:
        total = float(sum(natural[c] for c in remaining))
        for c in remaining:
            widths[c] = max(floors[c], int(left * natural[c] / total))
    return widths


def align_table(rows, max_chars=None):
    """Return the table as aligned physical lines.

    If the rows would exceed max_chars, long cells are wrapped over several
    physical lines; continuation lines start their first cell with CONT so
    table_rows() can join them back. Keeps :--/--: alignment markers."""
    rows = [list(r) for r in rows]
    ncols = max(len(r) for r in rows)
    for r in rows:
        r.extend([""] * (ncols - len(r)))
    natural = [max(3, max(len(r[c]) for k, r in enumerate(rows) if k != 1)) for c in range(ncols)]
    overhead = 3 * ncols + 1
    wrapped = bool(max_chars) and sum(natural) + overhead > max_chars
    if wrapped:
        body = [r for k, r in enumerate(rows) if k != 1]  # the separator row's dashes are not words
        floors = [max([3] + [len(w) for r in body for w in r[c].split()])
                  + (len(CONT) + 1 if c == 0 else 0) for c in range(ncols)]
        widths = fit_widths(natural, floors, max(ncols * 3, max_chars - overhead))
    else:
        widths = natural

    marks = rows[1]
    out = []
    for k, r in enumerate(rows):
        if k == 1:
            cells = []
            for c, cell in enumerate(r):
                left, right = cell.startswith(":"), cell.endswith(":")
                cells.append((":" if left else "") + "-" * (widths[c] - left - right) + (":" if right else ""))
            out.append("| " + " | ".join(cells) + " |")
            continue
        parts = [textwrap.wrap(cell, widths[c] - (len(CONT) + 1 if c == 0 else 0),
                               break_long_words=False, break_on_hyphens=False) or [""]
                 if wrapped else [cell] for c, cell in enumerate(r)]
        height = max(len(p) for p in parts)
        for h in range(height):
            cells = []
            for c, p in enumerate(parts):
                text = p[h] if h < len(p) else ""
                if c == 0 and h > 0:
                    text = (CONT + " " + text).rstrip()
                w = widths[c]
                if marks[c].endswith(":") and not marks[c].startswith(":"):
                    cells.append(text.rjust(w))
                elif marks[c].startswith(":") and marks[c].endswith(":"):
                    cells.append(text.center(w))
                else:
                    cells.append(text.ljust(w))
            out.append("| " + " | ".join(cells) + " |")
    return out


def find_blocks(view):
    """Return (tables, tasks, images, rules, headings) found outside fenced code."""
    lines = view.lines(sublime.Region(0, view.size()))
    max_lines = settings().get("max_lines", 5000)
    if len(lines) > max_lines:
        return [], [], [], [], []
    texts = [view.substr(r) for r in lines]

    tables, tasks, images, rules, headings = [], [], [], [], []
    in_fence = False
    i = 0
    while i < len(lines):
        text = texts[i]
        if FENCE_RE.match(text):
            in_fence = not in_fence
            i += 1
            continue
        if in_fence:
            i += 1
            continue

        if "|" in text:
            h = i
            while h + 1 < len(lines) and is_cont(texts[h + 1]):
                h += 1
            if h + 1 < len(lines) and "-" in texts[h + 1] and TABLE_SEP_RE.match(texts[h + 1]) \
                    and "|" in texts[h] + texts[h + 1]:
                j = h + 2
                while j < len(lines) and "|" in texts[j] and texts[j].strip():
                    j += 1
                region = sublime.Region(lines[i].begin(), lines[j - 1].end())
                tables.append((region, table_rows(texts[i:j])))
                i = j
                continue

        m = TASK_RE.match(text)
        if m:
            tasks.append((lines[i].begin() + m.start(1), m.group(1)[1] != " ", lines[i]))
        for im in IMAGE_RE.finditer(text):
            images.append((lines[i].end(), im.group(1), im.group(2), lines[i]))
        if HR_RE.match(text):
            rules.append(lines[i])
        elif HEADING_RE.match(text):
            headings.append(lines[i])
        i += 1
    return tables, tasks, images, rules, headings


def image_size(path):
    """(width, height) from the file header, or None. PNG, GIF and JPEG only."""
    try:
        with open(path, "rb") as f:
            head = f.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return struct.unpack("<HH", head[6:10])
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    b = f.read(1)
                    while b and b != b"\xff":
                        b = f.read(1)
                    while b == b"\xff":
                        b = f.read(1)
                    if not b:
                        return None
                    marker = b[0]
                    if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                        h, w = struct.unpack(">HH", f.read(7)[3:7])
                        return w, h
                    if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                        continue
                    (length,) = struct.unpack(">H", f.read(2))
                    f.seek(length - 2, 1)
    except (OSError, struct.error):
        pass
    return None


def resolve_image(view, src):
    """Return (file URI, filesystem path) for a local image, else None."""
    if src.startswith(("http://", "https://", "data:")):
        return None  # minihtml cannot fetch remote images
    if src.startswith("file://"):
        path = unquote(src[7:])
    else:
        path = os.path.expanduser(unquote(src))
    if not os.path.isabs(path):
        base = os.path.dirname(view.file_name() or "")
        if not base:
            return None
        path = os.path.join(base, path)
    if not os.path.isfile(path):
        return None
    return "file://" + quote(path.replace(os.sep, "/")), path


# -------------------------------------------------------------- rendering

CSS = """
<style>
  table.md { border-collapse: collapse; margin: 0.4rem 0; }
  table.md th, table.md td { border: 1px solid color(var(--foreground) alpha(0.25)); padding: 2px 8px; }
  table.md th { font-weight: bold; }
  code { background-color: color(var(--foreground) alpha(0.12)); }
  a.box { text-decoration: none; }
  hr.md { color: color(var(--foreground) alpha(0.3)); }
</style>
"""


def intersects_selection(view, region):
    for sel in view.sel():
        if sel.intersects(region) or region.contains(sel.b) or region.begin() == sel.b == region.end():
            return True
    return False


def render(view):
    if not view.is_valid():
        return
    vid = view.id()
    if not is_enabled(view):
        clear(view)
        return

    if settings().get("apply_color_scheme", True) \
            and view.settings().get("color_scheme") != SCHEME:
        view.settings().set("color_scheme", SCHEME)
    if settings().get("apply_syntax", True) and view.settings().get("syntax") == STOCK_SYNTAX \
            and sublime.find_resources("Markdown Inline.sublime-syntax"):
        view.assign_syntax(SYNTAX)

    ps = _phantom_sets.get(vid)
    if ps is None:
        ps = _phantom_sets[vid] = sublime.PhantomSet(view, "markdown_inline")

    tables, tasks, images, rules, headings = find_blocks(view)
    phantoms = []

    now_in = {r.begin() for r, _ in tables if intersects_selection(view, r)}
    count = view.change_count()
    last = _last_change.get(vid)
    _last_change[vid] = count
    prev_dirty = _dirty_tables.get(vid, set())
    # a table is dirty once the text changed while the cursor was inside it
    dirty = (prev_dirty & now_in) | (now_in if last is not None and count != last else set())
    left = _active_tables.get(vid, set()) - now_in
    _active_tables[vid] = now_in
    _dirty_tables[vid] = dirty
    if left and settings().get("align_tables_on_leave", True) and not view.is_read_only():
        starts = {r.begin() for r, _ in tables}
        for start in sorted(left & starts & prev_dirty, reverse=True):
            view.run_command("markdown_inline_align_table", {"point": start})

    def on_nav(href):
        if href.startswith("toggle:"):
            view.run_command("markdown_inline_toggle_task", {"point": int(href[7:])})

    if settings().get("render_tables", True):
        width_px = table_width_px(view)
        for region, rows in tables:
            if intersects_selection(view, region):
                continue
            phantoms.append(sublime.Phantom(
                sublime.Region(region.end(), region.end()),
                CSS + table_html(rows, width_px),
                sublime.LAYOUT_BLOCK,
            ))

    for point, checked, line in tasks:
        if intersects_selection(view, line):
            continue
        glyph, color = ("&#9745;", "#99c794") if checked else ("&#9744;", "#f9c761")
        phantoms.append(sublime.Phantom(
            sublime.Region(point, point),
            CSS + '<a class="box" href="toggle:{}" style="color:{}">{}&nbsp;</a>'.format(point, color, glyph),
            sublime.LAYOUT_INLINE,
            on_nav,
        ))

    max_w = settings().get("image_max_width", 600)
    for point, alt, src, line in images:
        found = resolve_image(view, src)
        if not found:
            continue
        uri, path = found
        size = image_size(path)
        if size and size[0] > 0 and size[1] > 0:
            w = min(size[0], max_w)
            h = max(1, round(size[1] * w / size[0]))
        else:
            w, h = max_w, round(max_w * 0.6)  # unknown format: placeholder box
        phantoms.append(sublime.Phantom(
            sublime.Region(point, point),
            '<img src="{}" width="{}" height="{}" alt="{}">'.format(uri, w, h, html.escape(alt)),
            sublime.LAYOUT_BLOCK,
        ))

    if settings().get("heading_rules", True):
        for line in headings:
            if intersects_selection(view, line):
                continue
            phantoms.append(sublime.Phantom(
                sublime.Region(line.end(), line.end()),
                CSS + '<hr class="md">',
                sublime.LAYOUT_BLOCK,
            ))

    for line in rules:
        if intersects_selection(view, line):
            continue
        phantoms.append(sublime.Phantom(
            sublime.Region(line.end(), line.end()),
            CSS + '<hr class="md">',
            sublime.LAYOUT_BLOCK,
        ))

    ps.update(phantoms)


# ------------------------------------------------------------ paste image

def sniff_image(data):
    """Return the file extension for known image bytes, else None."""
    if not data:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return None


def clipboard_text_image(text):
    """(bytes, ext) if the clipboard text is an image path or data URI, else None."""
    text = (text or "").strip()
    if not text:
        return None
    m = DATA_URI_RE.match(text)
    if m:
        try:
            data = base64.b64decode(m.group(2))
        except (ValueError, TypeError):
            return None
        ext = ".jpg" if m.group(1).lower() in ("jpg", "jpeg") else "." + m.group(1).lower()
        return (data, ext) if sniff_image(data) else None
    if len(text) < 4096 and "\n" not in text:
        path = unquote(text[7:]) if text.startswith("file://") else os.path.expanduser(unquote(text))
        if os.path.isabs(path) and os.path.splitext(path)[1].lower() in IMAGE_EXTS and os.path.isfile(path):
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                return None
            ext = sniff_image(data)
            return (data, ext) if ext else None
    return None


class ToolMissing(Exception):
    """Raised when a required clipboard executable is not installed."""

    def __init__(self, name):
        super().__init__(name)
        self.name = name


def run_bytes(cmd):
    """(bytes, ext) from cmd's stdout (list, or shell string), else None.

    Raises ToolMissing when the executable cannot be found."""
    shell = isinstance(cmd, str)
    parts = cmd.split() if shell else cmd
    tool = parts[0] if parts else cmd
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=10, shell=shell)
    except FileNotFoundError:
        raise ToolMissing(tool)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode == 127 and shell:
        raise ToolMissing(tool)
    if proc.returncode != 0:
        return None
    ext = sniff_image(proc.stdout)
    return (proc.stdout, ext) if ext else None


def unlink(path):
    try:
        os.remove(path)
    except OSError:
        pass


def macos_osascript_image():
    """(bytes, ext) from the macOS pasteboard via osascript, else None.

    No third-party tools: coerces the clipboard to PNG, falling back to TIFF
    (converted to PNG with the built-in sips). Call from a worker thread."""
    osascript, sips = "/usr/bin/osascript", "/usr/bin/sips"
    for coerce, ext in (("\u00abclass PNGf\u00bb", ".png"),
                        ("\u00abclass TIFF\u00bb", ".tiff"),
                        ("TIFF picture", ".tiff")):
        fd, tmp = tempfile.mkstemp(suffix=ext)
        os.close(fd)
        script = (
            "set theImage to (the clipboard as {0})\n"
            "set theFile to (open for access POSIX file \"{1}\" with write permission)\n"
            "set eof theFile to 0\n"
            "write theImage to theFile\n"
            "close access theFile"
        ).format(coerce, tmp)
        try:
            proc = subprocess.run([osascript, "-e", script], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=10)
            if proc.returncode != 0 or not os.path.getsize(tmp):
                unlink(tmp)
                continue
            if ext == ".tiff":
                png = tmp + ".png"
                try:
                    subprocess.run([sips, "-s", "format", "png", tmp, "--out", png],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=10)
                except (OSError, subprocess.SubprocessError):
                    pass
                unlink(tmp)
                tmp = png
            with open(tmp, "rb") as f:
                data = f.read()
        except (OSError, subprocess.SubprocessError):
            data = b""
        unlink(tmp)
        got = sniff_image(data)
        if got:
            return data, got
    return None


def clipboard_image_bytes():
    """((bytes, ext), error) for a raw image on the system clipboard.

    Sublime's clipboard API is text-only, so raw images require a platform
    tool. Returns (None, reason) when every candidate tool is missing, or
    (None, None) when tools ran but found no image. Call from a worker thread."""
    plat = sublime.platform()
    custom = (settings().get("paste_image_command", "") or "").strip()

    if custom:
        try:
            found = run_bytes(custom)
        except ToolMissing as e:
            return None, "{} not found".format(e.name)
        return (found, None) if found else (None, None)

    candidates = []
    if plat == "linux":
        if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
            candidates.append(("wl-paste", lambda: run_bytes(
                ["wl-paste", "--no-newline", "--type", "image/png"])))
        candidates.append(("xclip", lambda: run_bytes(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"])))
        candidates.append(("xsel", lambda: run_bytes(["xsel", "--clipboard", "--output"])))
    elif plat == "osx":
        candidates.append(("pngpaste", lambda: run_bytes(["pngpaste", "-"])))
        if os.path.exists("/usr/bin/osascript"):
            candidates.append(("osascript", macos_osascript_image))
    elif plat == "windows":
        candidates.append(("powershell", lambda: run_bytes(
            ["powershell", "-NoProfile", "-Command",
             "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
             "$img=[Windows.Forms.Clipboard]::GetImage();"
             "if($img){$ms=New-Object IO.MemoryStream;"
             "$img.Save($ms,[Drawing.Imaging.ImageFormat]::Png);"
             "$out=[Console]::OpenStandardOutput();$b=$ms.ToArray();"
             "$out.Write($b,0,$b.Length);$out.Flush()}"])))

    missing, ran = [], False
    for tool, extract in candidates:
        try:
            found = extract()
        except ToolMissing:
            missing.append(tool)
            continue
        ran = True
        if found:
            return found, None
    if not ran and missing:
        return None, "{} not found".format(", ".join(missing))
    return None, None


# ---------------------------------------------------------------- plugin

class MarkdownInlineListener(sublime_plugin.EventListener):
    def on_load_async(self, view):
        if is_markdown(view):
            snapshot_tables(view)
        schedule(view, 0)

    def on_activated_async(self, view):
        schedule(view, 0)

    def on_modified_async(self, view):
        if is_enabled(view):
            schedule(view)

    def on_selection_modified_async(self, view):
        if is_enabled(view):
            schedule(view, 60)

    def on_pre_save(self, view):
        if is_markdown(view) and settings().get("align_tables_on_save", True):
            view.run_command("markdown_inline_align_table", {"modified": True})

    def on_post_save_async(self, view):
        if is_markdown(view):
            snapshot_tables(view)

    def on_pre_close(self, view):
        clear(view)
        _tokens.pop(view.id(), None)
        _active_tables.pop(view.id(), None)
        _dirty_tables.pop(view.id(), None)
        _last_change.pop(view.id(), None)
        _saved_tables.pop(view.id(), None)


class MarkdownInlineToggleCommand(sublime_plugin.TextCommand):
    def is_enabled(self):
        return is_markdown(self.view)

    def run(self, edit):
        view = self.view
        now = not is_enabled(view)
        view.settings().set("markdown_inline.enabled", now)
        if now:
            render(view)
        else:
            clear(view)


class MarkdownInlineToggleTaskCommand(sublime_plugin.TextCommand):
    def run(self, edit, point):
        view = self.view
        line = view.line(point)
        text = view.substr(line)
        m = TASK_RE.match(text)
        if not m:
            return
        pos = line.begin() + m.start(1) + 1
        new = " " if text[m.start(1) + 1] in "xX" else "x"
        view.replace(edit, sublime.Region(pos, pos + 1), new)


class MarkdownInlineAlignTableCommand(sublime_plugin.TextCommand):
    def is_enabled(self):
        return is_markdown(self.view)

    def run(self, edit, all=False, point=None, modified=False):
        view = self.view
        tables = find_blocks(view)[0]
        if point is not None:
            tables = [t for t in tables if t[0].begin() == point]
        elif modified:
            saved = _saved_tables.get(view.id(), set())
            tables = [t for t in tables if view.substr(t[0]) not in saved]
        elif not all:
            tables = [t for t in tables if intersects_selection(view, t[0])]
        # replace bottom-up so earlier regions stay valid
        max_chars = table_max_chars(view)
        for region, rows in sorted(tables, key=lambda t: -t[0].begin()):
            new = "\n".join(align_table(rows, max_chars))
            if new != view.substr(region):
                view.replace(edit, region, new)


class MarkdownInlineDebugCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        print("[MarkdownInline] syntax:", view.settings().get("syntax"))
        print("[MarkdownInline] markdown scope:", is_markdown(view))
        print("[MarkdownInline] enabled:", is_enabled(view))
        print("[MarkdownInline] color_scheme:", view.settings().get("color_scheme"))
        print("[MarkdownInline] background:", view.style().get("background"))
        sublime.status_message("Markdown Inline: debug info printed to the console")


class MarkdownInlineInsertImageCommand(sublime_plugin.TextCommand):
    def run(self, edit, link):
        for sel in reversed(self.view.sel()):
            self.view.replace(edit, sel, link)


class MarkdownInlinePasteImageCommand(sublime_plugin.TextCommand):
    def is_enabled(self):
        return is_markdown(self.view)

    def run(self, edit):
        view = self.view
        if not view.file_name():
            sublime.status_message("Markdown Inline: save the file before pasting an image")
            return
        sublime.get_clipboard_async(lambda text: self._from_text(view, text))

    def _from_text(self, view, text):
        found = clipboard_text_image(text)
        if found:
            self._save(view, found)
        else:
            sublime.set_timeout_async(lambda: self._from_raw(view))

    def _from_raw(self, view):
        found, error = clipboard_image_bytes()
        if not found:
            if error:
                sublime.status_message(
                    "Markdown Inline: {0} — install it to paste clipboard images".format(error))
            else:
                sublime.status_message("Markdown Inline: no image found on the clipboard")
            return
        sublime.set_timeout(lambda: self._save(view, found))

    def _save(self, view, found):
        data, ext = found
        base = os.path.dirname(view.file_name())
        rel_dir = settings().get("image_dir", "images")
        out_dir = rel_dir if os.path.isabs(rel_dir) else os.path.join(base, rel_dir)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            sublime.status_message("Markdown Inline: cannot create {}: {}".format(rel_dir, e))
            return

        prefix = settings().get("image_name_prefix", "pasted_")
        fmt = settings().get("image_name_format", "%Y%m%d_%H%M%S")
        stem = prefix + time.strftime(fmt)
        name, n = stem + ext, 1
        while os.path.exists(os.path.join(out_dir, name)):
            name = "{}-{}{}".format(stem, n, ext)
            n += 1
        try:
            with open(os.path.join(out_dir, name), "wb") as f:
                f.write(data)
        except OSError as e:
            sublime.status_message("Markdown Inline: cannot write image: {}".format(e))
            return

        link_dir = rel_dir.replace(os.sep, "/")
        if not link_dir.startswith(("./", "../", "/")):
            link_dir = "./" + link_dir
        link = "![{}]({}/{})".format(os.path.splitext(name)[0], link_dir, name)
        view.run_command("markdown_inline_insert_image", {"link": link})
        schedule(view, 0)
