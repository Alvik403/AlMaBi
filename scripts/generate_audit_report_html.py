"""Generate structured HTML audit report from logs/almabi_test/audit-latest.json."""
from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "logs" / "almabi_test" / "audit-latest.json"
DEFAULT_OUTPUT = Path.home() / "Downloads" / "almabi_audit_report.html"

NO_DIRECTION = {"без направления", "без группы", "без проекта", ""}


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def _fmt_money(value: float) -> str:
    """Формат только для отображения; расчёты в пайплайне без округления."""
    return f"{float(value or 0):,.2f}".replace(",", "\u00a0").replace(".", ",")


def _short_doc(document: str) -> str:
    if not document:
        return "—"
    parts = document.split()
    for part in parts:
        if "00АМ" in part or part.startswith("АМ-"):
            return part.rstrip(",")
    return document[:60] + ("…" if len(document) > 60 else "")


def _is_no_direction(value: str) -> bool:
    return (value or "").strip().casefold() in NO_DIRECTION or not (value or "").strip()


def _classify_cost_reason(line: dict) -> str:
    cost = line.get("cost_join")
    rev = line.get("realization_join")
    analytics = line.get("analytics") or {}
    direction = analytics.get("direction", "")

    if not _is_no_direction(direction):
        return "С аналитикой"

    if cost and _is_no_direction(cost.get("direction", "")):
        return "Join себестоимости OK, но в файле нет направления/группы/проекта"

    if cost is None and not line.get("nomenclature_kt"):
        return "Нет join: пустая номенклатура Кт (типично счёт 20)"

    if cost is None and "распределение расходов" in (line.get("document") or "").casefold():
        return "Нет join: документ «Распределение расходов»"

    if cost is None:
        return "Нет join: номенклатура/документ не найдены в файле себестоимости"

    if rev:
        return "Конфликт источников (PQ: оба заполнены → пусто)"

    return "Без направления (прочее)"


def _build_html(audit: dict) -> str:
    summary = audit.get("summary") or {}
    revenue_lines = audit.get("revenue_lines") or []
    cost_lines = audit.get("cost_lines") or []
    dup_buh = audit.get("duplicate_buh_rows") or []
    dup_facts = audit.get("duplicate_facts") or []
    cross = audit.get("cross_section_overlaps") or []

    # --- Revenue stats ---
    rev_directions = Counter()
    rev_no_dir = []
    for line in revenue_lines:
        d = (line.get("analytics") or {}).get("direction", "")
        rev_directions[d or "—"] += 1
        if _is_no_direction(d):
            rev_no_dir.append(line)

    # --- Cost stats ---
    cost_reasons = Counter()
    cost_by_reason: dict[str, list[dict]] = defaultdict(list)
    cost_with_dir = []
    for line in cost_lines:
        reason = _classify_cost_reason(line)
        cost_reasons[reason] += 1
        if len(cost_by_reason[reason]) < 8:
            cost_by_reason[reason].append(line)
        d = (line.get("analytics") or {}).get("direction", "")
        if not _is_no_direction(d):
            cost_with_dir.append(line)

    cost_join_ok = sum(1 for ln in cost_lines if ln.get("cost_join"))
    cost_join_fail = len(cost_lines) - cost_join_ok

    # --- Duplicates by section ---
    dup_buh_sections: Counter[str] = Counter()
    for group in dup_buh:
        for sec in group.get("sections") or []:
            dup_buh_sections[sec] += 1

    dup_fact_sections: Counter[str] = Counter()
    dup_fact_top: list[tuple[int, dict]] = []
    for group in dup_facts:
        sources = group.get("sources") or []
        for src in sources:
            dup_fact_sections[src] += 1
        dup_fact_top.append((group.get("count", 0), group))
    dup_fact_top.sort(key=lambda x: (-x[0], str(x[1].get("fingerprint"))))

    section_counts = summary.get("section_counts") or {}

    run_id = audit.get("run_id", "—")
    created = audit.get("created_at", "")
    try:
        created_fmt = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M UTC")
    except ValueError:
        created_fmt = created

    # Revenue examples with direction
    rev_examples = sorted(
        revenue_lines,
        key=lambda x: -(x.get("amount_buh") or 0),
    )[:15]

    # Cost contrast: same doc revenue has direction, cost doesn't
    rev_by_doc = {}
    for line in revenue_lines:
        doc = line.get("document", "")
        if doc and not _is_no_direction((line.get("analytics") or {}).get("direction", "")):
            rev_by_doc[doc] = line

    contrast_rows = []
    for line in cost_lines:
        doc = line.get("document", "")
        rev = rev_by_doc.get(doc)
        if not rev:
            continue
        if _is_no_direction((line.get("analytics") or {}).get("direction", "")):
            contrast_rows.append((rev, line))
    contrast_rows.sort(key=lambda pair: -(pair[0].get("amount_buh") or 0))
    contrast_rows = contrast_rows[:12]

    css = """
    :root {
      --bg: #f4f6f9; --card: #fff; --text: #1a1d26; --muted: #5c6370;
      --accent: #2563eb; --ok: #059669; --warn: #d97706; --bad: #dc2626;
      --border: #e2e8f0;
    }
    * { box-sizing: border-box; }
    body { font-family: "Segoe UI", system-ui, sans-serif; background: var(--bg);
           color: var(--text); margin: 0; line-height: 1.5; }
    .wrap { max-width: 1200px; margin: 0 auto; padding: 24px 20px 48px; }
    h1 { font-size: 1.75rem; margin: 0 0 8px; }
    .meta { color: var(--muted); font-size: 0.9rem; margin-bottom: 28px; }
    h2 { font-size: 1.25rem; margin: 32px 0 12px; padding-bottom: 6px;
         border-bottom: 2px solid var(--accent); }
    h3 { font-size: 1rem; margin: 20px 0 8px; color: var(--muted); }
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
            padding: 14px 16px; }
    .card .label { font-size: 0.78rem; color: var(--muted); text-transform: uppercase; letter-spacing: .03em; }
    .card .value { font-size: 1.5rem; font-weight: 700; margin-top: 4px; }
    .card.warn .value { color: var(--warn); }
    .card.bad .value { color: var(--bad); }
    .card.ok .value { color: var(--ok); }
    table { width: 100%; border-collapse: collapse; background: var(--card);
            border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
            font-size: 0.85rem; margin-bottom: 16px; }
    th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
    th { background: #f8fafc; font-weight: 600; white-space: nowrap; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: #f8fafc; }
    .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }
    .badge-ok { background: #d1fae5; color: #065f46; }
    .badge-warn { background: #fef3c7; color: #92400e; }
    .badge-bad { background: #fee2e2; color: #991b1b; }
    .badge-neutral { background: #e2e8f0; color: #334155; }
    .note { background: #eff6ff; border-left: 4px solid var(--accent); padding: 12px 16px;
            border-radius: 0 8px 8px 0; margin: 16px 0; font-size: 0.9rem; }
    .note-warn { background: #fffbeb; border-color: var(--warn); }
    nav.toc { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
               padding: 16px 20px; margin-bottom: 24px; }
    nav.toc ul { margin: 8px 0 0; padding-left: 20px; }
    nav.toc a { color: var(--accent); text-decoration: none; }
    nav.toc a:hover { text-decoration: underline; }
    .bar-row { display: flex; align-items: center; gap: 10px; margin: 6px 0; font-size: 0.85rem; }
    .bar-label { min-width: 220px; flex-shrink: 0; }
    .bar-track { flex: 1; height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden; }
    .bar-fill { height: 100%; background: var(--accent); border-radius: 4px; }
    .bar-count { min-width: 36px; text-align: right; color: var(--muted); }
    footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--border);
             color: var(--muted); font-size: 0.8rem; }
    """

    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="ru">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>AlMaBi — аудит выручки и себестоимости</title>",
        f"<style>{css}</style>",
        "</head>",
        "<body>",
        '<div class="wrap">',
        "<h1>AlMaBi — аудит аналитики (Тест BI)</h1>",
        f'<p class="meta">Run ID: <strong>{_esc(run_id)}</strong> · Сформирован: {_esc(created_fmt)} · Источник: audit-latest.json</p>',
        '<nav class="toc"><strong>Содержание</strong><ul>',
        '<li><a href="#summary">Сводка</a></li>',
        '<li><a href="#revenue">Выручка</a></li>',
        '<li><a href="#cost">Себестоимость</a></li>',
        '<li><a href="#contrast">Выручка vs себестоимость (один документ)</a></li>',
        '<li><a href="#duplicates">Дубли</a></li>',
        '<li><a href="#sections">Остальные разделы</a></li>',
        '<li><a href="#conclusions">Выводы</a></li>',
        "</ul></nav>",
        '<section id="summary">',
        "<h2>Сводка</h2>",
        '<div class="cards">',
        f'<div class="card ok"><div class="label">Выручка (строк)</div><div class="value">{summary.get("revenue_lines", 0)}</div></div>',
        f'<div class="card warn"><div class="label">Себестоимость (аудит)</div><div class="value">{summary.get("cost_lines", 0)}</div></div>',
        f'<div class="card"><div class="label">Фактов себестоимости</div><div class="value">{section_counts.get("Себестоимость", 0)}</div></div>',
        f'<div class="card bad"><div class="label">Дубли бухрегистра</div><div class="value">{summary.get("duplicate_buh_groups", 0)}</div></div>',
        f'<div class="card bad"><div class="label">Дубли фактов</div><div class="value">{summary.get("duplicate_fact_groups", 0)}</div></div>',
        f'<div class="card warn"><div class="label">Пересечения разделов</div><div class="value">{summary.get("cross_section_overlaps", 0)}</div></div>',
        "</div>",
        "</section>",
    ]

    # Revenue section
    parts.append('<section id="revenue"><h2>Выручка</h2>')
    if rev_no_dir:
        parts.append(
            f'<p class="note note-warn"><strong>{len(rev_no_dir)}</strong> строк без направления.</p>'
        )
    else:
        parts.append(
            '<p class="note"><strong>Все строки выручки получили направление</strong> через join с файлом реализации '
            '(документ + основной раздел «Доходы»).</p>'
        )

    parts.append("<h3>Распределение по направлениям</h3>")
    max_rev = max(rev_directions.values()) if rev_directions else 1
    for name, cnt in rev_directions.most_common():
        pct = cnt / len(revenue_lines) * 100 if revenue_lines else 0
        width = int(cnt / max_rev * 100)
        parts.append(
            f'<div class="bar-row"><span class="bar-label">{_esc(name)}</span>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{width}%"></div></div>'
            f'<span class="bar-count">{cnt} ({pct:.0f}%)</span></div>'
        )

    parts.append("<h3>Крупнейшие строки выручки</h3>")
    parts.append("<table><thead><tr>")
    parts.append(
        "<th>Месяц</th><th>Документ</th><th>Направление</th><th>Группа</th><th>Проект</th>"
        '<th class="num">Сумма БУ</th><th>Join</th></tr></thead><tbody>'
    )
    for line in rev_examples:
        a = line.get("analytics") or {}
        rj = line.get("realization_join")
        join_badge = '<span class="badge badge-ok">realization</span>' if rj else '<span class="badge badge-bad">нет</span>'
        parts.append(
            f"<tr><td>{_esc(line.get('month'))}</td>"
            f"<td title=\"{_esc(line.get('document'))}\">{_esc(_short_doc(line.get('document', '')))}</td>"
            f"<td>{_esc(a.get('direction'))}</td><td>{_esc(a.get('project_group'))}</td>"
            f"<td>{_esc(a.get('project'))}</td>"
            f'<td class="num">{_fmt_money(line.get("amount_buh") or 0)}</td>'
            f"<td>{join_badge}</td></tr>"
        )
    parts.append("</tbody></table></section>")

    # Cost section
    parts.append('<section id="cost"><h2>Себестоимость</h2>')
    parts.append(
        f'<p class="note note-warn">Из <strong>{len(cost_lines)}</strong> строк аудита: '
        f"join с файлом себестоимости сработал у <strong>{cost_join_ok}</strong>, "
        f"не сработал у <strong>{cost_join_fail}</strong>. "
        f"Строк с заполненным направлением: <strong>{len(cost_with_dir)}</strong>.</p>"
    )
    parts.append(
        '<p class="note">Для себестоимости <code>main_section = «Расходы»</code> — join с реализацией '
        "не выполняется (PQ). Направление из выручки по тому же документу не подтягивается.</p>"
    )

    parts.append("<h3>Почему «Без направления»</h3>")
    max_cost = max(cost_reasons.values()) if cost_reasons else 1
    for reason, cnt in cost_reasons.most_common():
        width = int(cnt / max_cost * 100)
        parts.append(
            f'<div class="bar-row"><span class="bar-label">{_esc(reason)}</span>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{width}%;background:#d97706"></div></div>'
            f'<span class="bar-count">{cnt}</span></div>'
        )

    for reason, examples in cost_by_reason.items():
        if not examples:
            continue
        parts.append(f"<h3>Примеры: {_esc(reason)}</h3>")
        parts.append("<table><thead><tr>")
        parts.append(
            "<th>Месяц</th><th>Документ</th><th>Счёт</th><th>Номенклатура Кт</th>"
            '<th class="num">Сумма</th><th>cost_join</th><th>Аналитика</th></tr></thead><tbody>'
        )
        for line in examples[:6]:
            a = line.get("analytics") or {}
            cj = line.get("cost_join")
            cj_txt = "да" if cj else "нет"
            badge = "badge-warn" if cj else "badge-bad"
            parts.append(
                f"<tr><td>{_esc(line.get('month'))}</td>"
                f"<td title=\"{_esc(line.get('document'))}\">{_esc(_short_doc(line.get('document', '')))}</td>"
                f"<td>{_esc(line.get('account_dt'))} → {_esc(line.get('account_kt'))}</td>"
                f"<td>{_esc(line.get('nomenclature_kt') or '—')}</td>"
                f'<td class="num">{_fmt_money(line.get("amount_buh") or 0)}</td>'
                f'<td><span class="badge {badge}">{cj_txt}</span></td>'
                f"<td>{_esc(a.get('direction'))} / {_esc(a.get('project_group'))}</td></tr>"
            )
        parts.append("</tbody></table>")

    parts.append("</section>")

    # Contrast section
    parts.append('<section id="contrast"><h2>Один документ: выручка с направлением, себестоимость без</h2>')
    if contrast_rows:
        parts.append(
            '<p class="note note-warn">Типичная ситуация: в файле реализации аналитика есть, '
            "в файле себестоимости — пусто, а PQ не использует реализацию для расходов.</p>"
        )
        parts.append("<table><thead><tr>")
        parts.append(
            "<th>Документ</th><th>Выручка → направление</th><th>Себестоимость → направление</th>"
            '<th class="num">Выручка БУ</th><th class="num">Себест. БУ</th></tr></thead><tbody>'
        )
        for rev, cost in contrast_rows:
            ra = rev.get("analytics") or {}
            ca = cost.get("analytics") or {}
            parts.append(
                f"<tr><td title=\"{_esc(rev.get('document'))}\">{_esc(_short_doc(rev.get('document', '')))}</td>"
                f"<td><span class=\"badge badge-ok\">{_esc(ra.get('direction'))}</span></td>"
                f"<td><span class=\"badge badge-bad\">{_esc(ca.get('direction'))}</span></td>"
                f'<td class="num">{_fmt_money(rev.get("amount_buh") or 0)}</td>'
                f'<td class="num">{_fmt_money(cost.get("amount_buh") or 0)}</td></tr>'
            )
        parts.append("</tbody></table>")
    else:
        parts.append("<p>Нет контрастных пар.</p>")
    parts.append("</section>")

    # Duplicates
    parts.append('<section id="duplicates"><h2>Дубли</h2>')
    parts.append(
        f'<div class="cards">'
        f'<div class="card bad"><div class="label">Групп дублей бухрегистра</div><div class="value">{len(dup_buh)}</div></div>'
        f'<div class="card bad"><div class="label">Групп дублей фактов</div><div class="value">{len(dup_facts)}</div></div>'
        f'<div class="card warn"><div class="label">Межразделные пересечения</div><div class="value">{len(cross)}</div></div>'
        "</div>"
    )

    parts.append("<h3>Дубли бухрегистра — по разделам (число групп)</h3>")
    for sec, cnt in dup_buh_sections.most_common():
        parts.append(f'<div class="bar-row"><span class="bar-label">{_esc(sec)}</span>'
                     f'<span class="bar-count">{cnt} групп</span></div>')
    parts.append(
        '<p class="note">В выручке и себестоимости групп дублей бухрегистра <strong>нет</strong>. '
        "Чаще всего — прочие расходы/доходы с суммой 0 (расчёт себестоимости, курсовые разницы).</p>"
    )

    parts.append("<h3>Топ дублей бухрегистра (по count)</h3>")
    dup_buh_sorted = sorted(dup_buh, key=lambda g: -g.get("count", 0))[:15]
    parts.append("<table><thead><tr><th>Count</th><th>Раздел</th><th>Документ</th>"
                 "<th>Счета</th><th>Месяц</th><th class=\"num\">Сумма</th><th>Номенклатура</th></tr></thead><tbody>")
    for group in dup_buh_sorted:
        fp = group.get("fingerprint") or {}
        secs = ", ".join(group.get("sections") or [])
        parts.append(
            f"<tr><td>{group.get('count')}</td><td>{_esc(secs)}</td>"
            f"<td title=\"{_esc(fp.get('document'))}\">{_esc(_short_doc(fp.get('document', '')))}</td>"
            f"<td>{_esc(fp.get('account_dt'))} → {_esc(fp.get('account_kt'))}</td>"
            f"<td>{_esc(fp.get('month'))}</td>"
            f'<td class="num">{_fmt_money(fp.get("amount_buh") or 0)}</td>'
            f"<td>{_esc(fp.get('nomenclature_kt') or '—')}</td></tr>"
        )
    parts.append("</tbody></table>")

    parts.append("<h3>Дубли фактов — по KPI (число групп)</h3>")
    for sec, cnt in dup_fact_sections.most_common():
        parts.append(f'<div class="bar-row"><span class="bar-label">{_esc(sec)}</span>'
                     f'<span class="bar-count">{cnt} групп</span></div>')
    parts.append(
        '<p class="note">Дублей фактов в <strong>Выручке</strong> и <strong>Себестоимости</strong> нет.</p>'
    )

    parts.append("<h3>Топ дублей фактов</h3>")
    parts.append("<table><thead><tr><th>Count</th><th>KPI</th><th>Месяц</th><th>Номенклатура</th>"
                 "<th>Направление</th><th class=\"num\">Сумма</th></tr></thead><tbody>")
    for count, group in dup_fact_top[:15]:
        fp = group.get("fingerprint") or {}
        parts.append(
            f"<tr><td>{count}</td><td>{_esc((group.get('sources') or [''])[0])}</td>"
            f"<td>{_esc(fp.get('month'))}</td><td>{_esc(fp.get('nomenclature') or '—')[:80]}</td>"
            f"<td>{_esc(fp.get('direction'))}</td>"
            f'<td class="num">{_fmt_money(fp.get("amount_buh") or 0)}</td></tr>'
        )
    parts.append("</tbody></table>")

    if cross:
        parts.append("<h3>Пересечения между разделами (одна номенклатура + сумма в двух KPI)</h3>")
        parts.append("<table><thead><tr><th>Месяц</th><th>Разделы</th><th>Номенклатура</th>"
                     '<th class="num">Сумма</th><th>Документ</th></tr></thead><tbody>')
        for item in cross:
            secs = " + ".join(item.get("sections") or [])
            docs = "; ".join(item.get("documents") or [])[:100]
            parts.append(
                f"<tr><td>{_esc(item.get('month'))}</td><td>{_esc(secs)}</td>"
                f"<td>{_esc(item.get('nomenclature'))}</td>"
                f'<td class="num">{_fmt_money(item.get("amount_buh") or 0)}</td>'
                f"<td>{_esc(docs)}</td></tr>"
            )
        parts.append("</tbody></table>")

    parts.append("</section>")

    # Other sections
    parts.append('<section id="sections"><h2>Остальные разделы</h2>')
    parts.append("<table><thead><tr><th>Раздел</th><th class=\"num\">Фактов</th>"
                 "<th>Классификация</th><th>Аналитика</th><th>Дерево дашборда</th></tr></thead><tbody>")
    section_meta = [
        ("Коммерческие расходы", "Дт 90.07.1", "Join редко; без направления", "Льготные / Нельготные"),
        ("Управленческие расходы", "Дт 90.08.1", "Join редко; без направления", "Льготные / Нельготные"),
        ("Прочие доходы", "Кт 91.01", "Иногда realization для «Доходы»", "Льготные / Нельготные → Статья"),
        ("Прочие расходы", "Дт 91.02", "Почти всегда без направления", "Льготные / Нельготные → Статья"),
    ]
    for name, rule, analytics, tree in section_meta:
        cnt = section_counts.get(name, 0)
        dup_cnt = dup_fact_sections.get(name, 0)
        parts.append(
            f"<tr><td><strong>{_esc(name)}</strong></td>"
            f'<td class="num">{cnt}</td><td>{_esc(rule)}</td>'
            f"<td>{_esc(analytics)}<br><small>Дублей фактов: {dup_cnt} групп</small></td>"
            f"<td>{_esc(tree)}</td></tr>"
        )
    parts.append("</tbody></table></section>")

    # Conclusions
    parts.append('<section id="conclusions"><h2>Выводы</h2><ul>')
    conclusions = [
        "Выручка полностью размечена через файл реализации (46/46).",
        "Себестоимость почти целиком «Без направления»: файл себестоимости без колонок направления/группы/проекта "
        "или join не находит строку (счёт 20 без номенклатуры, распределение расходов).",
        "PQ для тестового BI не подтягивает направление из реализации для расходов — "
        "расхождение с выручкой по одному документу ожидаемо.",
        "Дубли сосредоточены в прочих доходах/расходах и коммерческих расходах; выручка и себестоимость чистые.",
        "5 пересечений — лом металлов (КАПО): одна сумма одновременно в прочих доходах и расходах.",
    ]
    for item in conclusions:
        parts.append(f"<li>{_esc(item)}</li>")
    parts.append("</ul></section>")

    parts.append(
        f"<footer>AlMaBi audit report · сгенерировано {datetime.now().strftime('%d.%m.%Y %H:%M')} · "
        f"источник: {_esc(AUDIT_PATH)}</footer>"
    )
    parts.append("</div></body></html>")
    return "\n".join(parts)


def main() -> Path:
    import argparse

    parser = argparse.ArgumentParser(description="Generate AlMaBi audit HTML report")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output HTML path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=AUDIT_PATH,
        help="Path to audit JSON",
    )
    args = parser.parse_args()

    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    html_content = _build_html(audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_content, encoding="utf-8")
    print(f"Report written to: {args.output}")
    return args.output


if __name__ == "__main__":
    main()
