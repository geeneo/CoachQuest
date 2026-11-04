"""The small Markdown subset of News & guides posts, for emails: HTML with inline styles (mail apps
ignore style sheets) and a clean plain-text version.

Handles headings (#, ##, ###), paragraphs, "- " / "* " / "1. " lists with indented continuation lines,
**bold**, *italic*, `code`, [links](https://...) and bare https:// links. Everything else is text,
HTML-escaped.
"""

import html
import re

TEXT = "color:#1f2937;font-size:15px;line-height:1.55"
BLOCK = re.compile(r"^(#{1,3})\s+(.*)$|^\s*([-*]|\d+\.)\s+(.*)$")


def _blocks(md: str, breaks: bool = False) -> list[tuple[str, object]]:
    """[(kind, content)]: ("h1".."h3", text), ("ul"/"ol", [items]), ("p", text)."""
    out: list[tuple[str, object]] = []
    para: list[str] = []

    def flush():
        if para:
            out.append(("p", ("\n" if breaks else " ").join(para)))
            para.clear()

    for raw in md.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        m = BLOCK.match(line)
        if not line.strip():
            flush()
            continue
        if m and m.group(1):
            flush()
            out.append((f"h{len(m.group(1))}", m.group(2).strip()))
        elif m and m.group(3):
            flush()
            kind = "ol" if m.group(3)[0].isdigit() else "ul"
            if out and out[-1][0] == kind and not para:
                out[-1][1].append(m.group(4).strip())
            else:
                out.append((kind, [m.group(4).strip()]))
        elif raw[:1] == " " and out and out[-1][0] in ("ul", "ol") and not para:
            out[-1][1][-1] += " " + line.strip()  # a list item's next line
        else:
            para.append(line.strip())
    flush()
    return out


def _inline_html(t: str) -> str:
    links: list[str] = []

    def keep(m):
        links.append(
            f'<a href="{html.escape(m.group(2), quote=True)}" style="color:#0b6fbf">{html.escape(m.group(1))}</a>'
        )
        return f"\x00{len(links) - 1}\x00"

    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", keep, t)
    t = html.escape(t, quote=False)
    t = re.sub(r"(?<![\"=])(https?://[^\s<]+[^\s<.,;:)])", r'<a href="\1" style="color:#0b6fbf">\1</a>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", t)
    t = re.sub(r"`([^`]+)`", r'<code style="background:#eef2f7;padding:0 3px;border-radius:3px">\1</code>', t)
    return re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], t)


def _inline_text(t: str) -> str:
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1 (\2)", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"\1", t)
    return t.replace("`", "")


def to_html(md: str, breaks: bool = False) -> str:
    """`breaks`: keep the text's line breaks inside a paragraph (emails written line by line); posts
    are hard-wrapped, so their lines are joined."""
    parts = []
    sizes = {"h1": 22, "h2": 18, "h3": 16}
    for kind, content in _blocks(md, breaks):
        if kind in sizes:
            parts.append(
                f'<h{kind[1]} style="color:#032440;font-size:{sizes[kind]}px;margin:24px 0 8px">'
                f"{_inline_html(content)}</h{kind[1]}>"
            )
        elif kind in ("ul", "ol"):
            items = "".join(f'<li style="margin:0 0 6px">{_inline_html(i)}</li>' for i in content)
            parts.append(f'<{kind} style="{TEXT};margin:0 0 14px;padding-left:22px">{items}</{kind}>')
        else:
            body = "<br>".join(_inline_html(line) for line in content.split("\n"))
            parts.append(f'<p style="{TEXT};margin:0 0 14px">{body}</p>')
    return "\n".join(parts)


def to_text(md: str) -> str:
    lines = []
    for kind, content in _blocks(md):
        if kind.startswith("h"):
            title = _inline_text(content)
            lines += ["", title.upper() if kind in ("h1", "h2") else title, ""]
        elif kind in ("ul", "ol"):
            for n, i in enumerate(content, 1):
                lines.append(f"{n}. {_inline_text(i)}" if kind == "ol" else f"• {_inline_text(i)}")
            lines.append("")
        else:
            lines += [_inline_text(content), ""]
    return "\n".join(lines).strip() + "\n"


def plain(text: str) -> str:
    """An email's own text without the Markdown markers, line by line (its layout stays)."""
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        line = m.group(2) if m else line
        line = re.sub(r"^(\s*)[-*]\s+", r"\1• ", line)
        out.append(_inline_text(line))
    return "\n".join(out)


def page(title: str, body_html: str, button: tuple[str, str] | None = None, footer_html: str = "") -> str:
    """A whole email: a header band, the body, an optional button and a small footer."""
    btn = (
        f'<p style="margin:24px 0"><a href="{html.escape(button[1], quote=True)}" '
        'style="background:#0b6fbf;color:#ffffff;text-decoration:none;padding:11px 20px;border-radius:6px;'
        f'font-weight:600;display:inline-block">{html.escape(button[0])}</a></p>'
        if button
        else ""
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title></head>
<body style="margin:0;padding:0;background:#f2f5f9">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f2f5f9">
<tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
 style="max-width:600px;background:#ffffff;border-radius:10px;overflow:hidden;
 font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">
<tr><td style="background:#032440;padding:18px 28px;color:#ffffff;font-size:20px;font-weight:700;letter-spacing:.5px">
COACH<span style="color:#f28c28">QUEST</span></td></tr>
<tr><td style="padding:26px 28px 8px">
<h1 style="color:#032440;font-size:22px;margin:0 0 16px">{html.escape(title)}</h1>
{body_html}
{btn}
</td></tr>
<tr><td style="padding:16px 28px 24px;border-top:1px solid #e5e9f0;color:#6b7280;font-size:12px;line-height:1.5">
{footer_html}</td></tr>
</table></td></tr></table></body></html>"""
