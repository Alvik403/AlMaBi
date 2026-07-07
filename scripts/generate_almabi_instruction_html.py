"""Инструкция пользователя AlMaBi → HTML в Загрузки."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

DEFAULT_OUTPUT = Path.home() / "Downloads" / "almabi_instruction.html"

CSS = """
:root{--bg:#f4f6f9;--card:#fff;--text:#1a1d26;--muted:#5c6370;--accent:#2563eb;
      --warn:#d97706;--ok:#059669;--border:#e2e8f0}
body{font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--text);
     margin:0;line-height:1.6;font-size:15px}
.wrap{max-width:920px;margin:0 auto;padding:28px 20px 56px}
h1{font-size:1.55rem;margin:0 0 6px}
h2{font-size:1.1rem;margin:34px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--accent)}
h3{font-size:.98rem;margin:18px 0 8px}
.meta{color:var(--muted);font-size:.84rem;margin-bottom:16px}
.lead{font-size:1.02rem;margin:10px 0 18px}
.note{background:#eff6ff;border-left:4px solid var(--accent);padding:12px 16px;border-radius:0 8px 8px 0;
      font-size:.9rem;margin:14px 0}
.note-warn{background:#fffbeb;border-color:var(--warn)}
.note-ok{background:#ecfdf5;border-color:var(--ok)}
nav.toc{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px 20px;margin:18px 0}
nav.toc ol{margin:8px 0 0;padding-left:22px}
nav.toc a{color:var(--accent);text-decoration:none}
nav.toc a:hover{text-decoration:underline}
.steps{counter-reset:step;list-style:none;padding:0;margin:14px 0}
.steps>li{counter-increment:step;position:relative;padding:14px 14px 14px 52px;
          background:var(--card);border:1px solid var(--border);border-radius:10px;margin-bottom:10px}
.steps>li::before{content:counter(step);position:absolute;left:14px;top:14px;width:26px;height:26px;
                  background:var(--accent);color:#fff;border-radius:50%;font-size:.78rem;font-weight:700;
                  display:flex;align-items:center;justify-content:center}
.steps strong{display:block;margin-bottom:4px}
.steps p{margin:4px 0 0;font-size:.9rem;color:var(--muted)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--border);
      border-radius:10px;overflow:hidden;font-size:.88rem;margin:12px 0}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}
th{background:#f8fafc;width:30%}
tr:last-child td{border-bottom:none}
code{font-family:Consolas,monospace;font-size:.82rem;background:#f1f5f9;padding:1px 6px;border-radius:4px}
.url{font-family:Consolas,monospace;font-size:.85rem;color:var(--accent)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:12px 0}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.card h4{margin:0 0 8px;font-size:.92rem}
.card p{margin:0;font-size:.86rem;color:var(--muted)}
.cmd{background:#1e293b;color:#e2e8f0;font-family:Consolas,monospace;font-size:.82rem;
     padding:12px 14px;border-radius:8px;margin:10px 0;overflow-x:auto}
footer{margin-top:40px;color:var(--muted);font-size:.78rem}
@media(max-width:640px){.grid2{grid-template-columns:1fr}}
"""


def _build_html() -> str:
    ts = datetime.now().strftime("%d.%m.%Y %H:%M")
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>AlMaBi — инструкция</title>
<style>{CSS}</style></head><body><div class="wrap">

<h1>Инструкция AlMaBi</h1>
<p class="meta">Версия от {ts}</p>
<p class="lead">AlMaBi — дашборд P&amp;L из выгрузок 1С. Загружаете четыре Excel-файла, система собирает сводку по статьям, направлениям, договорам и контрагентам.</p>

<nav class="toc"><strong>Содержание</strong><ol>
<li><a href="#start">Быстрый старт</a></li>
<li><a href="#upload">Загрузка выгрузок</a></li>
<li><a href="#files">Какие файлы нужны</a></li>
<li><a href="#dashboard">Работа с дашбордом</a></li>
<li><a href="#test">Тест BI и проверка</a></li>
<li><a href="#reports">Отчёты в Загрузках</a></li>
<li><a href="#amounts">Суммы и округление</a></li>
<li><a href="#accounts">Счета и статьи</a></li>
<li><a href="#issues">Частые вопросы</a></li>
</ol></nav>

<section id="start"><h2>1. Быстрый старт</h2>
<ol class="steps">
<li><strong>Запустить сервис</strong>
<p>В папке проекта: <code>docker compose up --build -d</code></p></li>
<li><strong>Открыть дашборд</strong>
<p class="url">http://localhost:18001/dashboard/almabi</p></li>
<li><strong>Загрузить выгрузки 1С</strong>
<p>Шестерёнка справа вверху → форма с 4 файлами → «Загрузить и собрать дашборд»</p></li>
</ol>
<p class="note note-ok">Минимум для работы: <strong>бухрегистр</strong>, <strong>реализация</strong> и <strong>себестоимость</strong>. Амортизация опциональна (пока не влияет на P&amp;L).</p>
</section>

<section id="upload"><h2>2. Загрузка выгрузок</h2>
<ol class="steps">
<li><strong>Откройте меню загрузки</strong>
<p>Иконка шестерёнки в правом верхнем углу на странице AlMaBi.</p></li>
<li><strong>Выберите файлы</strong>
<p>Можно перетащить все .xlsx сразу — тип определяется автоматически по шапке листа.</p></li>
<li><strong>Нажмите «Загрузить и собрать дашборд»</strong>
<p>После успешной загрузки таблица обновится. Имена загруженных файлов видны под заголовком.</p></li>
<li><strong>При ошибке</strong>
<p>Проверьте, что файл — .xlsx с ожидаемыми колонками (см. раздел «Какие файлы нужны»).</p></li>
</ol>
</section>

<section id="files"><h2>3. Какие файлы нужны</h2>
<table><tbody>
<tr><th>Бух.регистр</th><td>Главный файл. Проводки: документ, счёт Дт/Кт, сумма, дата, субконто (НО, договор, номенклатура, контрагент).</td></tr>
<tr><th>Реализация</th><td>Продажи с аналитикой: документ, номенклатура, выручка, направление, группа проектов, проект, договор.</td></tr>
<tr><th>Себестоимость</th><td>Документ отгрузки, продукция, сумма себестоимости, счёт, статья калькуляции; при наличии — направление и договор.</td></tr>
<tr><th>Амортизация</th><td>Опционально. Парсится, но в сводку P&amp;L пока не попадает.</td></tr>
</tbody></table>
<p class="note">Связь между файлами — по <strong>номеру документа</strong> (например <code>00АМ-000456</code> в тексте «Реализация … от …»).</p>
</section>

<section id="dashboard"><h2>4. Работа с дашбордом</h2>
<h3>Вкладки</h3>
<table><tbody>
<tr><th>Сводная информация</th><td>Дерево P&amp;L: выручка, себестоимость, расходы, прибыль. Раскрывайте строки стрелкой.</td></tr>
<tr><th>Детализация выручки</th><td>Графики выручки и себестоимости по месяцам.</td></tr>
<tr><th>Контрагенты</th><td>Выручка по контрагентам, разбивка льгота / нельгота.</td></tr>
</tbody></table>

<h3>Панель управления</h3>
<table><tbody>
<tr><th>Единицы</th><td>Рубли или тысячи рублей — только отображение, расчёт не меняется.</td></tr>
<tr><th>Сценарий</th><td>Факт БУХ, Факт НУ, План (+8%), Прогноз (+12%). План и прогноз считаются от факта БУХ.</td></tr>
<tr><th>План</th><td>Чекбокс «Показать план» — колонка плана в таблице.</td></tr>
</tbody></table>

<h3>Дерево статей (куда смотреть)</h3>
<table><tbody>
<tr><th>Выручка</th><td>Направление → Группа → Проект → Договор</td></tr>
<tr><th>Себестоимость</th><td>Подстатья затрат → Направление → Группа → Проект</td></tr>
<tr><th>Коммерческие / управленческие</th><td>Льготные / Нельготные → Договор</td></tr>
<tr><th>Прочие доходы / расходы</th><td>Льготные / Нельготные → Статья → Договор</td></tr>
<tr><th>Операционная прибыль, налоги, чистая</th><td>Считаются автоматически из строк выше</td></tr>
</tbody></table>
</section>

<section id="test"><h2>5. Тест BI и проверка данных</h2>
<p>Страница для отладки и сверки с Power Query:</p>
<p class="url">http://localhost:18001/dashboard/almabi-test</p>
<div class="grid2">
<div class="card"><h4>Обычный дашборд</h4><p>Рабочий P&amp;L для просмотра. Аналитика из cost или реализации — что нашлось.</p></div>
<div class="card"><h4>Тест BI</h4><p>Строже PQ: конфликт аналитики = пусто. Пишет аудит в <code>logs/almabi_test/audit-latest.json</code>.</p></div>
</div>
<p class="note">После загрузки на Тест BI можно сгенерировать HTML-отчёты (см. ниже).</p>
</section>

<section id="reports"><h2>6. Отчёты в папке «Загрузки»</h2>
<p>Запускать из папки проекта (после прогона Тест BI с актуальными файлами):</p>
<div class="cmd">python scripts/generate_almabi_instruction_html.py
python scripts/generate_pipeline_logic_html.py
python scripts/generate_audit_report_html.py
python scripts/generate_duplicates_report_html.py</div>
<table><tbody>
<tr><th>almabi_instruction.html</th><td>Эта инструкция</td></tr>
<tr><th>almabi_pipeline_logic.html</th><td>Как файлы и колонки собираются в статьи</td></tr>
<tr><th>almabi_audit_report.html</th><td>Полный аудит: выручка, себестоимость, дубли, пересечения</td></tr>
<tr><th>almabi_duplicates_report.html</th><td>Одинаковые строки в BI и пути в дереве</td></tr>
</tbody></table>
</section>

<section id="amounts"><h2>7. Суммы и округление</h2>
<p class="note note-ok"><strong>Внутри системы</strong> все суммы считаются без округления (полная точность float).</p>
<p><strong>На экране</strong> показываются <strong>2 знака после запятой</strong> (только отображение). При переключении «тысячи» делится уже отображаемая шкала.</p>
</section>

<section id="accounts"><h2>8. Счета → статьи (бухрегистр)</h2>
<table><tbody>
<tr><th>Выручка</th><td>Кт <code>90.01.3</code></td></tr>
<tr><th>Себестоимость</th><td>Дт <code>90.02.1</code></td></tr>
<tr><th>Коммерческие расходы</th><td>Дт <code>90.07.1</code></td></tr>
<tr><th>Управленческие расходы</th><td>Дт <code>90.08.1</code></td></tr>
<tr><th>Прочие доходы</th><td>Кт <code>91.01</code></td></tr>
<tr><th>Прочие расходы</th><td>Дт <code>91.02</code></td></tr>
</tbody></table>
<p>Подробная логика связей между файлами — в <code>almabi_pipeline_logic.html</code>.</p>
</section>

<section id="issues"><h2>9. Частые вопросы</h2>
<table><tbody>
<tr><th>«Без направления» у себестоимости</th><td>Нет join с реализацией/cost: проверьте документ и номенклатуру; в cost могут отсутствовать колонки направления.</td></tr>
<tr><th>Выручка без проекта</th><td>Загрузите реализацию; документ в бухе должен совпадать с реализацией по номеру.</td></tr>
<tr><th>Дубли в прочих доходах/расходах</th><td>Смотрите <code>almabi_duplicates_report.html</code> — там пути в дереве BI.</td></tr>
<tr><th>Амортизация не видна</th><td>Файл принимается, но в P&amp;L ещё не подключён.</td></tr>
<tr><th>Обновить после новых выгрузок</th><td>Загрузите файлы заново через шестерёнку; для аудита — прогон на Тест BI и перегенерация HTML.</td></tr>
</tbody></table>
</section>

<footer>AlMaBi · инструкция пользователя · {ts}</footer>
</div></body></html>"""


def main() -> Path:
    import argparse

    parser = argparse.ArgumentParser(description="Generate AlMaBi user instruction HTML")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_build_html(), encoding="utf-8")
    print(f"Instruction: {args.output}")
    return args.output


if __name__ == "__main__":
    main()
