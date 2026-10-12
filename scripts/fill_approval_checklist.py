"""Fill the original network-approval template into a new Word file.

Does not modify the template or previously generated checklists.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches

TEMPLATE = Path(
    r"C:\Users\Flirp\Downloads\Чек-лист для согласования сетевой инфраструктуры проекта.docx"
)
OUT = Path(
    r"C:\Users\Flirp\Downloads\Чек-лист для согласования сетевой инфраструктуры проекта AlMaBi.docx"
)
ROOT = Path(__file__).resolve().parents[1]
IMG_NETWORK = ROOT / "docs" / "network_checklist" / "network_33.png"
IMG_DATAFLOW = ROOT / "docs" / "network_checklist" / "dataflow_35.png"

NETWORK_ROWS = [
    ("Наименование", "№ связи", "SRC", "DST", "Protocol", "Port", "Примечание"),
    (
        "Пользователь",
        "1",
        "IP АРМ или VPN — уточняет ИТ",
        "nginx, almabi.alabuga.ru",
        "TCP",
        "443",
        "HTTPS. Страницы приложения, /login и /login/callback",
    ),
    (
        "Администратор системы",
        "1",
        "IP АРМ — уточняет ИТ",
        "nginx, almabi.alabuga.ru",
        "TCP",
        "443",
        "Тот же HTTPS, что у пользователя. Роль admin в приложении, не доступ к серверу",
    ),
    (
        "Мониторинг",
        "4",
        "IP мониторинга — уточняет ИТ",
        "nginx, almabi.alabuga.ru",
        "TCP",
        "443",
        "GET /health и /ready",
    ),
    (
        "Администратор сервера через PAM",
        "3",
        "Система PAM",
        "хост ВМ almabi.alabuga.ru",
        "TCP",
        "22",
        "SSH на хост. В nginx этот доступ не приходит",
    ),
    (
        "nginx",
        "2",
        "контейнер nginx",
        "web:8000",
        "TCP",
        "8000",
        "Только внутренняя сеть Docker",
    ),
    (
        "Браузер, пароль",
        "2a",
        "АРМ пользователя или администратора системы",
        "Keycloak 26.5.7",
        "TCP",
        "8088",
        "Браузер открывает Keycloak сам. nginx туда не проксирует",
    ),
    (
        "web, код и ключи",
        "2c",
        "контейнер web",
        "keycloak:8080",
        "TCP",
        "8080",
        "Внутренний обмен кода и ключей. Роль берётся из группы токена",
    ),
    (
        "Keycloak, учётная запись и второй фактор",
        "2b",
        "Keycloak 26.5.7",
        "Active Directory и второй фактор вне ВМ",
        "TCP",
        "по схеме ИБ",
        "AlMaBi к AD и второму фактору не подключается",
    ),
    (
        "web",
        "5",
        "контейнер web",
        "Postgres :5432",
        "TCP",
        "5432",
        "Только учётки и сессии. Наружу не публикуется",
    ),
    (
        "Журналы",
        "6",
        "хост ВМ almabi.alabuga.ru",
        "srv-s.alabuga.ru (10.50.53.121)",
        "TCP",
        "1514, 1515",
        "Связь SIEM с сервером. Приложение web в SIEM не ходит",
    ),
]

ACCESS_ROWS = [
    ("Роль", "Дашборд и отчёты", "Загрузка Excel", "Учётные записи"),
    ("Роль", "Дашборд и отчёты", "Загрузка Excel", "Учётные записи"),
    ("admin", "чтение и запись", "запись", "управление"),
    ("uploader", "чтение", "запись", "нет"),
    ("viewer", "чтение", "нет", "нет"),
]


def _is_red(run) -> bool:
    props = run._element.find(qn("w:rPr"))
    if props is None:
        return False
    color = props.find(qn("w:color"))
    return color is not None and color.get(qn("w:val")) == "FF0000"


def strip_red(doc: Document) -> None:
    for paragraph in doc.paragraphs:
        for run in list(paragraph.runs):
            if _is_red(run):
                run._element.getparent().remove(run._element)


def replace_underscores(paragraph, answer: str) -> None:
    for run in paragraph.runs:
        if "_" in run.text:
            run.text = re.sub(r"_+", answer, run.text, count=1)
            return
    if paragraph.runs:
        paragraph.runs[-1].text = paragraph.runs[-1].text.rstrip() + answer
    else:
        paragraph.add_run(answer)


def set_paragraph(paragraph, text: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)


def set_cell(cell, text: str) -> None:
    paragraph = cell.paragraphs[0]
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)
    for extra in cell.paragraphs[1:]:
        for run in extra.runs:
            run.text = ""


def write_table(table, rows: list[tuple[str, ...]]) -> None:
    while len(table.rows) > 1:
        table._tbl.remove(table.rows[-1]._tr)
    for cell, value in zip(table.rows[0].cells, rows[0]):
        set_cell(cell, value)
    for row_data in rows[1:]:
        cells = table.add_row().cells
        for cell, value in zip(cells, row_data):
            set_cell(cell, value)


def replace_picture(paragraph, image_path: Path) -> None:
    element = paragraph._element
    for child in list(element):
        if child.tag.endswith("r"):
            element.remove(child)
    paragraph.add_run().add_picture(str(image_path), width=Inches(6.3))


def insert_picture_after(paragraph, image_path: Path):
    new_xml = paragraph._element.makeelement(qn("w:p"), {})
    paragraph._element.addnext(new_xml)
    from docx.text.paragraph import Paragraph

    new_paragraph = Paragraph(new_xml, paragraph._parent)
    new_paragraph.add_run().add_picture(str(image_path), width=Inches(6.3))


def delete_paragraph(paragraph) -> None:
    element = paragraph._element
    element.getparent().remove(element)


def main() -> None:
    if not TEMPLATE.is_file():
        raise FileNotFoundError(TEMPLATE)
    if not IMG_NETWORK.is_file() or not IMG_DATAFLOW.is_file():
        raise FileNotFoundError("diagram png is missing")
    shutil.copy2(TEMPLATE, OUT)
    doc = Document(str(OUT))
    strip_red(doc)
    paragraphs = doc.paragraphs

    replace_underscores(
        paragraphs[7],
        "внутренний веб-дашборд Al Ma BI для P&L по Excel-выгрузкам 1С "
        "(бухрегистр, реализация, себестоимость; опционально план и прогноз)",
    )
    replace_underscores(paragraphs[9], "30.09.2026")
    replace_underscores(
        paragraphs[10],
        "Попов Алексей Викторович, +79934058605, Alepopov@alabuga.ru",
    )
    replace_underscores(paragraphs[11], "")
    replace_underscores(paragraphs[14], " — целевой вариант; площадку согласует ИТ")
    replace_underscores(paragraphs[15], "не требуется")
    replace_underscores(paragraphs[16], "не планируется")
    replace_underscores(paragraphs[17], "только браузер, серверные компоненты не размещаются")
    replace_underscores(paragraphs[18], "не размещается")
    replace_underscores(
        paragraphs[20],
        "имя almabi.alabuga.ru; hostname и IP хоста задаёт ИТ",
    )
    replace_underscores(
        paragraphs[21],
        "только если нет подходящего хоста: 1 ВМ, Linux, Docker Engine и Compose v2",
    )
    replace_underscores(
        paragraphs[22],
        "Docker Compose: nginx :443, web :8000, Postgres :5432 (учётки и сессии), Keycloak 26.5.7",
    )
    replace_underscores(paragraphs[26], "отдельная VLAN/VRF для AlMaBi не требуется")
    replace_underscores(
        paragraphs[28],
        " корпоративное DNS-имя; FQDN задаётся в ALMABI_HOST и в SAN сертификата",
    )
    replace_underscores(paragraphs[32], " — нет; только сотрудники с личной учётной записью")
    replace_underscores(paragraphs[33], "перечень подразделений даёт владелец системы")
    replace_underscores(
        paragraphs[34],
        "AlMaBi-Admins (два администратора системы), AlMaBi-Uploaders, AlMaBi-Viewers",
    )
    replace_underscores(paragraphs[35], "мониторинг опрашивает /health и /ready через nginx :443")
    replace_underscores(paragraphs[37], " — нет")
    replace_underscores(paragraphs[38], " — да, если доступ нужен вне корпоративной LAN")
    replace_underscores(paragraphs[39], "нет")
    replace_underscores(paragraphs[40], "нет")
    replace_picture(paragraphs[47], IMG_NETWORK)
    replace_underscores(
        paragraphs[63],
        "Excel .xlsx, выгрузки 1С; загружает uploader или администратор системы",
    )
    replace_underscores(
        paragraphs[64],
        "веб-дашборд AlMaBi: P&L, drill-down и отчёты в браузере",
    )
    replace_underscores(
        paragraphs[65],
        "проверка XLSX, разбор openpyxl, расчёт P&L в памяти. "
        "Учётки и сессии хранит отдельный Postgres, расчёты в базу не пишутся",
    )
    replace_underscores(
        paragraphs[66],
        "браузер → HTTPS :443 → nginx → web :8000 → зашифрованные uploads → расчёт в памяти → HTML. "
        "Пароль браузер вводит на Keycloak. Сессия пишется в Postgres :5432. Журналы идут с хоста в SIEM",
    )
    insert_picture_after(paragraphs[66], IMG_DATAFLOW)
    replace_underscores(
        paragraphs[67],
        "Попов Алексей Викторович — контакт по приложению; "
        "ИТ назначает администратора хоста, Docker, TLS и резервных копий",
    )
    set_paragraph(
        paragraphs[70],
        "Да — вход: /login по HTTPS :443 через nginx, затем браузер сам открывает Keycloak 26.5.7 и вводит пароль. "
        "web забирает код и ключи и назначает роль по группе токена: "
        "AlMaBi-Admins — admin, AlMaBi-Uploaders — uploader, AlMaBi-Viewers — viewer. "
        "Общий пароль не используется. Active Directory и второй фактор к Keycloak подключает ИБ, вне ВМ",
    )
    replace_underscores(
        paragraphs[79],
        "журналы с хоста ВМ на srv-s.alabuga.ru (10.50.53.121), TCP 1514 и TCP 1515. "
        "Keycloak обращается к Active Directory и второму фактору вне ВМ. Приложение web в SIEM не ходит",
    )
    replace_underscores(
        paragraphs[83],
        "internal CA; файлы ops/tls/fullchain.pem и privkey.pem, SAN равен DNS-имени сайта",
    )
    set_paragraph(
        paragraphs[87],
        "Да — TLS 1.2 и 1.3 между браузером и nginx (связь 1). "
        "nginx → web и web → Postgres идут по HTTP и TCP внутри Docker и наружу не публикуются",
    )
    replace_underscores(
        paragraphs[94],
        "В выгрузках 1С возможны финансовые сведения и персональные данные в свободных полях. "
        "Категории субъектов, цель и основание обработки подтверждают владелец системы и СБ. "
        "Файлы лежат в томе uploads, срок хранения 90 дней",
    )
    replace_underscores(paragraphs[95], "")
    replace_underscores(
        paragraphs[99],
        "внутренний веб-интерфейс и API того же сайта за nginx :443. Отдельный внешний API не публикуется",
    )
    replace_underscores(
        paragraphs[102],
        "Вход через Keycloak 26.5.7, дальше серверная сессия в cookie. "
        "Изменяющие запросы требуют CSRF. Роли viewer, uploader и admin. "
        "Секреты в ответе не приводятся: они лежат в файлах ops/secrets",
    )
    replace_underscores(paragraphs[103], "")
    replace_underscores(
        paragraphs[106],
        "CN/SAN — DNS-имя сайта, выпуск internal CA, установка в nginx. "
        "Срок смотрит /ready, продлевает администратор хоста. Закрытый ключ не прикладывается",
    )
    replace_underscores(paragraphs[107], "")
    replace_underscores(paragraphs[111], "")
    replace_underscores(
        paragraphs[114],
        "Файлы ops/secrets, в боевом запуске это Docker secrets, не переменные .env: "
        "session_secret подписывает cookie, data_key шифрует uploads и журналы, "
        "отдельно пароль Postgres и секрет клиента Keycloak. "
        "Ротация ключей раз в 60 дней скриптами rotate_session_secret.py и rotate_data_key.py. "
        "Простой сессии 15 минут отзывает вход одного человека и ключи не меняет. "
        "Абсолютный срок сессии 8 часов. Пароль сотрудника хранит Keycloak",
    )
    replace_underscores(paragraphs[115], "")
    replace_underscores(
        paragraphs[119],
        "источник — хост ВМ; назначение srv-s.alabuga.ru (10.50.53.121), TCP 1514 и TCP 1515. "
        "На диске журналы шифруются и хранятся 30 дней",
    )
    replace_underscores(
        paragraphs[123],
        "тома uploads, runtime, logs и база Postgres. Периодичность и место задаёт ИТ. "
        "Проверка восстановления — по регламенту эксплуатации",
    )
    replace_underscores(
        paragraphs[126],
        "Простой сессии 15 минут. Ключ сессии и ключ данных ротируются раз в 60 дней и служат разным целям. "
        "Лимит файла 50 МиБ, квота пользователя 500 МиБ. "
        "Проверка входа без AD: docker-compose.test.yml",
    )

    write_table(doc.tables[0], NETWORK_ROWS)
    write_table(doc.tables[1], ACCESS_ROWS)

    for paragraph in list(doc.paragraphs):
        has_drawing = "w:drawing" in paragraph._element.xml
        if not paragraph.text.strip() and not has_drawing:
            delete_paragraph(paragraph)

    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
