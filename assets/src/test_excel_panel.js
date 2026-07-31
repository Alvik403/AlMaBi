function parseRows(root) {
  const script = root.querySelector("[data-test-excel-rows]");
  if (!script?.textContent) return [];
  try {
    return JSON.parse(script.textContent);
  } catch {
    return [];
  }
}

function parseColumns(root) {
  const script = root.querySelector("[data-test-excel-columns]");
  if (!script?.textContent) return [];
  try {
    return JSON.parse(script.textContent);
  } catch {
    return [];
  }
}

const amountColumns = ["Сумма", "Сумма БУ", "Сумма НУ", "Себестоимость.Сумма"];

function numeric(value) {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatMoney(value) {
  return new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(numeric(value));
}

function rowAmount(row, columns) {
  const column = amountColumns.find((name) => columns.includes(name));
  return column ? numeric(row[column]) : 0;
}

function rowMatches(row, columns, query, filters) {
  if (query) {
    const haystack = columns.map((column) => String(row[column] || "")).join(" ").toLocaleLowerCase("ru-RU");
    if (!haystack.includes(query)) return false;
  }
  return Object.entries(filters).every(([column, value]) => !value || String(row[column] || "") === value);
}

function initPanel(root) {
  const rows = parseRows(root);
  const columns = parseColumns(root);
  const tbody = root.querySelector("[data-test-excel-body]");
  const search = root.querySelector("[data-test-excel-search]");
  const filters = Array.from(root.querySelectorAll("[data-test-excel-filter]"));
  const selectAll = root.querySelector("[data-test-excel-select-all]");
  const selectedTotal = root.querySelector("[data-test-excel-selected-total]");
  const selectedCount = root.querySelector("[data-test-excel-selected-count]");
  const rowCount = root.querySelector("[data-test-excel-row-count]");
  const clearFilters = root.querySelector("[data-test-excel-clear-filters]");
  const selectVisible = root.querySelector("[data-test-excel-select-visible]");
  const clearSelection = root.querySelector("[data-test-excel-clear-selection]");
  const form = root.querySelector("[data-test-excel-upload]");
  const status = root.querySelector("[data-test-excel-status]");

  const selected = new Set();

  const activeRows = () => {
    const query = String(search?.value || "").trim().toLocaleLowerCase("ru-RU");
    const filterValues = Object.fromEntries(
      filters.map((filter) => [filter.dataset.testExcelFilter, filter.value]),
    );
    return rows
      .map((row, index) => ({ row, index }))
      .filter(({ row }) => rowMatches(row, columns, query, filterValues));
  };

  const updateSelectedSummary = () => {
    const total = Array.from(selected).reduce((sum, index) => sum + rowAmount(rows[index], columns), 0);
    if (selectedTotal) selectedTotal.textContent = formatMoney(total);
    if (selectedCount) selectedCount.textContent = `Выделено: ${selected.size}`;
  };

  const render = () => {
    if (!tbody) return;
    const visibleRows = activeRows();
    if (rowCount) rowCount.textContent = String(visibleRows.length);
    if (selectAll) {
      selectAll.checked = visibleRows.length > 0 && visibleRows.every(({ index }) => selected.has(index));
      selectAll.indeterminate = visibleRows.some(({ index }) => selected.has(index)) && !selectAll.checked;
    }
    if (!visibleRows.length) {
      tbody.innerHTML = `
        <tr>
          <td colspan="${columns.length + 1}" class="px-4 py-10 text-center text-gray-500">
            Нет строк по выбранным фильтрам.
          </td>
        </tr>`;
      updateSelectedSummary();
      return;
    }
    tbody.innerHTML = visibleRows
      .map(({ row, index }) => `
        <tr class="border-t border-gray-100 hover:bg-brand-50/40" data-test-excel-row data-row-index="${index}">
          <td class="px-3 py-2">
            <input type="checkbox" data-test-excel-row-check aria-label="Выделить строку" ${selected.has(index) ? "checked" : ""} />
          </td>
          ${columns
            .map((column) => {
              const value = amountColumns.includes(column) ? formatMoney(row[column]) : String(row[column] ?? "");
              const classes = amountColumns.includes(column) ? "text-right font-medium tabular-nums" : "";
              return `<td class="px-3 py-2 whitespace-nowrap ${classes}">${value}</td>`;
            })
            .join("")}
        </tr>`)
      .join("");
    updateSelectedSummary();
  };

  search?.addEventListener("input", render);
  filters.forEach((filter) => filter.addEventListener("change", render));
  clearFilters?.addEventListener("click", () => {
    if (search) search.value = "";
    filters.forEach((filter) => {
      filter.value = "";
    });
    render();
  });
  clearSelection?.addEventListener("click", () => {
    selected.clear();
    render();
  });
  selectVisible?.addEventListener("click", () => {
    activeRows().forEach(({ index }) => selected.add(index));
    render();
  });
  selectAll?.addEventListener("change", () => {
    const visibleRows = activeRows();
    if (selectAll.checked) {
      visibleRows.forEach(({ index }) => selected.add(index));
    } else {
      visibleRows.forEach(({ index }) => selected.delete(index));
    }
    render();
  });
  tbody?.addEventListener("change", (event) => {
    const checkbox = event.target.closest("[data-test-excel-row-check]");
    if (!checkbox) return;
    const index = Number(checkbox.closest("[data-test-excel-row]")?.dataset.rowIndex);
    if (!Number.isInteger(index)) return;
    if (checkbox.checked) selected.add(index);
    else selected.delete(index);
    updateSelectedSummary();
  });

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type='submit']");
    const formData = new FormData(form);
    if (button) button.disabled = true;
    if (status) {
      status.textContent = "Загружаем и строим таблицу...";
      status.className = "mt-2 text-xs text-brand-700";
    }
    try {
      const response = await fetch(root.dataset.uploadUrl, { method: "POST", body: formData });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Не удалось загрузить файл");
      window.location.reload();
    } catch (error) {
      if (status) {
        status.textContent = error.message;
        status.className = "mt-2 text-xs text-red-600";
      }
      if (button) button.disabled = false;
    }
  });

  render();
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-test-excel-root]").forEach(initPanel);
});
