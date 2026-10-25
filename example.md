# MarkdownInline

Inline Markdown preview for Sublime Text: you keep editing the raw text while the result shows in place.

## Heading 2

Orange, with the same thin rule below.

### Heading 3

Purple, a good level for sub-sections.

#### Heading 4

Blue, for smaller topics inside a sub-section.

##### Heading 5

Green, used for the two smallest levels.

## Task lists

Task list items show as larger checkboxes that you can click to toggle. A checked box gets a mark inside it.

- [x] Install the plugin
- [ ] Click a checkbox to toggle it

## Tables

Tables are aligned into neat columns when you leave one you edited, or when you save. Alignment markers like `:--` and `--:` are kept.

| Feature              |      Setting       | Default |
| :------------------- | :----------------: | ------: |
| Clickable task lists |   checkbox_scale   |     1.6 |
| Heading underline    | underline_headings |    true |

Long cells wrap into aligned columns; the `↳` marks a continuation line.

| Setting               | What it does                                                                      |
| --------------------- | --------------------------------------------------------------------------------- |
| align_tables_on_leave | Aligns a table when the cursor leaves it, but only if you edited it. Reading a    |
| ↳                     | file never rewrites a table, and long cells are wrapped so the row fits the       |
| ↳                     | window.                                                                           |
| align_tables_on_save  | Aligns only the tab les you changed since the file was loaded or last saved.      |

## Tags

Status tags are colored and underlined, which is handy for tracking findings: #todo, #done, #vulnerable, #reported and #falsepositive.

## Text formatting

Markers such as **bold**, *italic*, ~~strikethrough~~ and `inline code` are dimmed instead of hidden, so the text stays easy to read and edit. Links look like [this one](https://github.com/fruh/MarkdownInline) and fold their URL away until you edit the line.

> Blockquotes are set apart in a muted italic color, and their marker is tinted.

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



## HTML-like tags

Use <code>code</code> and <bold>bold</bold> inline, or whole blocks:

<list>
First bullet
Second bullet with <bold>bold</bold>
</list>

<olist>
First step
Second step
</olist>

<codeblock>
print("same look as a fenced block")
</codeblock>

<request>
GET /login HTTP/1.1
Host: example.com
</request>

<response>
HTTP/1.1 200 OK
Set-Cookie: <highlight>session=abc123</highlight>
</response>
