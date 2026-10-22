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

_phantom_sets = {}
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
        return

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
