#!/usr/bin/env python3
"""Convert the LaTeX lecture notes in src/ into the static site in docs/.

Usage:  python3 build.py

Math is left as LaTeX and rendered in the browser by MathJax, so anything
MathJax understands works inside $...$, \\[...\\], align*, etc. Macros from
src/preamble.tex are passed to MathJax.

Text-mode LaTeX is converted by this script. It supports the subset used in
the notes: \\chapter, \\section, \\subsection, \\paragraph, theorem-like
environments, proof, enumerate/itemize, figure (+ \\caption), \\emph,
\\textbf, \\textit, quotes and dashes. Anything else is reported as a
warning so it can be added.

TikZ cannot run in the browser. Inside a figure environment, add a comment
    %html-figure: name.svg
pointing at a file in src/figures/; the HTML uses that SVG and LaTeX
ignores the comment.
"""

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
OUT = ROOT / "docs"
SITE_TITLE = "Stochastic Calculus Notes"
SITE_SUBTITLE = "ACTSC 969, University of Waterloo"

# Chapters, in order. Add later chapters here as their .tex files arrive.
CHAPTERS = [
    ("martingales", "01-martingales.tex"),
]

THEOREM_ENVS = {
    "definition": "Definition",
    "theorem": "Theorem",
    "proposition": "Proposition",
    "lemma": "Lemma",
    "corollary": "Corollary",
    "example": "Example",
    "remark": "Remark",
    "exercise": "Exercise",
}
MATH_ENVS = {"align", "align*", "equation", "equation*", "gather", "gather*",
             "multline", "multline*", "eqnarray", "eqnarray*"}
IGNORED_COMMANDS = {"medskip", "smallskip", "bigskip", "noindent", "centering",
                    "par", "newpage", "clearpage", "maketitle", "indent"}

warnings = []


def warn(msg):
    warnings.append(msg)


# ---------------------------------------------------------------- utilities

def read_group(s, i, open_ch="{", close_ch="}"):
    """s[i] must be open_ch. Return (content, index after the closing char)."""
    assert s[i] == open_ch, (s[i:i + 30], open_ch)
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    raise ValueError("Unbalanced group starting at: " + s[i:i + 60])


def skip_ws(s, i):
    while i < len(s) and s[i] in " \t\n":
        i += 1
    return i


def read_optional(s, i):
    """If s[i:] (after spaces on the same line) starts with [...], return it."""
    j = i
    while j < len(s) and s[j] in " \t":
        j += 1
    if j < len(s) and s[j] == "[":
        content, end = read_group(s, j, "[", "]")
        return content, end
    return None, i


def find_env_end(s, name, start):
    """Index of the matching \\end{name} for an env whose body starts at start."""
    begin_tok = "\\begin{%s}" % name
    end_tok = "\\end{%s}" % name
    depth = 1
    i = start
    while True:
        nb = s.find(begin_tok, i)
        ne = s.find(end_tok, i)
        if ne == -1:
            raise ValueError("Missing %s" % end_tok)
        if nb != -1 and nb < ne:
            depth += 1
            i = nb + len(begin_tok)
        else:
            depth -= 1
            if depth == 0:
                return ne, ne + len(end_tok)
            i = ne + len(end_tok)


def slugify(text):
    text = re.sub(r"\x00M\d+\x00", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "section"


# ------------------------------------------------------------ preprocessing

def strip_comments(s):
    s = re.sub(r"^[ \t]*%html-figure:\s*(\S+)[ \t]*$",
               lambda m: "\\htmlfigure{%s}" % m.group(1), s, flags=re.M)
    # Drop % comments (not \%), keeping the newline.
    return re.sub(r"(?<!\\)%.*", "", s)


class MathStore:
    """Replace math with placeholders so text conversion cannot touch it."""

    def __init__(self):
        self.items = []

    def add(self, tex):
        self.items.append(tex)
        return "\x00M%d\x00" % (len(self.items) - 1)

    def extract(self, s):
        out = []
        i = 0
        while i < len(s):
            if s.startswith("\\[", i):
                j = s.find("\\]", i + 2)
                out.append(self.add(s[i:j + 2]))
                i = j + 2
            elif s.startswith("\\(", i):
                j = s.find("\\)", i + 2)
                out.append(self.add(s[i:j + 2]))
                i = j + 2
            elif s.startswith("$$", i):
                j = s.find("$$", i + 2)
                out.append(self.add("\\[" + s[i + 2:j] + "\\]"))
                i = j + 2
            elif s[i] == "$":
                j = i + 1
                while s[j] != "$" or s[j - 1] == "\\":
                    j += 1
                out.append(self.add(s[i:j + 1]))
                i = j + 1
            elif s.startswith("\\begin{", i):
                name = s[i + 7:s.find("}", i)]
                if name in MATH_ENVS:
                    _, end = find_env_end(s, name, i + 8 + len(name))
                    out.append(self.add(s[i:end]))
                    i = end
                else:
                    out.append(s[i])
                    i += 1
            elif s[i] == "\\" and i + 1 < len(s):
                out.append(s[i:i + 2])  # keep escaped chars like \$ together
                i += 2
            else:
                out.append(s[i])
                i += 1
        return "".join(out)

    def restore(self, s):
        return re.sub(r"\x00M(\d+)\x00",
                      lambda m: html.escape(self.items[int(m.group(1))], quote=False), s)


# ---------------------------------------------------------- inline (text)

def convert_inline(s):
    """Convert text-mode LaTeX inside a paragraph to HTML."""
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            m = re.match(r"\\([a-zA-Z]+)\*?", s[i:])
            if not m:
                nxt = s[i + 1] if i + 1 < len(s) else ""
                if nxt == "\\":
                    out.append("<br>")
                elif nxt in "%&$#_{} ":
                    out.append(html.escape(nxt) if nxt != " " else " ")
                elif nxt == ",":
                    out.append("&thinsp;")
                else:
                    warn("Unknown control symbol \\" + nxt)
                i += 2
                continue
            name = m.group(1)
            j = i + len(m.group(0))
            if name in ("emph", "textit"):
                content, j = read_group(s, skip_ws(s, j))
                out.append("<em>%s</em>" % convert_inline(content))
            elif name == "textbf":
                content, j = read_group(s, skip_ws(s, j))
                out.append("<strong>%s</strong>" % convert_inline(content))
            elif name == "texttt":
                content, j = read_group(s, skip_ws(s, j))
                out.append("<code>%s</code>" % convert_inline(content))
            elif name in ("label", "index"):
                _, j = read_group(s, skip_ws(s, j))
            elif name in IGNORED_COMMANDS:
                pass
            elif name == "ldots" or name == "dots":
                out.append("&hellip;")
            elif name == "LaTeX":
                out.append("LaTeX")
            else:
                warn("Unknown text command \\%s" % name)
                out.append(html.escape(m.group(0)))
            i = j
            continue
        if s.startswith("``", i):
            out.append("&ldquo;"); i += 2; continue
        if s.startswith("''", i):
            out.append("&rdquo;"); i += 2; continue
        if s.startswith("---", i):
            out.append("&mdash;"); i += 3; continue
        if s.startswith("--", i):
            out.append("&ndash;"); i += 2; continue
        if c == "~":
            out.append("&nbsp;"); i += 1; continue
        if c in "{}":
            i += 1; continue
        out.append(html.escape(c, quote=False))
        i += 1
    return "".join(out)


# ------------------------------------------------------------ block level

class Renderer:
    def __init__(self, chapter_num):
        self.chapter_num = chapter_num
        self.counter = 0
        self.figure_counter = 0
        self.toc = []  # (level, id, html title)
        self.used_ids = set()
        self.chapter_title = None

    def unique_id(self, base):
        cand = base
        n = 2
        while cand in self.used_ids:
            cand = "%s-%d" % (base, n)
            n += 1
        self.used_ids.add(cand)
        return cand

    def render_paragraphs(self, text):
        html_parts = []
        for para in re.split(r"\n[ \t]*\n", text):
            if not para.strip():
                continue
            html_parts.append(self.render_paragraph(para.strip()))
        return "\n".join(html_parts)

    def render_paragraph(self, para):
        m = re.match(r"\\paragraph\*?\s*\{", para)
        if m:
            title, end = read_group(para, m.end() - 1)
            rest = para[end:].strip()
            title_html = convert_inline(title)
            if not rest:
                return '<h4 class="paragraph-head">%s</h4>' % title_html
            return '<p><strong class="run-in">%s</strong> %s</p>' % (
                title_html, convert_inline(rest))
        return "<p>%s</p>" % convert_inline(para)

    def render(self, s):
        """Render a block of LaTeX (no math, already placeholdered)."""
        out = []
        pattern = re.compile(
            r"\\(chapter|section|subsection|subsubsection)(\*?)\s*\{"
            r"|\\begin\{([a-zA-Z*]+)\}"
            r"|\\paragraph\*?\s*\{")
        i = 0
        buf_start = 0
        while True:
            m = pattern.search(s, i)
            if not m:
                break
            if m.group(0).startswith("\\paragraph"):
                # Paragraph headings start a new paragraph but stay inline.
                out.append(self.render_paragraphs(s[buf_start:m.start()]))
                buf_start = m.start()
                i = m.end()
                # Ensure it begins its own paragraph
                continue
            out.append(self.render_paragraphs(s[buf_start:m.start()]))
            if m.group(1):
                level = m.group(1)
                title, end = read_group(s, m.end() - 1)
                out.append(self.heading(level, title))
                i = buf_start = end
            else:
                env = m.group(3)
                body_start = m.end()
                body_end, after = find_env_end(s, env, body_start)
                out.append(self.environment(env, s[body_start:body_end]))
                i = buf_start = after
        out.append(self.render_paragraphs(s[buf_start:]))
        return "\n".join(p for p in out if p)

    def heading(self, level, title):
        title_html = convert_inline(title)
        if level == "chapter":
            self.chapter_title = title_html
            return ""
        tag = {"section": "h2", "subsection": "h3", "subsubsection": "h4"}[level]
        hid = self.unique_id(slugify(title))
        if level in ("section", "subsection"):
            self.toc.append((level, hid, title_html))
        return '<%s id="%s"><a class="anchor" href="#%s">%s</a></%s>' % (
            tag, hid, hid, title_html, tag)

    def environment(self, env, body):
        if env in THEOREM_ENVS:
            return self.theorem(env, body)
        if env == "proof":
            title, start = read_optional(body, 0)
            label = convert_inline(title) if title else "Proof"
            inner = self.render(body[start:])
            return ('<div class="proof"><span class="proof-label">%s.</span>\n%s\n'
                    '<span class="qed" aria-label="end of proof">&#8718;</span></div>'
                    % (label, inner))
        if env in ("enumerate", "itemize"):
            return self.list_env(env, body)
        if env in ("figure", "figure*"):
            return self.figure(body)
        if env in ("center",):
            return '<div class="center">%s</div>' % self.render(body)
        if env == "tikzpicture":
            warn("tikzpicture outside a figure is not rendered")
            return ""
        warn("Unknown environment %s (rendered as plain text)" % env)
        return self.render(body)

    def theorem(self, env, body):
        title, start = read_optional(body, 0)
        self.counter += 1
        number = "%d.%d" % (self.chapter_num, self.counter)
        tid = self.unique_id("%s-%s" % (env, number.replace(".", "-")))
        head = '<a class="thm-name" href="#%s">%s %s</a>' % (
            tid, THEOREM_ENVS[env], number)
        if title:
            head += ' <span class="thm-title">(%s)</span>' % convert_inline(title)
        inner = self.render(body[start:])
        return ('<div class="thm thm-%s" id="%s">\n<div class="thm-head">%s.</div>\n%s\n</div>'
                % (env, tid, head, inner))

    def list_env(self, env, body):
        items = []
        i = 0
        depth = 0
        positions = []
        # Find top-level \item positions (skip those inside nested lists).
        for m in re.finditer(r"\\begin\{(enumerate|itemize)\}|\\end\{(enumerate|itemize)\}|\\item\b", body):
            tok = m.group(0)
            if tok.startswith("\\begin"):
                depth += 1
            elif tok.startswith("\\end"):
                depth -= 1
            elif depth == 0:
                positions.append(m.start())
        positions.append(len(body))
        for a, b in zip(positions, positions[1:]):
            chunk = body[a + len("\\item"):b]
            label, start = read_optional(chunk, 0)
            items.append((label, chunk[start:]))
        has_labels = any(lbl is not None for lbl, _ in items)
        tag = "ol" if env == "enumerate" else "ul"
        cls = ' class="labeled"' if has_labels else ""
        lis = []
        for label, content in items:
            inner = self.render(content.strip())
            # Unwrap a single paragraph so list items stay compact.
            if inner.count("<p>") == 1 and inner.startswith("<p>") and inner.endswith("</p>"):
                inner = inner[3:-4]
            if label is not None:
                lis.append('<li><span class="item-label">%s</span><div>%s</div></li>'
                           % (convert_inline(label), inner))
            else:
                lis.append("<li>%s</li>" % inner)
        return "<%s%s>\n%s\n</%s>" % (tag, cls, "\n".join(lis), tag)

    def figure(self, body):
        _, start = read_optional(body, 0)
        body = body[start:]
        self.figure_counter += 1
        svg_html = ""
        m = re.search(r"\\htmlfigure\{([^}]+)\}", body)
        if m:
            path = SRC / "figures" / m.group(1)
            if path.exists():
                svg_html = path.read_text()
            else:
                warn("Missing figure file %s" % path)
        elif "tikzpicture" in body:
            warn("Figure %d has TikZ but no %%html-figure comment" % self.figure_counter)
        caption = ""
        cm = re.search(r"\\caption\s*\{", body)
        if cm:
            cap, _ = read_group(body, cm.end() - 1)
            caption = "<figcaption><strong>Figure %d.%d.</strong> %s</figcaption>" % (
                self.chapter_num, self.figure_counter, convert_inline(cap))
        return '<figure>\n%s\n%s\n</figure>' % (svg_html, caption)


# ---------------------------------------------------------------- MathJax

def mathjax_macros():
    text = strip_comments((SRC / "preamble.tex").read_text())
    macros = {}
    for m in re.finditer(r"\\(?:re)?newcommand\*?\s*\{?\\([a-zA-Z]+)\}?\s*(?:\[(\d)\])?\s*\{", text):
        body, _ = read_group(text, m.end() - 1)
        macros[m.group(1)] = [body, int(m.group(2))] if m.group(2) else body
    for m in re.finditer(r"\\DeclareMathOperator(\*?)\s*\{\\([a-zA-Z]+)\}\s*\{([^}]*)\}", text):
        op = "\\operatorname%s{%s}" % (m.group(1), m.group(3))
        macros[m.group(2)] = op
    return macros


def js_string(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def mathjax_config():
    items = []
    for name, val in mathjax_macros().items():
        if isinstance(val, list):
            items.append("      %s: [%s, %d]" % (name, js_string(val[0]), val[1]))
        else:
            items.append("      %s: %s" % (name, js_string(val)))
    return """<script>
  window.MathJax = {
    tex: {
      inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
      displayMath: [['\\\\[', '\\\\]']],
      processEnvironments: true,
      macros: {
%s
      }
    },
    chtml: { displayAlign: 'center' },
    options: { skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'svg'] }
  };
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>""" % ",\n".join(items)


# ---------------------------------------------------------------- pages

# Computer Modern prose, to match the MathJax equations.
#
# We declare the @font-face rules ourselves, under our own family name
# "CMProse", so the CSS can never disagree with the font's registered name.
# Each face lists several sources; the browser tries them in order and uses the
# first that downloads:
#   1. Computer Modern Unicode (cmunrm/ti/bx/bi) from the vsalvino repo on jsDelivr
#   2. MathJax's own Computer Modern files from jsDelivr (the same files that draw
#      the equations, so they are known to be reachable from the reader's browser)
# If everything fails the page falls back to Georgia.
#
# #font-probe reports what really happened: the load status of each CMProse face
# and which font files were requested. (document.fonts.check() is NOT used: it
# returns true for unknown family names, which made the earlier probe misleading.)
_VS = "https://cdn.jsdelivr.net/gh/vsalvino/computer-modern@main/fonts/Serif"
_MJ = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/output/chtml/fonts/woff-v2"
FONT_LINK = """<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<style>
  @font-face { font-family: "CMProse"; font-style: normal; font-weight: 400; font-display: swap;
    src: url("%(vs)s/cmunrm.woff2") format("woff2"),
         url("%(mj)s/MathJax_Main-Regular.woff") format("woff"); }
  @font-face { font-family: "CMProse"; font-style: italic; font-weight: 400; font-display: swap;
    src: url("%(vs)s/cmunti.woff2") format("woff2"),
         url("%(mj)s/MathJax_Main-Italic.woff") format("woff"); }
  @font-face { font-family: "CMProse"; font-style: normal; font-weight: 700; font-display: swap;
    src: url("%(vs)s/cmunbx.woff2") format("woff2"),
         url("%(mj)s/MathJax_Main-Bold.woff") format("woff"); }
  @font-face { font-family: "CMProse"; font-style: italic; font-weight: 700; font-display: swap;
    src: url("%(vs)s/cmunbi.woff2") format("woff2"),
         url("%(mj)s/MathJax_Main-BoldItalic.woff") format("woff"); }
</style>
<script>
  document.addEventListener("DOMContentLoaded", function () {
    var el = document.getElementById("font-probe");
    if (!el || !document.fonts) return;
    function report() {
      // Real status of each @font-face we declared.
      var faces = [];
      document.fonts.forEach(function (f) {
        if (f.family.replace(/"/g, "") === "CMProse") faces.push(f.style + "/" + f.weight + ":" + f.status);
      });
      // Which font files were actually requested, with HTTP status when exposed.
      var files = performance.getEntriesByType("resource")
        .filter(function (r) { return /\.(woff2?|ttf|otf)(\?|$)/.test(r.name); })
        .map(function (r) {
          var n = r.name.split("/").pop();
          var host = /vsalvino/.test(r.name) ? "CM" : (/MathJax_/.test(r.name) ? "MJ" : "?");
          return host + ":" + n + (r.responseStatus ? " " + r.responseStatus : "");
        });
      var ok = faces.some(function (x) { return /:loaded$/.test(x); });
      el.textContent = (ok ? "CMProse OK" : "CMProse NOT loaded") + " | " + faces.join(", ")
                       + " | files: " + (files.join("; ") || "none");
      el.className = ok ? "ok" : "bad";
    }
    // Force the browser to fetch the regular face now, then report.
    var p = document.fonts.load('16px "CMProse"');
    Promise.resolve(p).then(report, report);
    setTimeout(report, 4000);
  });
</script>"""  % {"vs": _VS, "mj": _MJ}


def page(title, body, nav_html="", css_version=""):
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title>
%s
<link rel="stylesheet" href="style.css%s">
%s
</head>
<body>
<header class="site-header">
  <a class="site-title" href="index.html">%s</a>
  <span class="site-subtitle">%s</span>
</header>
%s
<main>
%s
</main>
</body>
</html>
""" % (title, FONT_LINK, css_version, mathjax_config(), SITE_TITLE, SITE_SUBTITLE,
       nav_html, body)


def toc_html(toc, chapters_info, current_slug):
    """Horizontal top bar: current chapter's lecture (section) links only."""
    current = next((c for c in chapters_info if c["slug"] == current_slug), None)
    section_links = [
        '<a href="#%s">%s</a>' % (hid, title)
        for level, hid, title in toc if level == "section"
    ]
    if not section_links:
        return ""
    label = current["title"] if current else "Contents"
    return ('<nav class="toc" aria-label="On this page">\n'
            '<span class="toc-title">%s</span>\n'
            '<div class="toc-links">%s</div>\n'
            '<span id="font-probe">checking font\u2026</span>\n'
            '</nav>') % (label, "\n".join(section_links))


def build():
    OUT.mkdir(exist_ok=True)
    css_text = (ROOT / "assets" / "style.css").read_text()
    import hashlib
    css_version = "?v=" + hashlib.sha1(css_text.encode()).hexdigest()[:8]
    rendered = []
    for num, (slug, filename) in enumerate(CHAPTERS, start=1):
        tex = (SRC / filename).read_text()
        math = MathStore()
        s = math.extract(strip_comments(tex))
        r = Renderer(num)
        body = r.render(s)
        title = r.chapter_title or slug.replace("-", " ").title()
        rendered.append({"slug": slug, "num": num, "title": "%d. %s" % (num, title),
                         "plain_title": title, "body": body, "math": math, "toc": r.toc})

    for i, info in enumerate(rendered):
        prev_link = next_link = ""
        if i > 0:
            p = rendered[i - 1]
            prev_link = '<a href="%s.html">&larr; %s</a>' % (p["slug"], p["title"])
        if i + 1 < len(rendered):
            n = rendered[i + 1]
            next_link = '<a href="%s.html">%s &rarr;</a>' % (n["slug"], n["title"])
        pager = '<nav class="pager"><span>%s</span><span>%s</span></nav>' % (prev_link, next_link)
        body = ('<h1>Chapter %d<br><span class="chapter-name">%s</span></h1>\n%s\n%s'
                % (info["num"], info["plain_title"], info["body"], pager))
        body = info["math"].restore(body)
        nav = info["math"].restore(toc_html(info["toc"], rendered, info["slug"]))
        html_text = page("%s | %s" % (info["plain_title"], SITE_TITLE), body, nav, css_version)
        (OUT / ("%s.html" % info["slug"])).write_text(html_text)

    # Index page
    items = []
    for info in rendered:
        lectures = [t for lvl, hid, t in info["toc"] if lvl == "section"]
        lec_links = ", ".join(
            '<a href="%s.html#%s">%s</a>' % (info["slug"], hid, t)
            for lvl, hid, t in info["toc"] if lvl == "section")
        items.append('<li><a class="chapter-link" href="%s.html">%s</a>'
                     '<div class="lectures">%s</div></li>'
                     % (info["slug"], info["title"], lec_links if lectures else ""))
    index_body = ("<h1>%s</h1>\n<p>Notes from %s.</p>\n<ol class=\"chapter-list\">\n%s\n</ol>"
                  % (SITE_TITLE, SITE_SUBTITLE, "\n".join(items)))
    index_body = rendered[0]["math"].restore(index_body) if rendered else index_body
    (OUT / "index.html").write_text(page(SITE_TITLE, index_body, "", css_version))

    (OUT / "style.css").write_text(css_text)
    (OUT / ".nojekyll").write_text("")

    for w in sorted(set(warnings)):
        print("warning:", w, file=sys.stderr)
    print("Built %d chapter(s) into %s" % (len(rendered), OUT))


if __name__ == "__main__":
    build()
