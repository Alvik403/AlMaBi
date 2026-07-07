"""Generate AlMaBi checklists: development, tester, end user."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from checklist_excel import build_dev_workbook, build_tester_workbook, build_user_workbook


def main() -> None:
    docs = Path(__file__).resolve().parents[1] / "docs"
    docs.mkdir(parents=True, exist_ok=True)

    files = {
        "AlMaBi_чек-лист_разработка.xlsx": build_dev_workbook(),
        "AlMaBi_чек-лист_тестировщик.xlsx": build_tester_workbook(),
        "AlMaBi_чек-лист_пользователь.xlsx": build_user_workbook(),
    }
    for name, workbook in files.items():
        path = docs / name
        workbook.save(path)
        print(path)


if __name__ == "__main__":
    main()
