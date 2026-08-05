import "./app.css";

const SIDEBAR_STORAGE_KEY = "almabi-sidebar";

function isLargeScreen() {
  return window.matchMedia("(min-width: 1024px)").matches;
}

function setSidebarState(open) {
  const state = open ? "open" : "closed";
  document.body.dataset.sidebar = state;
  localStorage.setItem(SIDEBAR_STORAGE_KEY, state);

  document.querySelectorAll("[data-sidebar-toggle]").forEach((button) => {
    button.setAttribute("aria-expanded", String(open));
    button.querySelector("[data-sidebar-icon-open]")?.classList.toggle("hidden", !open);
    button.querySelector("[data-sidebar-icon-closed]")?.classList.toggle("hidden", open);
  });
}

function initSidebar() {
  const sidebar = document.querySelector("[data-app-sidebar]");
  if (!sidebar) return;

  const stored = localStorage.getItem(SIDEBAR_STORAGE_KEY);
  const initialOpen = stored ? stored === "open" : isLargeScreen();
  setSidebarState(initialOpen);

  document.querySelectorAll("[data-sidebar-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const isOpen = document.body.dataset.sidebar === "open";
      setSidebarState(!isOpen);
    });
  });

  document.querySelector("[data-sidebar-backdrop]")?.addEventListener("click", () => {
    setSidebarState(false);
  });

  window.addEventListener("resize", () => {
    if (!localStorage.getItem(SIDEBAR_STORAGE_KEY) && !isLargeScreen()) {
      setSidebarState(false);
    }
  });
}

const ALMABI_EXPORT_ORDER = ["buh", "realization", "cost", "cost_nu"];
const ALMABI_REQUIRED_EXPORTS = ["buh", "realization", "cost"];
const ALMABI_EXPORT_LABELS = {
  buh: "Бух.регистр",
  realization: "Реализация",
  cost: "Себестоимость",
  cost_nu: "Себестоимость НУ",
};

function initAlmabiDataSourceMenu() {
  const root = document.querySelector("[data-almabi-data-menu]");
  if (!root) return;

  const uploadForm = root.querySelector("[data-almabi-upload-form]");
  const uploadStatus = root.querySelector("[data-almabi-upload-status]");
  const uploadButton = root.querySelector("[data-almabi-upload-button]");
  const dropZone = root.querySelector("[data-almabi-drop-zone]");
  const dropMessage = root.querySelector("[data-almabi-drop-message]");
  const exportInputs = Array.from(root.querySelectorAll("[data-almabi-export-input]"));
  const planForecastInput = root.querySelector("[data-almabi-plan-forecast-input]");
  const selectedName = root.querySelector("[data-almabi-selected-name]");
  const selectedFiles = Object.fromEntries(ALMABI_EXPORT_ORDER.map((key) => [key, null]));
  let selectedPlanForecastFile = null;

  const showStatus = (message, variant = "neutral") => {
    if (!uploadStatus) return;
    uploadStatus.textContent = message || "";
    const colorByVariant = {
      neutral: "text-gray-500",
      error: "text-red-600",
      success: "text-green-700",
      progress: "text-brand-700",
    };
    uploadStatus.className = `mt-2 text-xs ${colorByVariant[variant] || colorByVariant.neutral}`;
  };

  const setUploading = (isUploading) => {
    if (!uploadButton) return;
    uploadButton.disabled = isUploading;
    uploadButton.textContent = isUploading ? "Проверяем и загружаем..." : "Загрузить и собрать дашборд";
  };

  const renderSelectedFiles = () => {
    const lines = ALMABI_EXPORT_ORDER.filter((key) => selectedFiles[key]).map(
      (key) => `${ALMABI_EXPORT_LABELS[key]}: ${selectedFiles[key].name}`,
    );
    if (selectedPlanForecastFile) {
      lines.push(`План / прогноз: ${selectedPlanForecastFile.name}`);
    }
    if (selectedName) {
      if (!lines.length) {
        selectedName.classList.add("hidden");
        selectedName.textContent = "";
      } else {
        selectedName.textContent = lines.join(" · ");
        selectedName.classList.remove("hidden");
      }
    }
    if (dropMessage) {
      if (!lines.length) {
        dropMessage.textContent =
          "Загрузите 3 обязательных файла: бухрегистр, реализация и себестоимость. Можно выбрать все сразу через Ctrl+клик.";
        dropMessage.classList.remove("border-brand-200", "bg-brand-50", "text-brand-700");
        dropMessage.classList.add("border-gray-300", "bg-gray-50", "text-gray-500");
      } else {
        dropMessage.textContent = `Выбрано файлов: ${lines.length}`;
        dropMessage.classList.remove("border-gray-300", "bg-gray-50", "text-gray-500");
        dropMessage.classList.add("border-brand-200", "bg-brand-50", "text-brand-700");
      }
    }
  };

  const setSelectedFile = (exportType, file) => {
    if (!file) return false;
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      showStatus("Нужен файл .xlsx", "error");
      return false;
    }
    selectedFiles[exportType] = file;
    const input = exportInputs.find((item) => item.dataset.almabiExportInput === exportType);
    if (input) {
      const transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
    }
    renderSelectedFiles();
    showStatus("Готов к загрузке. Нажмите «Загрузить и собрать дашборд».", "neutral");
    return true;
  };

  const assignFiles = (files, source = "selected") => {
    const xlsxFiles = Array.from(files || []).filter((file) => file.name.toLowerCase().endsWith(".xlsx"));
    if (!xlsxFiles.length) {
      showStatus("Нужен хотя бы один файл .xlsx", "error");
      return false;
    }
    if (xlsxFiles.length === 1) {
      const nextType = ALMABI_EXPORT_ORDER.find((key) => !selectedFiles[key]) || ALMABI_EXPORT_ORDER[0];
      setSelectedFile(nextType, xlsxFiles[0]);
      showStatus(`${ALMABI_EXPORT_LABELS[nextType]}: ${xlsxFiles[0].name}`, source === "dropped" ? "success" : "neutral");
      return true;
    }
    xlsxFiles.slice(0, ALMABI_EXPORT_ORDER.length).forEach((file, index) => {
      setSelectedFile(ALMABI_EXPORT_ORDER[index], file);
    });
    showStatus(`Добавлено файлов: ${Math.min(xlsxFiles.length, ALMABI_EXPORT_ORDER.length)}`, "success");
    return true;
  };

  exportInputs.forEach((input) => {
    input.addEventListener("change", () => {
      const exportType = input.dataset.almabiExportInput;
      if (!exportType) return;
      setSelectedFile(exportType, input.files?.[0]);
    });
  });

  planForecastInput?.addEventListener("change", () => {
    const file = planForecastInput.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      showStatus("Форма план/прогноз — нужен файл .xlsx", "error");
      return;
    }
    selectedPlanForecastFile = file;
    renderSelectedFiles();
    showStatus("Готов к загрузке. Нажмите «Загрузить и собрать дашборд».", "neutral");
  });

  dropZone?.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropZone.classList.add("border-brand-400", "bg-brand-50");
  });

  dropZone?.addEventListener("dragleave", () => {
    dropZone.classList.remove("border-brand-400", "bg-brand-50");
  });

  dropZone?.addEventListener("drop", (event) => {
    event.preventDefault();
    dropZone.classList.remove("border-brand-400", "bg-brand-50");
    assignFiles(event.dataTransfer?.files, "dropped");
  });

  document.addEventListener("paste", (event) => {
    const panel = document.querySelector("[data-file-menu-panel]");
    if (!panel || panel.classList.contains("hidden")) return;
    const pastedFiles = Array.from(event.clipboardData?.files || []).filter((file) =>
      file.name.toLowerCase().endsWith(".xlsx"),
    );
    if (!pastedFiles.length) return;
    event.preventDefault();
    assignFiles(pastedFiles, "pasted");
  });

  uploadForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const missingRequired = ALMABI_REQUIRED_EXPORTS.filter((key) => !selectedFiles[key]);
    const hasExports = ALMABI_EXPORT_ORDER.some((key) => selectedFiles[key]);
    if (missingRequired.length && hasExports) {
      showStatus(
        `Загрузите обязательные файлы: ${missingRequired.map((key) => ALMABI_EXPORT_LABELS[key]).join(", ")}`,
        "error",
      );
      return;
    }
    if (!hasExports && !selectedPlanForecastFile) {
      showStatus("Выберите выгрузки 1С или форму план/прогноз", "error");
      return;
    }

    const formData = new FormData();
    ALMABI_EXPORT_ORDER.forEach((key) => {
      if (selectedFiles[key]) {
        formData.append(`${key}_file`, selectedFiles[key]);
      }
    });
    if (selectedPlanForecastFile) {
      formData.append("plan_forecast_file", selectedPlanForecastFile);
    }
    setUploading(true);
    showStatus("Файлы отправлены. Проверяем структуру и собираем дашборд...", "progress");
    try {
      const response = await fetch("/api/almabi/files/upload-set", {
        method: "POST",
        body: formData,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || "Файлы не прошли проверку");
      }
      const warningText = Array.isArray(payload.warnings) && payload.warnings.length
        ? payload.warnings.join(" ")
        : "";
      showStatus(
        warningText
          ? `Выгрузки загружены. ${warningText} Обновляем дашборд...`
          : "Выгрузки загружены. Обновляем дашборд...",
        "success",
      );
      window.setTimeout(() => window.location.reload(), 700);
    } catch (error) {
      showStatus(error.message, "error");
      setUploading(false);
    }
  });
}

function initFileMenuOpeners() {
  const panel = document.querySelector("[data-file-menu-panel]");
  if (!panel) return;

  const isMenuOpen = () => !panel.classList.contains("hidden");

  const closeMenu = () => {
    panel.classList.add("hidden");
  };

  const openMenu = () => {
    panel.classList.remove("hidden");
  };

  const toggleMenu = (event) => {
    event.stopPropagation();
    if (isMenuOpen()) closeMenu();
    else openMenu();
  };

  document.querySelectorAll("[data-file-menu-open], [data-file-menu-toggle]").forEach((button) => {
    button.addEventListener("click", toggleMenu);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initAlmabiDataSourceMenu();
  initFileMenuOpeners();
  initSidebar();
});
