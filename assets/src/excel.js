import "./excel-page.css";
import "@univerjs/preset-sheets-core/lib/index.css";

import { UniverSheetsCorePreset } from "@univerjs/preset-sheets-core";
import UniverPresetSheetsCoreEnUS from "@univerjs/preset-sheets-core/locales/en-US";
import { createUniver, LocaleType, mergeLocales } from "@univerjs/presets";
import ExcelJS from "exceljs";

const WORKBOOK_ID = "active-excel-workbook";

function setStatus(message, variant = "neutral") {
  const status = document.querySelector("[data-excel-status]");
  if (!status) return;
  if (!message) {
    status.textContent = "";
    status.className = "hidden shrink-0 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600";
    return;
  }
  status.classList.remove("hidden");
  status.textContent = message;
  const colorByVariant = {
    neutral: "text-gray-600",
    progress: "text-brand-700",
    error: "text-red-600",
  };
  status.className = `shrink-0 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm ${
    colorByVariant[variant] || colorByVariant.neutral
  }`;
}

function refreshUniverLayout() {
  window.dispatchEvent(new Event("resize"));
  requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
}

function sheetNameToId(name, index) {
  return `sheet_${index}_${String(name || "sheet").replace(/[^a-zA-Z0-9_-]/g, "_")}`;
}

function encodeColumn(index) {
  let value = index + 1;
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function encodeCell(rowIndex, columnIndex) {
  return `${encodeColumn(columnIndex)}${rowIndex + 1}`;
}

function decodeCell(address) {
  const match = String(address).match(/^([A-Z]+)(\d+)$/i);
  if (!match) return { r: 0, c: 0 };
  const letters = match[1].toUpperCase();
  let column = 0;
  for (const letter of letters) {
    column = column * 26 + (letter.charCodeAt(0) - 64);
  }
  return { r: Number(match[2]) - 1, c: column - 1 };
}

function decodeRange(range) {
  const [start, end = start] = String(range).split(":");
  return { s: decodeCell(start), e: decodeCell(end) };
}

function cellToUniver(cell) {
  const data = {};
  if (cell.formula) {
    data.f = cell.formula.startsWith("=") ? cell.formula : `=${cell.formula}`;
  }
  const value = cell.result ?? cell.value;
  if (value instanceof Date) {
    data.v = value.toISOString();
  } else if (value && typeof value === "object" && "text" in value) {
    data.v = value.text;
  } else if (value && typeof value === "object" && "richText" in value) {
    data.v = value.richText.map((part) => part.text || "").join("");
  } else if (value && typeof value === "object" && "hyperlink" in value) {
    data.v = value.text || value.hyperlink;
  } else if (value !== undefined && value !== null) {
    data.v = value;
  } else if (data.f) {
    data.v = data.f;
  }
  return data;
}

function workbookToUniverSnapshot(workbook, fileName) {
  const sheetOrder = [];
  const sheets = {};

  workbook.worksheets.forEach((worksheet, index) => {
    const sheetName = worksheet.name;
    const sheetId = sheetNameToId(sheetName, index);
    const cellData = {};
    let maxRow = Math.max(worksheet.rowCount || 1, 100);
    let maxColumn = Math.max(worksheet.columnCount || 1, 26);

    worksheet.eachRow({ includeEmpty: false }, (row, rowNumber) => {
      maxRow = Math.max(maxRow, rowNumber);
      row.eachCell({ includeEmpty: false }, (cell, colNumber) => {
        maxColumn = Math.max(maxColumn, colNumber);
        const rowIndex = rowNumber - 1;
        const colIndex = colNumber - 1;
        cellData[rowIndex] ||= {};
        cellData[rowIndex][colIndex] = cellToUniver(cell);
      });
    });

    const mergeData = (worksheet.model?.merges || []).map((merge) => {
      const decoded = decodeRange(merge);
      return {
        startRow: decoded.s.r,
        startColumn: decoded.s.c,
        endRow: decoded.e.r,
        endColumn: decoded.e.c,
      };
    });

    sheetOrder.push(sheetId);
    sheets[sheetId] = {
      id: sheetId,
      name: sheetName,
      tabColor: "",
      hidden: worksheet.state && worksheet.state !== "visible" ? 1 : 0,
      rowCount: Math.max(maxRow + 50, 100),
      columnCount: Math.max(maxColumn + 5, 26),
      zoomRatio: 1,
      scrollTop: 0,
      scrollLeft: 0,
      defaultColumnWidth: 88,
      defaultRowHeight: 24,
      rowHeader: { width: 46 },
      columnHeader: { height: 24 },
      freeze: { startRow: -1, startColumn: -1, ySplit: 0, xSplit: 0 },
      mergeData,
      cellData,
      rowData: {},
      columnData: Object.fromEntries(
        worksheet.columns.map((column, colIndex) => [colIndex, { w: Math.max(48, Math.round((column.width || 11) * 8)) }]),
      ),
      showGridlines: 1,
      rightToLeft: 0,
    };
  });

  return {
    id: WORKBOOK_ID,
    name: fileName || "active.xlsx",
    appVersion: "3.0.0",
    locale: LocaleType.EN_US,
    styles: {},
    sheetOrder,
    sheets,
  };
}

function univerSheetToWorksheet(sheet) {
  const cellData = sheet.cellData || {};
  const worksheet = new ExcelJS.Workbook().addWorksheet(sheet.name || "Sheet");

  Object.entries(cellData).forEach(([rowKey, row]) => {
    const rowNumber = Number(rowKey) + 1;
    Object.entries(row || {}).forEach(([colKey, cell]) => {
      if (cell?.f) {
        worksheet.getCell(rowNumber, Number(colKey) + 1).value = {
          formula: String(cell.f).replace(/^=/, ""),
          result: cell.v ?? null,
        };
      } else {
        worksheet.getCell(rowNumber, Number(colKey) + 1).value = cell?.v ?? null;
      }
    });
  });

  (sheet.mergeData || []).forEach((merge) => {
    worksheet.mergeCells(merge.startRow + 1, merge.startColumn + 1, merge.endRow + 1, merge.endColumn + 1);
  });
  Object.entries(sheet.columnData || {}).forEach(([colIndex, column]) => {
    worksheet.getColumn(Number(colIndex) + 1).width = Math.max(6, Math.round((column?.w || sheet.defaultColumnWidth || 88) / 8));
  });
  return worksheet;
}

async function snapshotToWorkbookBuffer(snapshot) {
  const workbook = new ExcelJS.Workbook();
  workbook.creator = "OPOP BI";
  workbook.created = new Date();
  const orderedIds = snapshot.sheetOrder?.length ? snapshot.sheetOrder : Object.keys(snapshot.sheets || {});
  orderedIds.forEach((sheetId) => {
    const sheet = snapshot.sheets?.[sheetId];
    if (!sheet) return;
    const exportedSheet = univerSheetToWorksheet(sheet);
    const worksheet = workbook.addWorksheet(sheet.name || sheetId);
    exportedSheet.eachRow({ includeEmpty: true }, (row, rowNumber) => {
      row.eachCell({ includeEmpty: true }, (cell, colNumber) => {
        worksheet.getCell(rowNumber, colNumber).value = cell.value;
      });
    });
    (sheet.mergeData || []).forEach((merge) => {
      worksheet.mergeCells(merge.startRow + 1, merge.startColumn + 1, merge.endRow + 1, merge.endColumn + 1);
    });
    Object.entries(sheet.columnData || {}).forEach(([colIndex, column]) => {
      worksheet.getColumn(Number(colIndex) + 1).width = Math.max(6, Math.round((column?.w || sheet.defaultColumnWidth || 88) / 8));
    });
  });
  return workbook.xlsx.writeBuffer();
}

async function loadActiveWorkbook() {
  const response = await fetch("/api/excel/active");
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Не удалось загрузить активный Excel-файл");
  }
  const fileName = response.headers.get("content-disposition")?.match(/filename=\"?([^\";]+)\"?/)?.[1];
  const arrayBuffer = await response.arrayBuffer();
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.load(arrayBuffer);
  return workbookToUniverSnapshot(workbook, fileName || "active.xlsx");
}

function initUniver(snapshot) {
  const { univerAPI } = createUniver({
    locale: LocaleType.EN_US,
    locales: {
      [LocaleType.EN_US]: mergeLocales(UniverPresetSheetsCoreEnUS),
    },
    presets: [
      UniverSheetsCorePreset({
        container: "excel-editor-app",
      }),
    ],
  });
  univerAPI.createWorkbook(snapshot);
  refreshUniverLayout();
  window.setTimeout(refreshUniverLayout, 150);
  return univerAPI;
}

async function saveAsNewVersion(univerAPI) {
  const workbook = univerAPI.getActiveWorkbook();
  if (!workbook) {
    throw new Error("Книга ещё не загружена");
  }
  await workbook.endEditingAsync?.(true);
  const snapshot = workbook.save();
  const output = await snapshotToWorkbookBuffer(snapshot);
  const blob = new Blob([output], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  const formData = new FormData();
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  formData.append("file", blob, `excel-editor-${stamp}.xlsx`);

  const response = await fetch("/api/excel/save-version", {
    method: "POST",
    body: formData,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || "Не удалось сохранить новую версию");
  }
  return payload;
}

document.addEventListener("DOMContentLoaded", async () => {
  const root = document.querySelector("[data-excel-editor-root]");
  if (!root) return;

  const saveButton = root.querySelector("[data-excel-save]");
  const reloadButton = root.querySelector("[data-excel-reload]");
  let univerAPI = null;

  reloadButton?.addEventListener("click", () => window.location.reload());

  try {
    setStatus("Загружаем файл...", "progress");
    const snapshot = await loadActiveWorkbook();
    univerAPI = initUniver(snapshot);
    setStatus("");
  } catch (error) {
    setStatus(error.message, "error");
  }

  saveButton?.addEventListener("click", async () => {
    saveButton.disabled = true;
    try {
      setStatus("Экспортируем и проверяем файл...", "progress");
      await saveAsNewVersion(univerAPI);
      setStatus("Версия сохранена. Обновляем...", "progress");
      window.setTimeout(() => window.location.reload(), 900);
    } catch (error) {
      setStatus(error.message, "error");
      saveButton.disabled = false;
    }
  });
});
