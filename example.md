# MarkdownInline

Inline Markdown preview for Sublime Text: you keep editing the raw text while the result shows in place.

## Headings

Each of the six levels has its own color, and all of them are underlined. The `#` markers share the color of the heading text.

# Heading 1

Yellow. H1 and H2 also get a thin rule under the line.

## Heading 2

Orange, with the same thin rule below.

### Heading 3

Purple, a good level for sub-sections.

#### Heading 4

Blue, for smaller topics inside a sub-section.

##### Heading 5

Green, used for the two smallest levels.

###### Heading 6

Also green, so deep nesting still stands out from the body text.

## Task lists

Task list items show as larger checkboxes that you can click to toggle. A checked box gets a mark inside it.

- [x] Install the plugin
- [x] Open a Markdown file
- [ ] Click a checkbox to toggle it
- [ ] Keep writing, the preview stays out of the way

## Tables

Tables are aligned into neat columns when you leave one you edited, or when you save. Alignment markers like `:--` and `--:` are kept.

| Feature              |        Setting        | Default |
| :------------------- | :-------------------: | ------: |
| Clickable task lists |     checkbox_scale    |     1.6 |
| Heading underline    |   underline_headings  |    true |
| Align on leave       | align_tables_on_leave |    true |
| Align on save        |  align_tables_on_save |    true |

Long cells wrap into aligned columns; the `↳` marks a continuation line.

| Setting               | What it does                               |
| --------------------- | ------------------------------------------ |
| align_tables_on_leave | Aligns a table when the cursor leaves it,  |
| ↳                     | but only if you edited it. Reading a file  |
| ↳                     | never rewrites a table, and long cells are |
| ↳                     | wrapped so the row fits the window.        |
| align_tables_on_save  | Aligns only the tables you changed since   |
| ↳                     | the file was loaded or last saved.         |

## Text formatting

Markers such as **bold**, *italic*, ~~strikethrough~~ and `inline code` are dimmed instead of hidden, so the text stays easy to read and edit. Links look like [this one](https://github.com/fruh/MarkdownInline).

> Blockquotes are set apart in a muted italic color,
> and their marker is tinted.

- Bullet lists
  - with nested items
- and numbered lists:
  1. first step
  2. second step

## Code

Fenced code blocks keep their syntax colors, and a `#` line inside one is never treated as a heading.

```python
# a comment in a code block is not treated as a heading
def hello(name):
    return "Hello, " + name
```
