"""Сборка HTML полного комплекта документации AlMaBi (по образцу ОПиОП BI)."""
from __future__ import annotations

from pathlib import Path

import markdown

DOC_DIR = Path(__file__).resolve().parent
OUT_HTML = DOC_DIR / "Документация_AlMaBi_полный_комплект.html"

FILES = [
    "00_Оглавление.md",
    "01_Описание_проекта.md",
    "02_Архитектура_приложения.md",
    "03_Архитектура_хранилища.md",
    "04_API_и_маршруты.md",
    "05_Модель_данных_Excel.md",
    "06_Развертывание_и_эксплуатация.md",
    "07_Документация_для_проверки_ИБ.md",
    "08_Чек_лист_проверки_ИБ.md",
]

CSS = """
:root {
  --bg: #f6f8fb;
  --card: #ffffff;
  --text: #1a2332;
  --muted: #5b6b7c;
  --accent: #0b4f6c;
  --border: #d8e0ea;
  --code-bg: #0f172a;
  --code-fg: #e2e8f0;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
  color: var(--text);
  background: linear-gradient(180deg, #e8f1f6 0%, var(--bg) 240px);
  line-height: 1.55;
}
.wrap { max-width: 980px; margin: 0 auto; padding: 32px 20px 80px; }
header.hero {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 28px 32px;
  margin-bottom: 28px;
  box-shadow: 0 8px 24px rgba(26, 35, 50, 0.06);
}
header.hero h1 { margin: 0 0 8px; font-size: 1.85rem; color: var(--accent); }
header.hero p { margin: 4px 0; color: var(--muted); }
nav.toc {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 28px;
}
nav.toc h2 { margin: 0 0 10px; font-size: 1.05rem; }
nav.toc ol { margin: 0; padding-left: 1.3rem; }
nav.toc a { color: var(--accent); text-decoration: none; }
nav.toc a:hover { text-decoration: underline; }
section.doc {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 24px 28px 32px;
  margin-bottom: 22px;
  box-shadow: 0 4px 14px rgba(26, 35, 50, 0.04);
}
section.doc h1 { font-size: 1.55rem; border-bottom: 2px solid var(--accent); padding-bottom: 8px; }
section.doc h2 { font-size: 1.25rem; margin-top: 1.6em; color: #123; }
section.doc h3 { font-size: 1.08rem; margin-top: 1.3em; }
table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0 18px;
  font-size: 0.95rem;
}
th, td {
  border: 1px solid var(--border);
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
}
th { background: #e8f2f7; }
tr:nth-child(even) td { background: #fafcfe; }
code {
  font-family: Consolas, "Courier New", monospace;
  background: #eef2f7;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.9em;
}
pre {
  background: var(--code-bg);
  color: var(--code-fg);
  padding: 14px 16px;
  border-radius: 10px;
  overflow-x: auto;
  font-size: 0.88rem;
}
pre code { background: transparent; color: inherit; padding: 0; }
blockquote {
  margin: 12px 0;
  padding: 10px 14px;
  border-left: 4px solid var(--accent);
  background: #f0f6fa;
  color: var(--muted);
}
hr { border: none; border-top: 1px solid var(--border); margin: 24px 0; }
footer.note {
  color: var(--muted);
  font-size: 0.9rem;
  text-align: center;
  margin-top: 12px;
}
"""


def md_to_html(text: str) -> str:
    return markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists"],
    )


def section_id(filename: str) -> str:
    return Path(filename).stem


def main() -> None:
    toc_items: list[str] = []
    sections: list[str] = []

    for name in FILES:
        path = DOC_DIR / name
        raw = path.read_text(encoding="utf-8")
        title = raw.splitlines()[0].lstrip("# ").strip() if raw else name
        sid = section_id(name)
        toc_items.append(f'<li><a href="#{sid}">{title}</a></li>')
        body = md_to_html(raw)
        sections.append(f'<section class="doc" id="{sid}">\n{body}\n</section>')

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Документация Al Ma BI — полный комплект</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <h1>Документация Al Ma BI</h1>
    </header>
    <nav class="toc">
      <h2>Содержание</h2>
      <ol>
        {chr(10).join(toc_items)}
      </ol>
    </nav>
    {chr(10).join(sections)}
  </div>
</body>
</html>
"""
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT_HTML} ({OUT_HTML.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
