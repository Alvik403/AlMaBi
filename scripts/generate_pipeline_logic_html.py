"""HTML-справка: логика пайплайна AlMaBi — простым языком, по шагам."""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

DEFAULT_OUTPUT = Path.home() / "Downloads" / "almabi_pipeline_logic.html"

CSS = """
:root{--bg:#f4f6f9;--card:#fff;--text:#1a1d26;--muted:#5c6370;--accent:#2563eb;
      --warn:#d97706;--ok:#059669;--border:#e2e8f0;--step:#f8fafc}
*{box-sizing:border-box}
body{font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--text);
     margin:0;line-height:1.6;font-size:15px}
.wrap{max-width:960px;margin:0 auto;padding:24px 20px 48px}
h1{font-size:1.5rem;margin:0 0 4px}
h2{font-size:1.1rem;margin:36px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--accent)}
h3{font-size:1rem;margin:20px 0 8px;color:var(--text)}
.lead{font-size:1.02rem;color:var(--text);margin:12px 0 20px}
.meta{color:var(--muted);font-size:.84rem}
.note{background:#eff6ff;border-left:4px solid var(--accent);padding:12px 16px;border-radius:0 8px 8px 0;
      font-size:.9rem;margin:14px 0}
.note-warn{background:#fffbeb;border-color:var(--warn)}
.note-ok{background:#ecfdf5;border-color:var(--ok)}
nav.toc{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px 20px;margin:18px 0}
nav.toc ol{margin:8px 0 0;padding-left:22px}
nav.toc a{color:var(--accent);text-decoration:none}
nav.toc a:hover{text-decoration:underline}
.files{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:14px 0}
.file-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.file-card h4{margin:0 0 6px;font-size:.95rem}
.file-card p{margin:0;font-size:.88rem;color:var(--muted)}
.file-card .fname{font-family:Consolas,monospace;font-size:.8rem;background:#e2e8f0;
                  padding:2px 8px;border-radius:4px;display:inline-block;margin-bottom:6px}
.recipe{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px 20px;margin:18px 0}
.recipe-header{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:14px}
.recipe-header h3{margin:0;flex:1}
.badge{background:var(--accent);color:#fff;font-size:.75rem;padding:3px 10px;border-radius:20px;font-weight:600}
.badge-expense{background:#7c3aed}
.badge-calc{background:var(--muted)}
.trigger{font-size:.88rem;color:var(--muted);margin:0 0 12px}
.steps{counter-reset:step;list-style:none;padding:0;margin:0}
.steps>li{counter-increment:step;position:relative;padding:12px 14px 12px 48px;
          background:var(--step);border:1px solid var(--border);border-radius:8px;margin-bottom:8px;font-size:.9rem}
.steps>li::before{content:counter(step);position:absolute;left:14px;top:12px;
                  width:24px;height:24px;background:var(--accent);color:#fff;border-radius:50%;
                  font-size:.75rem;font-weight:700;display:flex;align-items:center;justify-content:center}
.steps strong{color:var(--text)}
.steps .from{color:var(--muted);font-size:.84rem;display:block;margin-top:4px}
.arrow{text-align:center;color:var(--muted);font-size:1.2rem;margin:2px 0}
.result{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:8px;padding:10px 14px;
        font-size:.88rem;margin-top:10px}
.tree{background:#1e293b;color:#e2e8f0;font-family:Consolas,monospace;font-size:.82rem;
      padding:12px 16px;border-radius:8px;margin:10px 0;overflow-x:auto}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--border);
      border-radius:10px;overflow:hidden;font-size:.88rem;margin:12px 0}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}
th{background:#f8fafc;width:32%}
tr:last-child td{border-bottom:none}
code{font-family:Consolas,monospace;font-size:.82rem;background:#f1f5f9;padding:1px 5px;border-radius:3px}
.example{background:var(--card);border:2px dashed var(--accent);border-radius:12px;padding:18px 20px;margin:20px 0}
.example h3{margin-top:0}
footer{margin-top:40px;color:var(--muted);font-size:.78rem}
@media(max-width:640px){.files{grid-template-columns:1fr}}
"""


def _esc(value: object) -> str:
    return html.escape(str(value))


def _recipe(
    *,
    section_id: str,
    title: str,
    badge: str,
    badge_class: str,
    trigger: str,
    steps: list[tuple[str, str, str]],
    tree: str,
    extra: str = "",
) -> str:
    """step = (action, from_where, detail)"""
    items = []
    for action, from_where, detail in steps:
        from_line = f'<span class="from">Файл: {from_where}</span>' if from_where else ""
        detail_line = f" — {detail}" if detail else ""
        items.append(f"<li><strong>{action}</strong>{detail_line}{from_line}</li>")

    extra_block = f'<div class="result">{extra}</div>' if extra else ""
    return (
        f'<article class="recipe" id="{section_id}">'
        f'<div class="recipe-header"><h3>{_esc(title)}</h3>'
        f'<span class="badge {badge_class}">{_esc(badge)}</span></div>'
        f'<p class="trigger">{trigger}</p>'
        f'<ol class="steps">{"".join(items)}</ol>'
        f'<p style="margin:12px 0 4px;font-size:.84rem;color:var(--muted)">Как выглядит в дашборде:</p>'
        f'<div class="tree">{tree}</div>'
        f"{extra_block}</article>"
    )


def _build_html() -> str:
    parts = [
        '<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">',
        "<title>AlMaBi — как собираются данные</title>",
        f"<style>{CSS}</style></head><body><div class=\"wrap\">",
        "<h1>Как AlMaBi собирает P&amp;L из выгрузок 1С</h1>",
        f'<p class="meta">Обновлено: {datetime.now().strftime("%d.%m.%Y %H:%M")}</p>',
        '<p class="lead">Система читает <strong>4 Excel-файла</strong>. '
        "Главный — <strong>бухрегистр</strong>: по счёту в строке понимаем, это выручка или расход. "
        "Потом подтягиваем детали из других файлов по <strong>номеру документа</strong> "
        "(например <code>Реализация 00АМ-000123</code> — сравнивается по части <code>00АМ-000123</code>).</p>",
        '<nav class="toc"><strong>Оглавление</strong><ol>',
        '<li><a href="#files">Какие файлы за что отвечают</a></li>',
        '<li><a href="#accounts">Какой счёт → какая статья</a></li>',
        '<li><a href="#example">Пример: одна строка выручки</a></li>',
        '<li><a href="#revenue">Выручка — пошагово</a></li>',
        '<li><a href="#cost">Себестоимость — пошагово</a></li>',
        '<li><a href="#commercial">Коммерческие и управленческие</a></li>',
        '<li><a href="#other">Прочие доходы и расходы</a></li>',
        '<li><a href="#calc">Что считается само (не из 1С)</a></li>',
        '<li><a href="#amort">Амортизация</a></li>',
        '<li><a href="#test-bi">Тест BI — чем отличается</a></li>',
        "</ol></nav>",
    ]

    # Files overview
    parts.append('<section id="files"><h2>Какие файлы за что отвечают</h2>')
    parts.append('<div class="files">')
    file_cards = [
        ("buh.xlsx", "Бухрегистр", "Главный файл. Каждая строка = проводка. По счёту Дт/Кт определяем статью P&amp;L. Отсюда суммы, месяц, договор, льгота."),
        ("realization.xlsx", "Реализация проекты", "Справочник: к какому направлению/проекту относится продажа. Ищем строку с тем же документом, что в бухе."),
        ("cost.xlsx", "Себестоимость", "Детализация себестоимости: сумма, вид затрат (материалы, ФОТ…), иногда направление и договор."),
        ("amortization.xlsx", "Амортизация", "Загружается, но <strong>пока не попадает в отчёт</strong> — логика не подключена."),
    ]
    for fname, title, desc in file_cards:
        parts.append(
            f'<div class="file-card"><span class="fname">{fname}</span>'
            f"<h4>{title}</h4><p>{desc}</p></div>"
        )
    parts.append("</div></section>")

    # Accounts
    parts.append('<section id="accounts"><h2>Какой счёт → какая статья</h2>')
    parts.append(
        '<p class="note">Смотрим только <strong>бухрегистр</strong>. '
        "Одна строка проводки попадает ровно в одну статью (или пропускается, если счёт не из списка).</p>"
    )
    parts.append("<table><tbody>")
    rows = [
        ("Выручка", "Кредит (Кт) счёт <code>90.01.3</code>"),
        ("Себестоимость", "Дебет (Дт) счёт <code>90.02.1</code>"),
        ("Коммерческие расходы", "Дт <code>90.07.1</code>"),
        ("Управленческие расходы", "Дт <code>90.08.1</code>"),
        ("Прочие доходы", "Кт <code>91.01</code>"),
        ("Прочие расходы", "Дт <code>91.02</code>"),
    ]
    for article, rule in rows:
        parts.append(f"<tr><th>{article}</th><td>{rule}</td></tr>")
    parts.append(
        "<tr><th>Налоги, операционная прибыль, чистая прибыль</th>"
        "<td>Не из бухрегистра — <a href=\"#calc\">считаются в дашборде</a> из уже собранных статей</td></tr>"
    )
    parts.append("</tbody></table></section>")

    # Example
    parts.append('<section id="example" class="example"><h2>Пример: одна строка выручки</h2>')
    parts.append("<p>Допустим, в <strong>бухрегистре</strong> есть строка:</p>")
    parts.append("<table><tbody>")
    example_rows = [
        ("Документ", "<code>Реализация товаров 00АМ-000456 от 15.01.2026</code>"),
        ("Счёт Дт / Кт", "<code>62.01</code> / <code>90.01.3</code> → это <strong>Выручка</strong>"),
        ("Сумма", "1 200 000 → попадёт в колонку месяца"),
        ("Дата", "15.01.2026 → <strong>Январь</strong>"),
        ("Субконто НО", "«Доходы по льготируемым…» → <strong>Льготные проекты</strong>"),
    ]
    for k, v in example_rows:
        parts.append(f"<tr><th>{k}</th><td>{v}</td></tr>")
    parts.append("</tbody></table>")
    parts.append('<p><strong>Дальше система делает:</strong></p><ol class="steps">')
    parts.append(
        "<li><strong>Идёт в файл «Реализация»</strong>"
        " — ищет строку, где документ содержит <code>00АМ-000456</code>"
        "<span class=\"from\">Файл: realization.xlsx → колонка «Документ» / «Заказ клиента»</span></li>"
    )
    parts.append(
        "<li><strong>Нашла — берёт оттуда</strong> Направление, Группу проектов, Проект"
        "<span class=\"from\">Файл: realization.xlsx</span></li>"
    )
    parts.append(
        "<li><strong>Складывает строку в BI</strong>: Выручка → Направление → Группа → Проект → Договор"
        "<span class=\"from\">Сумма остаётся из бухрегистра</span></li>"
    )
    parts.append("</ol>")
    parts.append(
        '<div class="tree">Выручка → Основное производство → БДР → П-101 → ДГ-2026/01  &nbsp;|&nbsp;  Январь: 1 200 000</div>'
    )
    parts.append("</section>")

    # Revenue recipe
    parts.append("<h2>Каждая статья — по шагам</h2>")
    parts.append(
        _recipe(
            section_id="revenue",
            title="Выручка",
            badge="из бухрегистра",
            badge_class="",
            trigger="Берём только строки бухрегистра, где <strong>Кт = 90.01.3</strong>.",
            steps=[
                (
                    "Берём сумму для отчёта",
                    "buh.xlsx",
                    "колонки <code>Сумма</code> (бух) и <code>Сумма НУ Кт</code> (налог)",
                ),
                (
                    "Определяем месяц",
                    "buh.xlsx",
                    "колонка <code>Дата</code> → Январь, Февраль…",
                ),
                (
                    "Льготный или нельготный проект",
                    "buh.xlsx",
                    "субконто «Вид налогообложения» на Дт или Кт",
                ),
                (
                    "Ищем направление и проект",
                    "realization.xlsx",
                    "по <code>Документ</code> из буха (сравнение по номеру 00АМ-…). "
                    "Берём <code>Направление</code>, <code>Группа проектов</code>, <code>Проект</code>",
                ),
                (
                    "Договор и контрагент",
                    "buh.xlsx",
                    "колонка/субконто <code>Договор</code>, субконто <code>Контрагент</code>",
                ),
                (
                    "Если в бухе нет ни одной строки 90.01.3",
                    "realization.xlsx",
                    "тогда выручку берём целиком из файла реализации (колонка <code>Выручка</code>) — запасной вариант",
                ),
            ],
            tree="Выручка → Направление → Группа проектов → Проект → Договор",
            extra=(
                "<strong>Поиск в реализации</strong> (по порядку): "
                "1) договор + номенклатура → 2) только договор → "
                "3) документ + номенклатура → 4) только документ"
            ),
        )
    )

    # Cost recipe
    parts.append(
        _recipe(
            section_id="cost",
            title="Себестоимость",
            badge="бух + cost + реализация",
            badge_class="",
            trigger="Берём строки бухрегистра, где <strong>Дт = 90.02.1</strong>.",
            steps=[
                (
                    "Ищем детализацию в файле себестоимости",
                    "cost.xlsx",
                    "ключ: <code>Документ отгрузки</code> из cost = <code>Документ</code> из буха "
                    "+ совпадает <code>Номенклатура</code> (в бухе — субконто Кт)",
                ),
                (
                    "Если нашли — сумму БУ берём из cost",
                    "cost.xlsx",
                    "колонка <code>Себестоимость (бухг. учет)</code> (не из буха!)",
                ),
                (
                    "Если не нашли — сумму БУ берём из буха",
                    "buh.xlsx",
                    "колонка <code>Сумма</code>",
                ),
                (
                    "Вид затрат (материалы, ФОТ, аренда…)",
                    "cost.xlsx",
                    "колонки <code>Счёт</code> и <code>Статья калькуляции</code> → подстатья в дереве",
                ),
                (
                    "Направление и проект",
                    "cost.xlsx → realization.xlsx",
                    "сначала из cost; если пусто — ищем в реализации. "
                    "Для себестоимости цепочка: продукция из cost → договор → реализация",
                ),
                (
                    "Сумма НУ",
                    "buh.xlsx",
                    "всегда <code>Сумма НУ Кт</code>",
                ),
            ],
            tree="Себестоимость → Материальные затраты / ФОТ / … → Направление → Группа → Проект",
            extra=(
                "<strong>Подстатьи из cost:</strong> счета 10, 20 → Материалы; "
                "в статье «фот/зарплат» → ФОТ; «аренд» → Аренда; «амортиз» → Амортизация; остальное → ОПЗ"
            ),
        )
    )

    # Commercial
    parts.append(
        _recipe(
            section_id="commercial",
            title="Коммерческие и управленческие расходы",
            badge="только бухрегистр",
            badge_class="badge-expense",
            trigger="Дт <code>90.07.1</code> (коммерческие) или Дт <code>90.08.1</code> (управленческие).",
            steps=[
                ("Суммы", "buh.xlsx", "<code>Сумма</code> и <code>Сумма НУ Дт</code>"),
                ("Месяц", "buh.xlsx", "<code>Дата</code>"),
                ("Льгота / нельгота", "buh.xlsx", "субконто налогообложения"),
                ("Договор", "buh.xlsx", "колонка или субконто договора"),
                (
                    "Направление и проект",
                    "",
                    "обычно <strong>не заполняются</strong> — в реализацию по расходам почти не ходим",
                ),
            ],
            tree="Коммерческие расходы → Льготные / Нельготные → Договор",
        )
    )

    # Other income/expense
    parts.append(
        _recipe(
            section_id="other",
            title="Прочие доходы и прочие расходы",
            badge="только бухрегистр",
            badge_class="badge-expense",
            trigger="Кт <code>91.01</code> (доходы) или Дт <code>91.02</code> (расходы).",
            steps=[
                ("Суммы", "buh.xlsx", "<code>Сумма</code> и НУ (Кт для доходов, Дт для расходов)"),
                ("Месяц", "buh.xlsx", "<code>Дата</code>"),
                (
                    "Название статьи внутри KPI",
                    "buh.xlsx",
                    "субконто «Статьи затрат» — например «Проценты», «Штрафы»",
                ),
                ("Льгота / нельгота", "buh.xlsx", "субконто налогообложения"),
                ("Договор", "buh.xlsx", "колонка или субконто"),
            ],
            tree="Прочие расходы → Нельготные → Штрафы → Д-014",
        )
    )

    # Calculated
    parts.append('<section id="calc"><h2>Что считается само (не из файлов 1С)</h2>')
    parts.append(
        '<p class="note note-ok">Эти строки <strong>не читаются из Excel</strong>. '
        "Дашборд складывает уже готовые статьи по формулам.</p>"
    )
    parts.append("<table><thead><tr><th>Строка в BI</th><th>Формула простыми словами</th></tr></thead><tbody>")
    calc_rows = [
        (
            "Операционная прибыль",
            "Выручка минус Себестоимость минус Коммерческие минус Управленческие (по каждому месяцу)",
        ),
        (
            "Прибыль до налогообложения",
            "Операционная плюс Прочие доходы минус Прочие расходы",
        ),
        (
            "Налоги",
            "Отдельная упрощённая модель: 25% от суммы НУ по выручке, себестоимости и прочим "
            "(или 2% для льготных). <em>Не проводки по счёту 68.</em>",
        ),
        (
            "Чистая прибыль",
            "Прибыль до налогообложения минус Налоги",
        ),
    ]
    for title, formula in calc_rows:
        parts.append(f"<tr><th>{title}</th><td>{formula}</td></tr>")
    parts.append("</tbody></table></section>")

    # Amortization
    parts.append('<section id="amort"><h2>Амортизация</h2>')
    parts.append(
        '<p class="note note-warn">Файл <code>amortization.xlsx</code> можно загрузить — '
        "система читает дату, статью расходов и сумму НУ. "
        "Но <strong>в сводку P&amp;L эти данные не попадают</strong> — раздел пока не подключён.</p>"
    )
    parts.append("</section>")

    # Test BI
    parts.append('<section id="test-bi"><h2>Тест BI — чем отличается</h2>')
    parts.append("<table><thead><tr><th></th><th>Обычный дашборд</th><th>Тест BI</th></tr></thead><tbody>")
    compare = [
        ("Направление из cost и realization", "Берётся из того, где нашлось", "Строже: если оба дали разное — оставляет пусто"),
        ("Реализация для расходов", "Только выручка и себестоимость", "И для прочих доходов/расходов тоже"),
        ("Журнал проверки", "Нет", "Пишет audit в logs/almabi_test/"),
    ]
    for aspect, normal, test in compare:
        parts.append(f"<tr><th>{aspect}</th><td>{normal}</td><td>{test}</td></tr>")
    parts.append("</tbody></table></section>")

    parts.append(
        f'<footer>AlMaBi · как собираются данные · {datetime.now().strftime("%d.%m.%Y %H:%M")}</footer>'
    )
    parts.append("</div></body></html>")
    return "\n".join(parts)


def main() -> Path:
    import argparse

    parser = argparse.ArgumentParser(description="Generate AlMaBi pipeline logic HTML guide")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_build_html(), encoding="utf-8")
    print(f"Pipeline logic guide: {args.output}")
    return args.output


if __name__ == "__main__":
    main()
