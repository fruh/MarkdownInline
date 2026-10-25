"""Optional, removable module: draws the bullets and numbers of <list> / <olist> blocks.

The syntax file "Markdown Inline HTML.sublime-syntax" scopes the blocks; this file adds
the marker as a phantom at the start of each item line. Delete both files to remove the
feature (see README, "HTML-like tags").
"""
import re

import sublime
import sublime_plugin

SETTINGS_FILE = "MarkdownInline.sublime-settings"
SYNTAX_NAME = "Markdown Inline HTML.sublime-syntax"
KEY = "markdown_inline_html"
UNORDERED = "markup.list.html-unordered.markdown"
ORDERED = "markup.list.html-ordered.markdown"
TAG_ONLY_RE = re.compile(r"^\s*(</?(?:list|olist)>\s*)*$", re.I)
OLIST_OPEN_RE = re.compile(r"<olist>", re.I)
FENCE_RE = re.compile(r"^\s*(```|~~~)")
HIGHLIGHT_RE = re.compile(r"(<highlight>)(.*?)(</highlight>)", re.I | re.S)
HL_KEY = "markdown_inline_html_hl"
MARKER_SELECTOR = "meta.highlight-marker.html.markdown"

_phantom_sets = {}
_hl_folded = set()  # view ids whose <highlight> tags were folded
_tokens = {}


def active(view):
    syntax = view.settings().get("syntax") or ""
    return syntax.endswith(SYNTAX_NAME)


def marker_color(view):
    style = view.style_for_scope("markup.list.unnumbered.bullet.markdown")
    return style.get("foreground", "#f99157")


def item_markers(view):
    """Return [(point, text)] for every item line of every <list> / <olist> block."""
    lines = {}
    for selector, ordered in ((UNORDERED, False), (ORDERED, True)):
        for region in view.find_by_selector(selector):
            for line in view.lines(region):
                lines[line.begin()] = (line, ordered)

    markers = []
    number = 0
    for begin in sorted(lines):
        line, ordered = lines[begin]
        text = view.substr(line)
        if OLIST_OPEN_RE.search(text):
            number = 0
        if TAG_ONLY_RE.match(text):
            continue
        number += 1
        start = begin + len(text) - len(text.lstrip())
        markers.append((start, "{}.".format(number) if ordered else "•"))
    return markers


def fence_highlights(view):
    """Return (text regions, tag regions) of <highlight> inside fenced ``` blocks, which
    the syntax cannot scope because the language syntax owns their content. A highlight
    may span lines; an unclosed one is ignored."""
    texts, tags = [], []
    if view.find("<highlight>", 0, sublime.LITERAL | sublime.IGNORECASE) is None:
        return texts, tags
    start = None
    for line in view.lines(sublime.Region(0, view.size())):
        if not FENCE_RE.match(view.substr(line)):
            continue
        if start is None:
            start = line.end() + 1
            continue
        base = start
        text = view.substr(sublime.Region(start, line.begin()))
        start = None
        for m in HIGHLIGHT_RE.finditer(text):
            texts.append(sublime.Region(base + m.start(2), base + m.end(2)))
            tags.append(sublime.Region(base + m.start(1), base + m.end(1)))
            tags.append(sublime.Region(base + m.start(3), base + m.end(3)))
    return texts, tags


def clear_fence_highlights(view):
    view.erase_regions(HL_KEY)
    if view.id() in _hl_folded:
        _hl_folded.discard(view.id())
        view.unfold(highlight_marker_regions(view))


def highlight_marker_regions(view):
    return list(view.find_by_selector(MARKER_SELECTOR)) + fence_highlights(view)[1]


def render_highlights(view, fill, fold):
    """Fill <highlight> text in fenced blocks and fold the <highlight> tags (and the
    multi-line @@HL@@ markers of the raw blocks) unless the cursor is on their line."""
    texts, tags = fence_highlights(view) if (fill or fold) else ([], [])
    if fill:
        view.add_regions(HL_KEY, texts, "markup.highlight.yellow.fill.markdown", "",
                         sublime.DRAW_NO_OUTLINE)
    else:
        view.erase_regions(HL_KEY)
    if not fold:
        if view.id() in _hl_folded:
            _hl_folded.discard(view.id())
            view.unfold(highlight_marker_regions(view))
        return
    if not fill:
        view.unfold(tags)
        tags = []
    cursor_lines = [view.line(sel) for sel in view.sel()]
    for r in list(view.find_by_selector(MARKER_SELECTOR)) + tags:
        line = view.line(r)
        if any(line.intersects(c) or line.contains(c.begin()) for c in cursor_lines):
            view.unfold(r)
        else:
            view.fold(r)
    _hl_folded.add(view.id())


def render(view):
    if not view.is_valid():
        return
    ps = _phantom_sets.get(view.id())
    if ps is None:
        ps = _phantom_sets[view.id()] = sublime.PhantomSet(view, KEY)
    cfg = sublime.load_settings(SETTINGS_FILE)
    if not active(view) or not cfg.get("html_tags", True) \
            or view.rowcol(view.size())[0] + 1 > cfg.get("max_lines", 20000):
        ps.update([])
        clear_fence_highlights(view)
        return

    render_highlights(view, cfg.get("highlight_in_fences", True), cfg.get("fold_highlight_markers", True))
    color = marker_color(view)
    cursor_lines = {view.line(sel.begin()).begin() for sel in view.sel()}
    phantoms = []
    for point, text in item_markers(view):
        if view.line(point).begin() in cursor_lines:
            continue
        html = '<span style="color:{}">{}&nbsp;</span>'.format(color, text)
        phantoms.append(sublime.Phantom(
            sublime.Region(point), html, sublime.LAYOUT_INLINE))
    ps.update(phantoms)


def schedule(view):
    vid = view.id()
    token = _tokens[vid] = _tokens.get(vid, 0) + 1

    def run():
        if _tokens.get(vid) == token:
            render(view)

    delay = sublime.load_settings(SETTINGS_FILE).get("debounce_ms", 150)
    sublime.set_timeout_async(run, delay)


class MarkdownInlineHtmlListener(sublime_plugin.EventListener):
    def on_load_async(self, view):
        schedule(view)

    def on_activated_async(self, view):
        schedule(view)

    def on_modified_async(self, view):
        schedule(view)

    def on_selection_modified_async(self, view):
        schedule(view)

    def on_pre_close(self, view):
        _phantom_sets.pop(view.id(), None)
        _tokens.pop(view.id(), None)
        _hl_folded.discard(view.id())
