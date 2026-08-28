import "./charts_page.css";

const MONTHS_RU = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

const MONTHS_SHORT = [
  "янв.", "фев.", "мар.", "апр.", "май", "июн.",
  "июл.", "авг.", "сен.", "окт.", "ноя.", "дек.",
];

const QUARTERS = {
  Q1: ["Январь", "Февраль", "Март"],
  Q2: ["Апрель", "Май", "Июнь"],
  Q3: ["Июль", "Август", "Сентябрь"],
  Q4: ["Октябрь", "Ноябрь", "Декабрь"],
};

const COLORS = {
  revenue: "#4A90E2",
  gross: "#F5A623",
  expense: "#A291C2",
  profit: "#50C878",
  plan: "#D1D5DB",
  planFill: "rgba(209, 213, 219, 0.35)",
};

const COST_SECTION_SHORT = {
  "Аренда (прямые)": "Аренда",
  "Общепроизводственные затраты": "ОПЗ",
  "Прочие производственные расходы": "Проч. пр-во",
};

const EXPENSE_KPI_NAMES = [
  "Себестоимость",
  "Коммерческие расходы",
  "Управленческие расходы",
  "Прочие расходы",
];

const CHART_REGISTRY = [
  { id: "kpi-cards", label: "KPI-карточки", default: true },
  { id: "revenue-profit-line", label: "Выручка и прибыль", default: true },
  { id: "revenue-plan-fact", label: "Выручка: план vs факт", default: true },
  { id: "expense-structure", label: "Структура расходов", default: true },
  { id: "gross-by-direction", label: "Валовая прибыль", default: true },
  { id: "expenses-monthly", label: "Расходы", default: true },
];

const CONFIG_STORAGE_KEY = "almabi-charts-config-v1";

const moneyFormatter = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

const percentFormatter = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

function readDashboard() {
  const node = document.getElementById("almabiChartsData");
  if (!node?.textContent?.trim()) return null;
  try {
    return JSON.parse(node.textContent);
  } catch {
    return null;
  }
}

function loadChartConfig() {
  try {
    const raw = localStorage.getItem(CONFIG_STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function saveChartConfig(visibleCharts) {
  localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify({ visibleCharts }));
}

function defaultVisibleCharts() {
  return Object.fromEntries(CHART_REGISTRY.map((item) => [item.id, item.default]));
}

const state = {
  taxBucket: "all",
  unitDivisor: 1000,
  compareScenario: "План",
  visibleCharts: defaultVisibleCharts(),
  periodFrom: "",
  periodTo: "",
  periodPicking: false,
  periodHover: "",
  periodViewYear: "",
};

const chartInstances = {};
let donutChart = null;
let dashboardData = null;

function scaled(value) {
  return Number(value || 0) / state.unitDivisor;
}

function formatMoney(value) {
  return moneyFormatter.format(scaled(value));
}

function compactMoney(value) {
  const abs = Math.abs(Number(value || 0));
  if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)} млрд`;
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)} млн`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(0)} тыс`;
  return moneyFormatter.format(scaled(value));
}

function unitLabel() {
  if (state.unitDivisor >= 1_000_000_000) return "млрд.";
  if (state.unitDivisor >= 1_000_000) return "млн.";
  return "тыс.";
}

function activeMonths() {
  return [...(dashboardData?.months || MONTHS_RU)];
}

function monthLabels(months) {
  return months.map((month) => displayPeriod(month) || MONTHS_SHORT[MONTHS_RU.indexOf(month)] || month);
}

function getConsolidated(data) {
  const bucket = state.taxBucket || "all";
  return data?.consolidated_by_tax?.[bucket] || data?.consolidated_by_tax?.all || [];
}

function consolidatedLookup(data) {
  return Object.fromEntries(getConsolidated(data).map((row) => [row.name, row]));
}

function sumScenarioValues(row, scenario, months) {
  const bucket = row?.values?.[scenario] || {};
  return months.reduce((sum, month) => sum + Number(bucket[month] || 0), 0);
}

function getChartsBundle(data) {
  const bucket = state.taxBucket || "all";
  return data?.charts_by_tax?.[bucket] || data?.charts_by_tax?.all || {
    revenue_by_month: data?.revenue_by_month || [],
    cost_by_month: data?.cost_by_month || [],
    cost_structure_by_month: data?.cost_structure_by_month || { sections: [], by_month: [] },
  };
}

function aggregateSeries(series, months) {
  const byPeriod = Object.fromEntries(series.map((item, index) => [
    item.period || months[index],
    Number(item.value || 0),
  ]));
  return {
    labels: monthLabels(months),
    values: months.map((period) => byPeriod[period] || 0),
  };
}

function aggregateCostStructure(structure, months) {
  const sections = structure?.sections || [];
  const rows = structure?.by_month || [];
  const monthSet = new Set(months);
  const filtered = rows.filter((row, index) => monthSet.has(row.period || months[index]));
  const totals = Object.fromEntries(sections.map((name) => [name, 0]));
  filtered.forEach((row) => {
    sections.forEach((name) => {
      totals[name] += Number(row.sections?.[name] || 0);
    });
  });
  return sections.map((name) => ({ name, value: totals[name] || 0 }));
}

function shortCostSectionName(name) {
  return COST_SECTION_SHORT[name] || name;
}

function buildExpenseStructureRows(data) {
  const months = activeMonths();
  const lookup = consolidatedLookup(data);
  const rows = [];

  const costNode = lookup["Себестоимость"];
  const costFactTotal = Math.abs(sumScenarioValues(costNode || {}, "Факт БУ", months));
  const costPlanTotal = Math.abs(sumScenarioValues(costNode || {}, state.compareScenario, months));

  aggregateCostStructure(getChartsBundle(data).cost_structure_by_month || {}, months)
    .filter((row) => row.value > 0)
    .sort((left, right) => right.value - left.value)
    .forEach(({ name, value }) => {
      const fact = value;
      const plan = costFactTotal > 0 && costPlanTotal > 0
        ? costPlanTotal * (fact / costFactTotal)
        : fact * 1.08;
      rows.push({
        name: shortCostSectionName(name),
        fact,
        plan,
        group: "cost",
      });
    });

  ["Коммерческие расходы", "Управленческие расходы", "Прочие расходы"].forEach((kpiName) => {
    const node = lookup[kpiName];
    const fact = Math.abs(sumScenarioValues(node || {}, "Факт БУ", months));
    const plan = Math.abs(sumScenarioValues(node || {}, state.compareScenario, months));
    if (fact <= 0 && plan <= 0) return;
    rows.push({
      name: kpiName,
      fact,
      plan,
      group: "opex",
    });
  });

  return rows
    .sort((left, right) => right.fact - left.fact)
    .slice(0, 10);
}

const structureBarLabels = {
  id: "structureBarLabels",
  afterDatasetsDraw(chart) {
    if (chart.config.type !== "bar" || chart.options.indexAxis !== "y") return;
    const { ctx } = chart;
    const factMeta = chart.getDatasetMeta(1);
    if (!factMeta?.data?.length) return;
    ctx.save();
    ctx.font = "600 10px Inter, system-ui, sans-serif";
    ctx.fillStyle = "#475569";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    factMeta.data.forEach((bar, index) => {
      const raw = Number(chart.data.datasets[1]?.data[index] || 0);
      if (!raw) return;
      const planRaw = Number(chart.data.datasets[0]?.data[index] || 0);
      const label = `${compactMoney(raw * chart.$unitDivisor)} · ${percentFormatter.format(planRaw ? (raw / planRaw) * 100 : 0)}%`;
      ctx.fillText(label, bar.x + 6, bar.y);
    });
    ctx.restore();
  },
};

function buildKpis(data) {
  const lookup = consolidatedLookup(data);
  const months = activeMonths();
  const revenue = lookup["Выручка"];
  const cost = lookup["Себестоимость"];
  const net = lookup["Чистая прибыль"];

  const revenueTotal = revenue ? sumScenarioValues(revenue, "Факт БУ", months) : 0;
  const costTotal = cost ? Math.abs(sumScenarioValues(cost, "Факт БУ", months)) : 0;
  const grossTotal = revenueTotal - costTotal;
  const netTotal = net ? sumScenarioValues(net, "Факт БУ", months) : grossTotal;
  const expenseTotal = ["Себестоимость", "Коммерческие расходы", "Управленческие расходы", "Прочие расходы"]
    .reduce((sum, name) => sum + Math.abs(sumScenarioValues(lookup[name] || {}, "Факт БУ", months)), 0);
  const margin = revenueTotal ? (grossTotal / revenueTotal) * 100 : 0;

  const planRevenue = revenue ? sumScenarioValues(revenue, state.compareScenario, months) : 0;
  const planGross = planRevenue - (cost ? Math.abs(sumScenarioValues(cost, state.compareScenario, months)) : 0);
  const planExpense = ["Себестоимость", "Коммерческие расходы", "Управленческие расходы", "Прочие расходы"]
    .reduce((sum, name) => sum + Math.abs(sumScenarioValues(lookup[name] || {}, state.compareScenario, months)), 0);
  const planNet = net ? sumScenarioValues(net, state.compareScenario, months) : planGross;

  const revenueRatio = planRevenue ? (revenueTotal / planRevenue) * 100 : 0;
  const grossRatio = planGross ? (grossTotal / planGross) * 100 : 0;
  const expenseRatio = planExpense ? (expenseTotal / planExpense) * 100 : 0;
  const netRatio = planNet ? (netTotal / planNet) * 100 : 0;

  const charts = getChartsBundle(data);
  const revenueSeries = aggregateSeries(charts.revenue_by_month || [], months);
  const expenseSeries = aggregateSeries(charts.cost_by_month || [], months);

  return {
    revenueTotal,
    grossTotal,
    margin,
    expenseTotal,
    netTotal,
    revenueRatio,
    grossRatio,
    expenseRatio,
    netRatio,
    revenueSparkline: revenueSeries.values,
    expenseSparkline: expenseSeries.values,
    netSparkline: revenueSeries.values.map((v, i) => v - (expenseSeries.values[i] || 0) * 0.3),
  };
}

function destroyChart(id) {
  if (chartInstances[id]) {
    chartInstances[id].destroy();
    delete chartInstances[id];
  }
}

function baseChartOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: "top",
        align: "end",
        labels: { boxWidth: 10, boxHeight: 10, font: { size: 11 } },
      },
    },
  };
}

function renderKpiCards(data) {
  const root = document.querySelector("[data-charts-kpi-grid]");
  if (!root) return;
  const k = buildKpis(data);

  root.innerHTML = `
    <article class="charts-kpi-card charts-kpi-card--revenue">
      <div class="charts-kpi-card__top">
        <span class="charts-kpi-card__label">Выручка</span>
        <div class="charts-kpi-card__spark-wrap"><canvas class="charts-kpi-card__spark" data-spark="revenue"></canvas></div>
      </div>
      <p class="charts-kpi-card__value">${compactMoney(k.revenueTotal)} <span class="charts-kpi-card__unit">${unitLabel()}</span></p>
      <div class="charts-kpi-card__bar"><span style="width:${Math.min(100, Math.max(4, k.revenueRatio))}%"></span></div>
      <p class="charts-kpi-card__pct">${percentFormatter.format(k.revenueRatio)}%</p>
    </article>

    <article class="charts-kpi-card charts-kpi-card--gross">
      <div class="charts-kpi-card__body--donut">
        <div>
          <span class="charts-kpi-card__label">Вал. прибыль</span>
          <p class="charts-kpi-card__value">${compactMoney(k.grossTotal)} <span class="charts-kpi-card__unit">${unitLabel()}</span></p>
          <div class="charts-kpi-card__bar"><span style="width:${Math.min(100, Math.max(4, k.grossRatio))}%"></span></div>
          <p class="charts-kpi-card__pct">${percentFormatter.format(k.grossRatio)}%</p>
        </div>
        <div class="charts-kpi-card__donut-wrap">
          <canvas id="chartMarginDonut"></canvas>
          <div class="charts-kpi-card__donut-label">
            <span>Рентаб.</span>
            <span class="charts-kpi-card__donut-value">${percentFormatter.format(k.margin)}%</span>
          </div>
        </div>
      </div>
    </article>

    <article class="charts-kpi-card charts-kpi-card--expense">
      <div class="charts-kpi-card__top">
        <span class="charts-kpi-card__label">Расходы</span>
        <div class="charts-kpi-card__spark-wrap"><canvas class="charts-kpi-card__spark" data-spark="expense"></canvas></div>
      </div>
      <p class="charts-kpi-card__value">${compactMoney(k.expenseTotal)} <span class="charts-kpi-card__unit">${unitLabel()}</span></p>
      <div class="charts-kpi-card__bar"><span style="width:${Math.min(100, Math.max(4, k.expenseRatio))}%"></span></div>
      <p class="charts-kpi-card__pct">${percentFormatter.format(k.expenseRatio)}%</p>
    </article>

    <article class="charts-kpi-card charts-kpi-card--profit">
      <div class="charts-kpi-card__top">
        <span class="charts-kpi-card__label">Чист. прибыль</span>
        <div class="charts-kpi-card__spark-wrap"><canvas class="charts-kpi-card__spark" data-spark="net"></canvas></div>
      </div>
      <p class="charts-kpi-card__value">${compactMoney(k.netTotal)} <span class="charts-kpi-card__unit">${unitLabel()}</span></p>
      <div class="charts-kpi-card__bar"><span style="width:${Math.min(100, Math.max(4, k.netRatio))}%"></span></div>
      <p class="charts-kpi-card__pct">${percentFormatter.format(k.netRatio)}%</p>
    </article>
  `;

  const sparks = {
    revenue: { data: k.revenueSparkline, color: COLORS.revenue },
    expense: { data: k.expenseSparkline, color: COLORS.expense },
    net: { data: k.netSparkline, color: COLORS.profit },
  };

  root.querySelectorAll("[data-spark]").forEach((canvas) => {
    const cfg = sparks[canvas.dataset.spark];
    if (!cfg?.data?.length || !window.Chart) return;
    new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels: cfg.data.map((_, i) => i),
        datasets: [{
          data: cfg.data.map((v) => scaled(v)),
          borderColor: cfg.color,
          backgroundColor: `${cfg.color}33`,
          fill: true,
          tension: 0.4,
          pointRadius: 0,
          borderWidth: 1.5,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: { x: { display: false }, y: { display: false } },
      },
    });
  });

  if (donutChart) donutChart.destroy();
  const donutCanvas = document.getElementById("chartMarginDonut");
  if (donutCanvas && window.Chart) {
    donutChart = new Chart(donutCanvas.getContext("2d"), {
      type: "doughnut",
      data: {
        datasets: [{
          data: [Math.max(0, k.margin), Math.max(0, 100 - k.margin)],
          backgroundColor: [COLORS.gross, "#eef0f4"],
          borderWidth: 0,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "72%",
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
      },
    });
  }
}

function renderRevenueProfitChart(data) {
  destroyChart("revenue-profit-line");
  const canvas = document.getElementById("chartRevenueProfit");
  if (!canvas || !window.Chart) return;

  const months = activeMonths();
  const lookup = consolidatedLookup(data);
  const revenue = lookup["Выручка"];
  const cost = lookup["Себестоимость"];
  const net = lookup["Чистая прибыль"];
  const labels = monthLabels(months);

  const revenueValues = months.map((month) => sumScenarioValues(revenue || {}, "Факт БУ", [month]));
  const grossValues = months.map((month, i) => revenueValues[i] - Math.abs(sumScenarioValues(cost || {}, "Факт БУ", [month])));
  const netValues = months.map((month) => sumScenarioValues(net || {}, "Факт БУ", [month]));

  chartInstances["revenue-profit-line"] = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Выручка", data: revenueValues.map(scaled), borderColor: COLORS.revenue, backgroundColor: COLORS.revenue, tension: 0.35, pointRadius: 2, borderWidth: 2 },
        { label: "Вал. прибыль", data: grossValues.map(scaled), borderColor: COLORS.gross, backgroundColor: COLORS.gross, tension: 0.35, pointRadius: 2, borderWidth: 2 },
        { label: "Чист. прибыль", data: netValues.map(scaled), borderColor: COLORS.profit, backgroundColor: COLORS.profit, tension: 0.35, pointRadius: 2, borderWidth: 2 },
      ],
    },
    options: {
      ...baseChartOptions(),
      interaction: { mode: "index", intersect: false },
      plugins: {
        ...baseChartOptions().plugins,
        tooltip: {
          callbacks: {
            label(ctx) {
              return `${ctx.dataset.label}: ${formatMoney(ctx.raw * state.unitDivisor)}`;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 10 } } },
        y: {
          grid: { color: "#f0f0f0" },
          ticks: {
            font: { size: 10 },
            callback(v) { return compactMoney(Number(v) * state.unitDivisor); },
          },
        },
      },
    },
  });
}

function renderRevenuePlanFactChart(data) {
  destroyChart("revenue-plan-fact");
  const canvas = document.getElementById("chartRevenuePlanFact");
  if (!canvas || !window.Chart) return;

  const months = activeMonths();
  const revenue = consolidatedLookup(data)["Выручка"];
  const labels = monthLabels(months);
  const planValues = months.map((month) => sumScenarioValues(revenue || {}, state.compareScenario, [month]));
  const factValues = months.map((month) => sumScenarioValues(revenue || {}, "Факт БУ", [month]));

  chartInstances["revenue-plan-fact"] = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: state.compareScenario,
          data: planValues.map(scaled),
          borderColor: COLORS.plan,
          backgroundColor: COLORS.planFill,
          fill: true,
          tension: 0.35,
          pointRadius: 0,
          borderWidth: 0,
        },
        {
          label: "Факт",
          data: factValues.map(scaled),
          borderColor: COLORS.revenue,
          backgroundColor: "transparent",
          fill: false,
          tension: 0.35,
          pointRadius: 2,
          borderWidth: 2,
        },
      ],
    },
    options: {
      ...baseChartOptions(),
      plugins: {
        ...baseChartOptions().plugins,
        tooltip: {
          callbacks: {
            label(ctx) {
              return `${ctx.dataset.label}: ${formatMoney(ctx.raw * state.unitDivisor)}`;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 10 } } },
        y: {
          grid: { color: "#f0f0f0" },
          ticks: {
            font: { size: 10 },
            callback(v) { return compactMoney(Number(v) * state.unitDivisor); },
          },
        },
      },
    },
  });
}

function renderExpenseStructureChart(data) {
  destroyChart("expense-structure");
  const canvas = document.getElementById("chartExpenseStructure");
  const wrap = document.querySelector("[data-structure-canvas-wrap]");
  const footnote = document.querySelector("[data-structure-footnote]");
  if (!canvas || !window.Chart) return;

  const rows = buildExpenseStructureRows(data);
  const months = activeMonths();
  const lookup = consolidatedLookup(data);
  const expenseKpiTotal = EXPENSE_KPI_NAMES.reduce(
    (sum, name) => sum + Math.abs(sumScenarioValues(lookup[name] || {}, "Факт БУ", months)),
    0,
  );
  const shownTotal = rows.reduce((sum, row) => sum + row.fact, 0);

  if (footnote) {
    footnote.textContent = rows.length
      ? `На графике: ${compactMoney(shownTotal)} · всего расходов (KPI): ${compactMoney(expenseKpiTotal)} · ${state.compareScenario.toLowerCase()} vs факт`
      : "";
  }

  if (!rows.length) {
    if (wrap) {
      wrap.style.removeProperty("--structure-rows");
      wrap.removeAttribute("data-row-count");
    }
    chartInstances["expense-structure"] = new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: { labels: ["Нет данных"], datasets: [{ data: [0], backgroundColor: "#e5e7eb" }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
    });
    return;
  }

  if (wrap) {
    wrap.style.setProperty("--structure-rows", String(rows.length));
    wrap.dataset.rowCount = String(rows.length);
  }

  const labels = rows.map((row) => row.name);
  const factValues = rows.map((row) => scaled(row.fact));
  const planValues = rows.map((row) => scaled(row.plan));

  chartInstances["expense-structure"] = new Chart(canvas.getContext("2d"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: state.compareScenario,
          data: planValues,
          backgroundColor: "#e5e7eb",
          borderRadius: 4,
          barThickness: 16,
          order: 2,
        },
        {
          label: "Факт",
          data: factValues,
          backgroundColor: COLORS.expense,
          borderRadius: 4,
          barThickness: 11,
          order: 1,
        },
      ],
    },
    plugins: [structureBarLabels],
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { right: 84 } },
      datasets: {
        bar: {
          categoryPercentage: 0.72,
          barPercentage: 0.9,
        },
      },
      plugins: {
        legend: {
          position: "top",
          align: "end",
          labels: { boxWidth: 10, boxHeight: 10, font: { size: 10 } },
        },
        tooltip: {
          callbacks: {
            label(ctx) {
              const raw = ctx.raw * state.unitDivisor;
              const plan = (rows[ctx.dataIndex]?.plan || 0);
              const pct = plan ? (rows[ctx.dataIndex].fact / plan) * 100 : 0;
              if (ctx.datasetIndex === 0) {
                return `${state.compareScenario}: ${formatMoney(raw)}`;
              }
              return `Факт: ${formatMoney(raw)} (${percentFormatter.format(pct)}% от ${state.compareScenario.toLowerCase()})`;
            },
          },
        },
      },
      scales: {
        x: {
          beginAtZero: true,
          grid: { color: "#f3f4f6" },
          ticks: {
            font: { size: 9 },
            callback(v) { return compactMoney(Number(v) * state.unitDivisor); },
          },
        },
        y: {
          grid: { display: false },
          ticks: { font: { size: 10, weight: "500" }, color: "#374151" },
        },
      },
    },
  });
  chartInstances["expense-structure"].$unitDivisor = state.unitDivisor;
}

function renderGrossByDirectionChart(data) {
  destroyChart("gross-by-direction");
  const canvas = document.getElementById("chartGrossDirection");
  if (!canvas || !window.Chart) return;

  const rows = (data?.analytics_charts?.gross_profit_by_direction || []).slice(0, 6);
  if (!rows.length) {
    chartInstances["gross-by-direction"] = new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: { labels: ["Нет данных"], datasets: [{ data: [0] }] },
      options: { responsive: true, maintainAspectRatio: false },
    });
    return;
  }

  chartInstances["gross-by-direction"] = new Chart(canvas.getContext("2d"), {
    type: "bar",
    data: {
      labels: rows.map((row) => row.name),
      datasets: [
        { label: "Выручка", data: rows.map((row) => scaled(row.revenue || 0)), backgroundColor: "#93c5fd", barThickness: 12 },
        { label: "Вал. прибыль", data: rows.map((row) => scaled(row.fact || 0)), backgroundColor: COLORS.gross, barThickness: 12 },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "top", align: "end", labels: { boxWidth: 10, font: { size: 10 } } },
        tooltip: {
          callbacks: {
            label(ctx) {
              return `${ctx.dataset.label}: ${formatMoney(ctx.raw * state.unitDivisor)}`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: { color: "#f0f0f0" },
          ticks: { font: { size: 9 }, callback(v) { return compactMoney(Number(v) * state.unitDivisor); } },
        },
        y: { grid: { display: false }, ticks: { font: { size: 9 } } },
      },
    },
  });
}

function renderExpensesMonthlyChart(data) {
  destroyChart("expenses-monthly");
  const canvas = document.getElementById("chartExpensesMonthly");
  if (!canvas || !window.Chart) return;

  const months = activeMonths();
  const monthSet = new Set(months);
  const rows = (data?.analytics_charts?.expenses_by_month || [])
    .filter((row, index) => monthSet.has(row.period || months[index]));
  const labels = rows.map((row) => String(row.month).toLowerCase());

  chartInstances["expenses-monthly"] = new Chart(canvas.getContext("2d"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Факт", data: rows.map((row) => scaled(row.fact || 0)), backgroundColor: COLORS.expense, borderRadius: 2 },
        {
          label: state.compareScenario,
          data: rows.map((row) => scaled(row.plan || 0)),
          type: "line",
          borderColor: "#374151",
          backgroundColor: "#374151",
          borderDash: [4, 3],
          pointStyle: "rectRot",
          pointRadius: 4,
          pointHoverRadius: 5,
          fill: false,
        },
      ],
    },
    options: {
      ...baseChartOptions(),
      plugins: {
        ...baseChartOptions().plugins,
        tooltip: {
          callbacks: {
            label(ctx) {
              return `${ctx.dataset.label}: ${formatMoney(ctx.raw * state.unitDivisor)}`;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 10 } } },
        y: {
          grid: { color: "#f0f0f0" },
          ticks: { font: { size: 10 }, callback(v) { return compactMoney(Number(v) * state.unitDivisor); } },
        },
      },
    },
  });
}

function applyVisibility() {
  CHART_REGISTRY.forEach(({ id }) => {
    document.querySelectorAll(`[data-chart-panel="${id}"]`).forEach((node) => {
      node.classList.toggle("is-hidden", !state.visibleCharts[id]);
    });
  });
}

function renderAll(data) {
  applyVisibility();
  if (state.visibleCharts["kpi-cards"]) renderKpiCards(data);
  if (state.visibleCharts["revenue-profit-line"]) renderRevenueProfitChart(data);
  if (state.visibleCharts["revenue-plan-fact"]) renderRevenuePlanFactChart(data);
  if (state.visibleCharts["expense-structure"]) renderExpenseStructureChart(data);
  if (state.visibleCharts["gross-by-direction"]) renderGrossByDirectionChart(data);
  if (state.visibleCharts["expenses-monthly"]) renderExpensesMonthlyChart(data);
}

function syncFilterButtons(selector, activeSet, attr = "filterValue") {
  document.querySelectorAll(selector).forEach((btn) => {
    const key = attr === "filterValue" ? btn.dataset.filterValue : btn.dataset[attr];
    btn.classList.toggle("is-active", activeSet.has(key));
  });
}

function bindToggleFilters(selector, getSet, onChange, attr = "filterValue") {
  document.querySelectorAll(selector).forEach((button) => {
    button.addEventListener("click", () => {
      const key = attr === "filterValue" ? button.dataset.filterValue : button.dataset[attr];
      const set = getSet();
      if (set.has(key)) set.delete(key);
      else set.add(key);
      syncFilterButtons(selector, getSet(), attr);
      onChange?.();
    });
  });
}

function initFilters(rerender) {
  document.querySelectorAll("[data-filter-tax]").forEach((button) => {
    button.addEventListener("click", () => {
      state.taxBucket = button.dataset.filterTax || "all";
      document.querySelectorAll("[data-filter-tax]").forEach((item) => {
        item.classList.toggle("is-active", item.dataset.filterTax === state.taxBucket);
      });
      rerender();
    });
  });

  document.querySelectorAll("[data-filter-unit]").forEach((button) => {
    button.addEventListener("click", () => {
      state.unitDivisor = Number(button.dataset.filterUnit || 1000);
      document.querySelectorAll("[data-filter-unit]").forEach((item) => {
        item.classList.toggle("is-active", Number(item.dataset.filterUnit) === state.unitDivisor);
      });
      rerender();
    });
  });

  document.querySelectorAll("[data-filter-scenario]").forEach((button) => {
    button.addEventListener("click", () => {
      state.compareScenario = button.dataset.filterScenario || "План";
      document.querySelectorAll("[data-filter-scenario]").forEach((item) => {
        item.classList.toggle("is-active", item.dataset.filterScenario === state.compareScenario);
      });
      rerender();
    });
  });
}

let serverFilterTimer = null;
let serverFilterController = null;

function displayPeriod(period) {
  if (!period) return "";
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (match) {
    const name = MONTHS_RU[Number(match[2]) - 1];
    if (name) return `${name} ${match[1]}`;
  }
  return dashboardData?.period_labels?.[period] || period;
}

function setServerFilterState({ loading = false, error = "" } = {}) {
  document.querySelector("[data-server-filter-loading]")?.classList.toggle("hidden", !loading);
  const errorNode = document.querySelector("[data-server-filter-error]");
  if (errorNode) {
    errorNode.textContent = error;
    errorNode.classList.toggle("hidden", !error);
  }
  document.querySelectorAll("[data-server-filter], [data-period-trigger], [data-period-clear], [data-server-filter-reset]").forEach((node) => {
    node.disabled = loading;
  });
}

function periodButtonLabel() {
  if (state.periodFrom && state.periodTo) {
    if (state.periodFrom === state.periodTo) return displayPeriod(state.periodFrom);
    return `${displayPeriod(state.periodFrom)} — ${displayPeriod(state.periodTo)}`;
  }
  if (state.periodFrom) return displayPeriod(state.periodFrom);
  return "Все месяцы";
}

function periodMonthName(period) {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (match) return MONTHS_RU[Number(match[2]) - 1] || period;
  return period;
}

function periodHasData(period) {
  const periods = dashboardData?.data_periods || dashboardData?.months || dashboardData?.periods || [];
  return periods.includes(period);
}

function groupedPeriodYears() {
  const periods = dashboardData?.available_periods || dashboardData?.periods || dashboardData?.months || [];
  const grouped = new Map();
  periods.forEach((period) => {
    const match = /^(\d{4})-(\d{2})$/.exec(period);
    const year = match ? match[1] : "Период";
    if (!grouped.has(year)) grouped.set(year, []);
    grouped.get(year).push(period);
  });
  return grouped;
}

function periodYearList() {
  return [...groupedPeriodYears().keys()].filter((year) => /^\d{4}$/.test(year));
}

function visiblePeriodYear() {
  const years = periodYearList();
  if (!years.length) return "";
  if (years.includes(state.periodViewYear)) return state.periodViewYear;
  if (state.periodFrom && years.includes(state.periodFrom.slice(0, 4))) {
    return state.periodFrom.slice(0, 4);
  }
  return years[years.length - 1];
}

function shiftPeriodViewYear(delta) {
  const years = periodYearList();
  const current = visiblePeriodYear();
  const index = years.indexOf(current);
  const next = years[index + delta];
  if (!next) return;
  state.periodViewYear = next;
  renderPeriodPicker();
}

function currentPeriodRange() {
  const from = state.periodFrom;
  let to = state.periodTo;
  if (!to && state.periodPicking) to = state.periodHover || from;
  if (from && to && from > to) return [to, from];
  return [from, to];
}

function syncPeriodMonthClasses() {
  const calendar = document.querySelector("[data-period-calendar]");
  if (!calendar) return;
  const [from, to] = currentPeriodRange();
  calendar.querySelectorAll("[data-period-month]").forEach((button) => {
    const period = button.getAttribute("data-period-month");
    const inRange = Boolean(from && to && period >= from && period <= to);
    const endpoint = Boolean(period && (period === from || period === to));
    button.classList.toggle("is-in-range", inRange);
    button.classList.toggle("is-endpoint", endpoint);
  });
}

function renderPeriodPicker() {
  const root = document.querySelector("[data-period-picker]");
  if (!root) return;
  const calendar = root.querySelector("[data-period-calendar]");
  const summary = root.querySelector("[data-period-summary]");
  const hint = root.querySelector("[data-period-pick-hint]");
  const yearNav = root.querySelector("[data-period-year-nav]");
  const yearLabel = root.querySelector("[data-period-year-label]");
  const yearPrev = root.querySelector("[data-period-year-prev]");
  const yearNext = root.querySelector("[data-period-year-next]");
  if (summary) summary.textContent = periodButtonLabel();
  root.classList.toggle("is-active", Boolean(state.periodFrom || state.periodTo));
  const years = periodYearList();
  const viewYear = visiblePeriodYear();
  state.periodViewYear = viewYear;
  if (hint) {
    hint.textContent = state.periodPicking && state.periodFrom
      ? `Начало: ${displayPeriod(state.periodFrom)}. Переключите год при необходимости и выберите конец`
      : years.length > 1
        ? "Сначала начало, затем конец. Год можно переключить"
        : "Сначала начало диапазона, затем конец";
  }
  yearNav?.classList.toggle("is-hidden", years.length < 2);
  if (yearLabel) yearLabel.textContent = viewYear || "Период";
  const yearIndex = years.indexOf(viewYear);
  if (yearPrev) yearPrev.disabled = yearIndex <= 0;
  if (yearNext) yearNext.disabled = yearIndex < 0 || yearIndex >= years.length - 1;
  if (!calendar) return;
  const grouped = groupedPeriodYears();
  const periods = viewYear ? (grouped.get(viewYear) || []) : [...grouped.values()].flat();
  calendar.innerHTML = `
    <div class="almabi-period-year">
      <div class="almabi-period-months">
        ${periods.map((period) => {
          const empty = !periodHasData(period);
          return `<button type="button" class="almabi-period-month${empty ? " is-empty" : ""}" data-period-month="${period}"${empty ? " disabled" : ""}>${periodMonthName(period)}</button>`;
        }).join("")}
      </div>
    </div>
  `;
  syncPeriodMonthClasses();
}

function commitIncompletePeriodPick(schedule) {
  if (!(state.periodPicking && state.periodFrom && !state.periodTo)) return;
  state.periodTo = state.periodFrom;
  state.periodPicking = false;
  state.periodHover = "";
  renderPeriodPicker();
  schedule?.();
}

function closePeriodPicker(schedule) {
  const root = document.querySelector("[data-period-picker]");
  if (!root) return;
  const wasOpen = root.classList.contains("is-open");
  root.classList.remove("is-open");
  root.querySelector("[data-period-trigger]")?.setAttribute("aria-expanded", "false");
  root.querySelector("[data-period-menu]")?.classList.add("hidden");
  if (wasOpen) commitIncompletePeriodPick(schedule);
}

function updateServerFilterHint() {
  const hint = document.querySelector("[data-server-filter-hint]");
  if (!hint) return;
  hint.textContent = `Диапазон: ${displayPeriod(state.periodFrom) || "с начала"} — ${displayPeriod(state.periodTo) || "до конца"}`;
}

function serverFilterParams() {
  const params = new URLSearchParams();
  document.querySelectorAll("[data-server-filter]").forEach((select) => {
    if (select.value) params.set(select.dataset.serverFilter, select.value);
  });
  if (state.periodFrom) params.set("period_from", state.periodFrom);
  if (state.periodTo) params.set("period_to", state.periodTo);
  return params;
}

async function reloadServerDashboard(rerender) {
  updateServerFilterHint();
  if (state.periodFrom && state.periodTo && state.periodFrom > state.periodTo) {
    serverFilterController?.abort();
    setServerFilterState({ error: "«Период с» не может быть позже «Период по»." });
    return;
  }
  serverFilterController?.abort();
  serverFilterController = new AbortController();
  setServerFilterState({ loading: true });
  try {
    const params = serverFilterParams().toString();
    const response = await fetch(`/api/almabi/dashboard${params ? `?${params}` : ""}`, {
      signal: serverFilterController.signal,
      headers: { Accept: "application/json" },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Ошибка API (${response.status})`);
    const previousDataPeriods = dashboardData?.data_periods;
    const previousAvailable = dashboardData?.available_periods;
    dashboardData = payload;
    if (!dashboardData.available_periods?.length && previousAvailable?.length) {
      dashboardData.available_periods = previousAvailable;
    } else if (!dashboardData.available_periods?.length) {
      dashboardData.available_periods = dashboardData.periods || dashboardData.months || [];
    }
    if (previousDataPeriods?.length && (dashboardData.data_periods || []).length < previousDataPeriods.length) {
      dashboardData.data_periods = previousDataPeriods;
    }
    renderPeriodPicker();
    rerender();
    setServerFilterState();
  } catch (error) {
    if (error.name === "AbortError") return;
    setServerFilterState({ error: error.message || "Не удалось обновить графики." });
  }
}

function initServerFilters(rerender) {
  const schedule = () => {
    clearTimeout(serverFilterTimer);
    serverFilterTimer = setTimeout(() => reloadServerDashboard(rerender), 250);
  };
  document.querySelectorAll("[data-server-filter]").forEach((select) => {
    select.addEventListener("change", schedule);
  });
  const periodRoot = document.querySelector("[data-period-picker]");
  const periodTrigger = periodRoot?.querySelector("[data-period-trigger]");
  const periodMenu = periodRoot?.querySelector("[data-period-menu]");
  periodTrigger?.addEventListener("click", (event) => {
    event.stopPropagation();
    const willOpen = !periodRoot.classList.contains("is-open");
    closePeriodPicker(schedule);
    if (willOpen) {
      periodRoot.classList.add("is-open");
      periodMenu?.classList.remove("hidden");
      periodTrigger.setAttribute("aria-expanded", "true");
    }
  });
  periodMenu?.addEventListener("click", (event) => {
    event.stopPropagation();
    if (event.target.closest("[data-period-year-prev]")) {
      shiftPeriodViewYear(-1);
      return;
    }
    if (event.target.closest("[data-period-year-next]")) {
      shiftPeriodViewYear(1);
      return;
    }
    const monthButton = event.target.closest("[data-period-month]");
    if (monthButton) {
      const period = monthButton.getAttribute("data-period-month");
      if (!period || monthButton.disabled || !periodHasData(period)) return;
      if (!state.periodPicking || !state.periodFrom || state.periodTo) {
        state.periodFrom = period;
        state.periodTo = "";
        state.periodPicking = true;
        state.periodHover = period;
        renderPeriodPicker();
        return;
      }
      if (period < state.periodFrom) {
        state.periodTo = state.periodFrom;
        state.periodFrom = period;
      } else {
        state.periodTo = period;
      }
      state.periodPicking = false;
      state.periodHover = "";
      renderPeriodPicker();
      closePeriodPicker();
      schedule();
      return;
    }
    if (event.target.closest("[data-period-clear]")) {
      state.periodFrom = "";
      state.periodTo = "";
      state.periodPicking = false;
      state.periodHover = "";
      renderPeriodPicker();
      closePeriodPicker();
      schedule();
    }
  });
  periodMenu?.addEventListener("mouseover", (event) => {
    const monthButton = event.target.closest("[data-period-month]");
    if (!monthButton || !state.periodPicking || state.periodTo) return;
    const period = monthButton.getAttribute("data-period-month");
    if (!period || monthButton.disabled || !periodHasData(period) || state.periodHover === period) return;
    state.periodHover = period;
    syncPeriodMonthClasses();
  });
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-period-picker]")) return;
    closePeriodPicker(schedule);
  });
  document.querySelector("[data-server-filter-reset]")?.addEventListener("click", () => {
    clearTimeout(serverFilterTimer);
    document.querySelectorAll("[data-server-filter]").forEach((control) => {
      control.value = "";
    });
    state.periodFrom = "";
    state.periodTo = "";
    state.periodPicking = false;
    state.periodHover = "";
    state.periodViewYear = "";
    renderPeriodPicker();
    updateServerFilterHint();
    reloadServerDashboard(rerender);
  });
  renderPeriodPicker();
  updateServerFilterHint();
}

function initChartConfig(rerender) {
  const list = document.querySelector("[data-charts-config-list]");
  if (!list) return;

  list.innerHTML = CHART_REGISTRY.map(({ id, label }) => `
    <label class="charts-config-item">
      <input type="checkbox" data-chart-toggle="${id}" ${state.visibleCharts[id] ? "checked" : ""} />
      <span>${label}</span>
    </label>
  `).join("");

  list.querySelectorAll("[data-chart-toggle]").forEach((input) => {
    input.addEventListener("change", () => {
      state.visibleCharts[input.dataset.chartToggle] = input.checked;
      saveChartConfig(state.visibleCharts);
      rerender();
    });
  });
}

function initPage() {
  dashboardData = readDashboard();
  const root = document.querySelector("[data-charts-page]");
  if (!root) return;

  const stored = loadChartConfig();
  if (stored?.visibleCharts) {
    state.visibleCharts = { ...defaultVisibleCharts(), ...stored.visibleCharts };
  }

  const rerender = () => {
    if (!dashboardData?.meta?.parsed) return;
    renderAll(dashboardData);
  };

  initFilters(rerender);
  initServerFilters(rerender);
  initChartConfig(rerender);

  if (!dashboardData?.meta?.parsed) {
    const kpi = document.querySelector("[data-charts-kpi-grid]");
    if (kpi) {
      kpi.innerHTML = `
        <div class="charts-empty" style="grid-column: 1 / -1">
          <p class="font-semibold text-gray-800">Нет данных для графиков</p>
          <p class="mt-2">Загрузите выгрузки 1С через «шестерёнку» в шапке.</p>
        </div>
      `;
    }
    return;
  }

  rerender();
}

document.addEventListener("DOMContentLoaded", initPage);
