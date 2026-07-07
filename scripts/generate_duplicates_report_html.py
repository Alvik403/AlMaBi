"""HTML-отчёт: одинаковые факты, попавшие в BI, и пересечения между статьями."""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "logs" / "almabi_test" / "audit-latest.json"
DEFAULT_OUTPUT = Path.home() / "Downloads" / "almabi_duplicates_report.html"


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def _fmt_money(value: float) -> str:
    """Формат только для отображения; расчёты в пайплайне без округления."""
    return f"{float(value or 0):,.2f}".replace(",", "\u00a0").replace(".", ",")


def _build_html(audit: dict) -> str:
    dup_facts = audit.get("duplicate_facts") or []
    cross = audit.get("cross_section_overlaps") or []
    summary = audit.get("summary") or {}

    dup_with_amount = [g for g in dup_facts if (g.get("fingerprint") or {}).get("amount_buh")]
    cross_sections = [g for g in cross if len(g.get("sections") or []) >= 2]

    total_extra = sum(g.get("extra_in_bi", max(0, g.get("count", 0) - 1)) for g in dup_facts)

    css = """
    :root{--bg:#f4f6f9;--card:#fff;--text:#1a1d26;--muted:#5c6370;--accent:#2563eb;
          --warn:#d97706;--bad:#dc2626;--border:#e2e8f0}
    body{font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--text);
         margin:0;line-height:1.5}
    .wrap{max-width:1280px;margin:0 auto;padding:24px 20px 48px}
    h1{font-size:1.6rem;margin:0 0 8px}
    h2{font-size:1.15rem;margin:28px 0 10px;border-bottom:2px solid var(--accent);padding-bottom:6px}
    h3{font-size:.95rem;margin:16px 0 8px;color:var(--muted)}
    .meta{color:var(--muted);font-size:.88rem;margin-bottom:20px}
    .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:16px 0}
    .card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px}
    .card .v{font-size:1.3rem;font-weight:700}.card .l{font-size:.72rem;color:var(--muted);text-transform:uppercase}
    table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--border);
          border-radius:10px;overflow:hidden;font-size:.82rem;margin:12px 0}
    th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}
    th{background:#f8fafc}
    tr:last-child td{border-bottom:none}
    .num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
    .path{font-family:Consolas,"Courier New",monospace;font-size:.78rem;color:#1e3a5f}
    .note{background:#eff6ff;border-left:4px solid var(--accent);padding:10px 14px;border-radius:0 8px 8px 0;
          font-size:.86rem;margin:12px 0}
    .note-warn{background:#fffbeb;border-color:var(--warn)}
    .tag{display:inline-block;background:#e2e8f0;border-radius:4px;padding:1px 6px;margin:2px 2px 0 0;font-size:.75rem}
    ul.loc{list-style:none;padding:0;margin:4px 0}
    ul.loc li{margin:4px 0;padding:6px 8px;background:#f8fafc;border-radius:6px;border:1px solid var(--border)}
    """

    parts = [
        "<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"utf-8\">",
        "<title>AlMaBi — дубли в BI</title>",
        f"<style>{css}</style></head><body><div class=\"wrap\">",
        "<h1>Одинаковые записи в BI</h1>",
        f'<p class="meta">Run: {_esc(audit.get("run_id", "—"))} · '
        f'Сформировано: {datetime.now().strftime("%d.%m.%Y %H:%M")}</p>',
        '<p class="note">Показаны только факты, которые <strong>уже попали в сводку BI</strong> '
        "(после пайплайна). «Лишних» строк в BI по группе = count − 1.</p>",
        '<div class="cards">',
        f'<div class="card"><div class="l">Групп дублей</div><div class="v">{len(dup_facts)}</div></div>',
        f'<div class="card"><div class="l">Лишних в BI (строк)</div><div class="v">{total_extra}</div></div>',
        f'<div class="card"><div class="l">Между статьями 1:1</div><div class="v">{len(cross_sections)}</div></div>',
        f'<div class="card"><div class="l">Групп с суммой ≠ 0</div><div class="v">{len(dup_with_amount)}</div></div>',
        "</div>",
    ]

    parts.append("<h2>1. Точные дубли в BI (одинаковый fingerprint)</h2>")
    parts.append(
        '<p class="note note-warn">Ключ: статья KPI + месяц + номенклатура + статья расхода + '
        "направление + группа + проект + договор + сумма (точное значение). "
        "Каждая строка ниже — группа из 2+ одинаковых фактов.</p>"
    )

    sorted_dup = sorted(
        dup_facts,
        key=lambda g: (
            -(g.get("fingerprint") or {}).get("amount_buh", 0),
            -g.get("count", 0),
        ),
    )

    for idx, group in enumerate(sorted_dup[:80], start=1):
        fp = group.get("fingerprint") or {}
        count = group.get("count", 0)
        extra = group.get("extra_in_bi", count - 1)
        amount = fp.get("amount_buh", 0)
        parts.append(f"<h3>#{idx} · { _esc(fp.get('kpi_l1')) } · {_esc(fp.get('month'))} · "
                     f"×{count} (лишних в BI: {extra}) · сумма {_fmt_money(amount)}</h3>")
        parts.append(
            f'<p><span class="tag">номенклатура</span> {_esc(fp.get("nomenclature") or "—")} '
            f'<span class="tag">договор</span> {_esc(fp.get("contract") or "—")} '
            f'<span class="tag">направление</span> {_esc(fp.get("direction") or "—")}</p>'
        )
        parts.append("<p><strong>Где в дереве BI (каждое вхождение):</strong></p><ul class=\"loc\">")
        for occ in group.get("occurrences") or []:
            parts.append(
                f"<li><span class=\"path\">{_esc(occ.get('bi_path'))}</span> "
                f"· {_esc(occ.get('month'))} · "
                f'<span class="num">{_fmt_money(occ.get("amount_buh") or 0)}</span></li>'
            )
        parts.append("</ul>")

    if len(sorted_dup) > 80:
        parts.append(f'<p class="meta">… ещё {len(sorted_dup) - 80} групп (см. audit-latest.json)</p>')

    parts.append("<h2>2. Одинаковые суммы в разных статьях (1:1 между KPI)</h2>")
    parts.append(
        '<p class="note">Одна номенклатура + сумма одновременно в нескольких статьях P&amp;L. '
        "Не всегда ошибка (зеркальные проводки).</p>"
    )

    if not cross_sections:
        parts.append("<p>Нет пересечений.</p>")
    else:
        parts.append(
            "<table><thead><tr><th>Месяц</th><th>Сумма</th><th>Номенклатура</th>"
            "<th>Статьи</th><th>Место в BI по каждой статье</th></tr></thead><tbody>"
        )
        for item in cross_sections:
            paths_html = []
            by_sec = item.get("bi_paths_by_section") or {}
            for section in item.get("sections") or []:
                paths = by_sec.get(section) or []
                for path in paths:
                    paths_html.append(f"<div class=\"path\">{_esc(section)} → {_esc(path)}</div>")
            if not paths_html:
                for occ in item.get("occurrences") or []:
                    paths_html.append(
                        f"<div class=\"path\">{_esc(occ.get('kpi_l1'))} → {_esc(occ.get('bi_path'))}</div>"
                    )
            parts.append(
                f"<tr><td>{_esc(item.get('month'))}</td>"
                f'<td class="num">{_fmt_money(item.get("amount_buh") or 0)}</td>'
                f"<td>{_esc(item.get('nomenclature') or item.get('expense_article') or '—')}</td>"
                f"<td>{_esc(' + '.join(item.get('sections') or []))}</td>"
                f"<td>{''.join(paths_html)}</td></tr>"
            )
        parts.append("</tbody></table>")

    parts.append(
        f"<h2>3. Сводка audit</h2><p class=\"meta\">"
        f"duplicate_fact_groups: {summary.get('duplicate_fact_groups', len(dup_facts))} · "
        f"cross_section_overlaps: {summary.get('cross_section_overlaps', len(cross))}"
        f"</p></div></body></html>"
    )
    return "\n".join(parts)


def main() -> Path:
    import argparse

    parser = argparse.ArgumentParser(description="Generate AlMaBi duplicates HTML report")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--audit", type=Path, default=AUDIT_PATH)
    args = parser.parse_args()

    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_build_html(audit), encoding="utf-8")
    print(f"Duplicates report: {args.output}")
    return args.output


if __name__ == "__main__":
    main()
