const TAX_PRIVILEGED = "Льготные проекты";
const TAX_NON_PRIVILEGED = "Нельготные проекты";
const TAX_FILTER_MAP = {
  privileged: TAX_PRIVILEGED,
  non_privileged: TAX_NON_PRIVILEGED,
};

const MONTHS_RU = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

const moneyFormatter = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const REPORT_CONFIGS = {
  revenue: {
    analyticsFields: ["Направление", "Группа проектов", "Проект", "Документ"],
    monthFields: ["Месяц", "Направление", "Группа проектов", "Проект", "Документ"],
    taxColumn: "Льгота",
    amountColumn: "Сумма БУ",
    hasTreeByTax: true,
  },
  cost: {
    analyticsFields: ["Направление", "Группа проектов", "Проект", "Документ"],
    monthFields: ["Месяц", "Направление", "Группа проектов", "Проект", "Документ"],
    taxColumn: "Льгота",
    amountColumn: "Сумма БУ",
    hasTreeByTax: true,
  },
  "other-income": {
    analyticsFields: ["Статья", "Документ"],
    monthFields: ["Месяц", "Статья", "Документ"],
    taxColumn: "Льгота",
    amountColumn: "Сумма БУ",
    hasTreeByTax: true,
  },
  "other-expense": {
    analyticsFields: ["Статья", "Документ"],
    monthFields: ["Месяц", "Статья", "Документ"],
    taxColumn: "Льгота",
    amountColumn: "Сумма БУ",
    hasTreeByTax: true,
  },
  "commercial-expense": {
    analyticsFields: ["Статья", "Документ"],
    monthFields: ["Месяц", "Статья", "Документ"],
    taxColumn: "Льгота",
    amountColumn: "Сумма БУ",
    hasTreeByTax: true,
  },
  "management-expense": {
    analyticsFields: ["Статья", "Документ"],
    monthFields: ["Месяц", "Статья", "Документ"],
    taxColumn: "Льгота",
    amountColumn: "Сумма БУ",
    hasTreeByTax: true,
  },
  "operating-profit": {
    analyticsFields: ["Компонент"],
    monthFields: ["Месяц", "Компонент"],
    taxColumn: "Льгота",
    amountColumn: "Сумма БУ",
    hasTreeByTax: false,
  },
  "profit-before-tax": {
    analyticsFields: ["Компонент"],
    monthFields: ["Месяц", "Компонент"],
    taxColumn: "Льгота",
    amountColumn: "Сумма БУ",
    hasTreeByTax: false,
  },
  "net-profit": {
    analyticsFields: ["Компонент"],
    monthFields: ["Месяц", "Компонент"],
    taxColumn: "Льгота",
    amountColumn: "Сумма БУ",
    hasTreeByTax: false,
  },
  taxes: {
    analyticsFields: ["Льгота"],
    monthFields: ["Месяц", "Льгота"],
    taxColumn: "Льгота",
    amountColumn: "Налог",
    hasTreeByTax: false,
    detailRowsKey: "source_rows",
    moneyColumns: ["Сумма НУ"],
  },
};

function formatMoney(value) {
  return moneyFormatter.format(Number(value) || 0);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function getReportSlug(root) {
  const attr = [...root.attributes].find(
    (item) => item.name.startsWith("data-") && item.name.endsWith("-report-root"),
  );
  if (!attr) return null;
  return attr.name.slice(5, -"-report-root".length);
}

function qs(slug, suffix, scope = document) {
  return scope.querySelector(`[data-${slug}-${suffix}]`);
}

function qsa(slug, suffix, scope = document) {
  return [...scope.querySelectorAll(`[data-${slug}-${suffix}]`)];
}

function readJsonScript(slug, suffix) {
  const node = qs(slug, suffix);
  if (!node?.textContent?.trim()) return null;
  try {
    return JSON.parse(node.textContent);
  } catch {
    return null;
  }
}

function filterRowsByTax(rows, taxFilter, taxColumn) {
  if (!taxColumn || taxFilter === "all") return rows;
  const bucket = TAX_FILTER_MAP[taxFilter];
  return rows.filter((row) => row[taxColumn] === bucket);
}

function sortKeys(field, keys) {
  const unique = [...keys];
  if (field === "Месяц") {
    const order = Object.fromEntries(MONTHS_RU.map((name, index) => [name, index]));
    return unique.sort((left, right) => (order[left] ?? 99) - (order[right] ?? 99) || left.localeCompare(right, "ru"));
  }
  if (field === "Льгота") {
    const order = { [TAX_PRIVILEGED]: 0, [TAX_NON_PRIVILEGED]: 1 };
    return unique.sort((left, right) => (order[left] ?? 2) - (order[right] ?? 2) || left.localeCompare(right, "ru"));
  }
  return unique.sort((left, right) => left.localeCompare(right, "ru"));
}

function buildHierarchy(rows, fieldNames, amountColumn) {
  if (!rows.length || !fieldNames.length) return [];

  const field = fieldNames[0];
  const grouped = new Map();
  rows.forEach((row) => {
    const key = String(row[field] ?? "—");
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(row);
  });

  return sortKeys(field, grouped.keys()).map((name) => {
    const childRows = grouped.get(name);
    const amount = childRows.reduce((sum, row) => sum + Number(row[amountColumn] || 0), 0);
    const children = fieldNames.length > 1
      ? buildHierarchy(childRows, fieldNames.slice(1), amountColumn)
      : [];
    return {
      name,
      amount,
      row_count: childRows.length,
      children,
    };
  });
}

function buildMonthTable(rows, amountColumn, taxColumn) {
  const byMonth = new Map();
  rows.forEach((row) => {
    const month = String(row["Месяц"] ?? "Без месяца");
    const bucket = String(row[taxColumn] ?? TAX_NON_PRIVILEGED);
    const totals = byMonth.get(month) || { privileged: 0, non_privileged: 0 };
    if (bucket === TAX_PRIVILEGED) totals.privileged += Number(row[amountColumn] || 0);
    else totals.non_privileged += Number(row[amountColumn] || 0);
    byMonth.set(month, totals);
  });

  return sortKeys("Месяц", byMonth.keys()).map((month) => {
    const totals = byMonth.get(month);
    return {
      month,
      privileged: totals.privileged,
      non_privileged: totals.non_privileged,
      total: totals.privileged + totals.non_privileged,
    };
  });
}

function getActiveTree(payload, config, state) {
  const rows = payload.rows || [];
  const { treeMode, taxFilter } = state;

  if (treeMode === "analytics") {
    if (config.hasTreeByTax && taxFilter !== "all" && payload.tree_by_tax?.length) {
      const bucket = TAX_FILTER_MAP[taxFilter];
      const node = payload.tree_by_tax.find((item) => item.name === bucket);
      return node?.children || [];
    }
    if (taxFilter !== "all") {
      const filtered = filterRowsByTax(rows, taxFilter, config.taxColumn);
      return buildHierarchy(filtered, config.analyticsFields, config.amountColumn);
    }
    return payload.tree || [];
  }

  if (taxFilter !== "all") {
    const filtered = filterRowsByTax(rows, taxFilter, config.taxColumn);
    return buildHierarchy(filtered, config.monthFields, config.amountColumn);
  }
  return payload.tree_by_month || [];
}

function collectTreePaths(nodes, prefix = "root", bucket = []) {
  nodes.forEach((node) => {
    const path = `${prefix}/${node.name}`;
    if (node.children?.length) {
      bucket.push(path);
      collectTreePaths(node.children, path, bucket);
    }
  });
  return bucket;
}

function setToggleGroup(slug, suffix, activeValue) {
  qsa(slug, suffix).forEach((button) => {
    const value = button.getAttribute(`data-${slug}-${suffix}`);
    const active = value === activeValue;
    button.classList.toggle("bg-brand-50", active);
    button.classList.toggle("text-brand-700", active);
    button.classList.toggle("text-gray-600", !active);
    button.classList.toggle("hover:bg-gray-50", !active);
  });
}

function renderMonthTable(slug, rows, amountColumn, taxColumn) {
  const tbody = qs(slug, "report-month-table");
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="px-4 py-6 text-center text-gray-500">Нет данных</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((row) => `
    <tr class="border-t border-gray-100">
      <td class="px-3 py-2 font-medium">${escapeHtml(row.month)}</td>
      <td class="px-3 py-2 text-right tabular-nums text-emerald-700">${formatMoney(row.privileged)}</td>
      <td class="px-3 py-2 text-right tabular-nums text-rose-700">${formatMoney(row.non_privileged)}</td>
      <td class="px-3 py-2 text-right font-semibold tabular-nums">${formatMoney(row.total)}</td>
    </tr>
  `).join("");
}

function renderDetailTable(slug, rows, columns, config, searchQuery) {
  const tbody = qs(slug, "report-body");
  if (!tbody) return;

  const query = searchQuery.trim().toLowerCase();
  const filtered = query
    ? rows.filter((row) => columns.some((column) => String(row[column] ?? "").toLowerCase().includes(query)))
    : rows;

  const moneyColumns = new Set([
    config.amountColumn,
    ...(config.moneyColumns || []),
    "Сумма БУ",
    "Сумма НУ",
    "Налог",
  ]);

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="${columns.length}" class="px-4 py-10 text-center text-gray-500">Нет данных</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map((row) => {
    const cells = columns.map((column) => {
      const raw = row[column];
      let className = "px-3 py-2 whitespace-nowrap";
      if (moneyColumns.has(column)) className += " text-right font-medium tabular-nums";
      if (column === "Льгота" && raw === TAX_PRIVILEGED) className += " text-emerald-700";
      if (column === "Льгота" && raw && raw !== TAX_PRIVILEGED) className += " text-rose-700";
      const value = moneyColumns.has(column) ? formatMoney(raw) : escapeHtml(raw);
      return `<td class="${className}">${value}</td>`;
    }).join("");
    return `<tr class="border-t border-gray-100 hover:bg-brand-50/40" data-${slug}-report-row>${cells}</tr>`;
  }).join("");
}

function renderTree(slug, nodes, expandedIds) {
  const tbody = qs(slug, "report-tree");
  if (!tbody) return;

  if (!nodes.length) {
    tbody.innerHTML = '<tr><td colspan="3" class="px-4 py-10 text-center text-gray-500">Нет данных для структуры</td></tr>';
    return;
  }

  const parts = [];
  const walk = (items, depth, prefix) => {
    items.forEach((node) => {
      const path = `${prefix}/${node.name}`;
      const hasChildren = Boolean(node.children?.length);
      const expanded = !hasChildren || expandedIds.has(path);
      parts.push(`
        <tr class="border-t border-gray-100 hover:bg-gray-50">
          <td class="px-3 py-2">
            <div class="flex items-center gap-1" style="padding-left:${depth * 16}px">
              ${hasChildren
                ? `<button type="button" class="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-gray-500 hover:bg-gray-100" data-tree-toggle="${escapeHtml(path)}" aria-label="Развернуть или свернуть">${expanded ? "▾" : "▸"}</button>`
                : '<span class="inline-block h-5 w-5 shrink-0"></span>'}
              <span class="font-medium text-gray-800">${escapeHtml(node.name)}</span>
            </div>
          </td>
          <td class="px-3 py-2 text-right tabular-nums text-gray-600">${node.row_count ?? 0}</td>
          <td class="px-3 py-2 text-right font-medium tabular-nums">${formatMoney(node.amount)}</td>
        </tr>
      `);
      if (hasChildren && expanded) walk(node.children, depth + 1, path);
    });
  };
  walk(nodes, 0, "root");
  tbody.innerHTML = parts.join("");
}

function initReportPage(root) {
  const slug = getReportSlug(root);
  const config = REPORT_CONFIGS[slug];
  if (!config) return;

  const uploadUrl = root.dataset.uploadUrl;
  const dataUrl = uploadUrl ? uploadUrl.replace(/\/upload$/, "/data") : null;

  const state = {
    treeMode: "analytics",
    taxFilter: "all",
    searchQuery: "",
    expandedIds: new Set(),
    payload: null,
  };

  const detailColumns = readJsonScript(slug, "report-source-columns-json")
    || readJsonScript(slug, "report-columns-json")
    || [];

  const render = () => {
    const payload = state.payload;
    if (!payload) return;

    const treeRows = payload.rows || [];
    const detailRows = payload[config.detailRowsKey || "rows"] || treeRows;
    const filteredDetailRows = filterRowsByTax(detailRows, state.taxFilter, config.taxColumn);
    const filteredTreeRows = filterRowsByTax(treeRows, state.taxFilter, config.taxColumn);
    const monthSourceRows = config.detailRowsKey ? treeRows : filteredTreeRows;
    const monthRows = filterRowsByTax(monthSourceRows, state.taxFilter, config.taxColumn);

    renderTree(slug, getActiveTree(payload, config, state), state.expandedIds);
    renderMonthTable(slug, buildMonthTable(monthRows, config.amountColumn, config.taxColumn), config.amountColumn, config.taxColumn);
    renderDetailTable(slug, filteredDetailRows, detailColumns, config, state.searchQuery);

    setToggleGroup(slug, "tree-mode", state.treeMode);
    setToggleGroup(slug, "tax-filter", state.taxFilter);
  };

  const loadPayload = async () => {
    if (dataUrl) {
      try {
        const response = await fetch(dataUrl, { headers: { Accept: "application/json" } });
        if (response.ok) {
          state.payload = await response.json();
          const tree = getActiveTree(state.payload, config, state);
          state.expandedIds = new Set(collectTreePaths(tree));
          render();
          return;
        }
      } catch {
        /* fallback below */
      }
    }

    state.payload = {
      rows: readJsonScript(slug, "report-rows-json") || [],
      source_rows: readJsonScript(slug, "report-source-rows-json") || [],
      tree: buildHierarchy(readJsonScript(slug, "report-rows-json") || [], config.analyticsFields, config.amountColumn),
      tree_by_month: buildHierarchy(readJsonScript(slug, "report-rows-json") || [], config.monthFields, config.amountColumn),
      tree_by_tax: [],
      month_table: [],
    };
    const tree = getActiveTree(state.payload, config, state);
    state.expandedIds = new Set(collectTreePaths(tree));
    render();
  };

  qsa(slug, "tree-mode").forEach((button) => {
    button.addEventListener("click", () => {
      state.treeMode = button.getAttribute(`data-${slug}-tree-mode`) || "analytics";
      render();
    });
  });

  qsa(slug, "tax-filter").forEach((button) => {
    button.addEventListener("click", () => {
      state.taxFilter = button.getAttribute(`data-${slug}-tax-filter`) || "all";
      render();
    });
  });

  qs(slug, "tree-expand-all")?.addEventListener("click", () => {
    if (!state.payload) return;
    state.expandedIds = new Set(collectTreePaths(getActiveTree(state.payload, config, state)));
    render();
  });

  qs(slug, "tree-collapse-all")?.addEventListener("click", () => {
    state.expandedIds = new Set();
    render();
  });

  qs(slug, "report-tree")?.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-tree-toggle]");
    if (!toggle) return;
    const path = toggle.getAttribute("data-tree-toggle");
    if (state.expandedIds.has(path)) state.expandedIds.delete(path);
    else state.expandedIds.add(path);
    render();
  });

  qs(slug, "report-search")?.addEventListener("input", (event) => {
    state.searchQuery = event.target.value || "";
    render();
  });

  qs(slug, "report-upload")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!uploadUrl) return;
    const form = event.currentTarget;
    const button = form.querySelector('button[type="submit"]');
    const status = qs(slug, "report-status");
    button.disabled = true;
    if (status) status.textContent = "Загрузка и сборка отчёта…";
    try {
      const response = await fetch(uploadUrl, { method: "POST", body: new FormData(form) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Ошибка загрузки");
      window.location.reload();
    } catch (error) {
      if (status) status.textContent = error.message || "Не удалось загрузить файлы";
      button.disabled = false;
    }
  });

  loadPayload();
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-upload-url]").forEach((root) => {
    if (getReportSlug(root)) initReportPage(root);
  });
});
