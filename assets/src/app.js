import "./app.css";

function initSortableTables() {
  const parseNumber = (text) => {
    const normalized = String(text || "")
      .replace(/\s+/g, "")
      .replace(/%/g, "")
      .replace(/,/g, ".")
      .replace(/[^0-9.\-]/g, "");
    const value = Number.parseFloat(normalized);
    return Number.isFinite(value) ? value : 0;
  };

  const compare = (a, b, type) => {
    if (type === "number") return parseNumber(a) - parseNumber(b);
    return String(a || "").localeCompare(String(b || ""), "ru");
  };

  document.querySelectorAll("table.sortable-table").forEach((table) => {
    const headers = Array.from(table.querySelectorAll("thead th.sortable"));
    const tbody = table.querySelector("tbody");
    if (!tbody || !headers.length) return;

    headers.forEach((th, index) => {
      th.dataset.sortDir = "none";
      th.addEventListener("click", () => {
        const rows = Array.from(tbody.querySelectorAll("tr"));
        if (!rows.length) return;
        if (rows.some((row) => row.querySelector("td[colspan]"))) return;

        const nextDir = th.dataset.sortDir === "asc" ? "desc" : "asc";
        headers.forEach((item) => {
          item.dataset.sortDir = "none";
        });
        th.dataset.sortDir = nextDir;

        const type = th.dataset.sortType || "text";
        rows.sort((rowA, rowB) => {
          const a = rowA.children[index]?.innerText?.trim() || "";
          const b = rowB.children[index]?.innerText?.trim() || "";
          const base = compare(a, b, type);
          return nextDir === "asc" ? base : -base;
        });
        rows.forEach((row) => tbody.appendChild(row));
      });
    });
  });
}

function initFileMenu() {
  const root = document.querySelector("[data-file-menu]");
  if (!root) return;

  const toggle = root.querySelector("[data-file-menu-toggle]");
  const panel = root.querySelector("[data-file-menu-panel]");
  const uploadForm = root.querySelector("[data-file-upload-form]");
  const uploadStatus = root.querySelector("[data-file-upload-status]");
  const uploadButton = root.querySelector("[data-file-upload-button]");
  const dropZone = root.querySelector("[data-file-drop-zone]");
  const dropMessage = root.querySelector("[data-file-drop-message]");
  const fileInput = uploadForm?.querySelector('input[type="file"]');
  const selectedName = root.querySelector("[data-file-selected-name]");
  let selectedFile = null;

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
    uploadButton.textContent = isUploading ? "Проверяем и загружаем..." : "Проверить и загрузить";
  };

  const setSelectedFile = (file, source = "selected") => {
    if (!file) return false;
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      showStatus("Нужен файл .xlsx", "error");
      return false;
    }
    selectedFile = file;
    if (selectedName) {
      selectedName.textContent = `Выбран файл: ${file.name}`;
      selectedName.classList.remove("hidden");
    }
    if (dropMessage) {
      const sourceLabels = {
        dropped: "Файл добавлен перетаскиванием",
        pasted: "Файл добавлен из буфера",
        selected: "Файл выбран",
      };
      dropMessage.textContent = `${sourceLabels[source] || "Файл выбран"}: ${file.name}`;
      dropMessage.classList.remove("border-gray-300", "bg-gray-50", "text-gray-500");
      dropMessage.classList.add("border-brand-200", "bg-brand-50", "text-brand-700");
    }
    showStatus("Готов к загрузке. Нажмите «Проверить и загрузить».", "neutral");
    return true;
  };

  const closeMenu = () => panel?.classList.add("hidden");

  document.addEventListener("click", (event) => {
    if (!panel || panel.classList.contains("hidden")) return;
    const target = event.target;
    if (root.contains(target)) return;
    if (target.closest("[data-file-menu-open]") || target.closest("[data-file-menu-toggle]")) return;
    closeMenu();
  });

  root.querySelectorAll("[data-file-select]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const response = await fetch(`/api/session/active-file/${button.dataset.fileSelect}`, {
          method: "POST",
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          throw new Error(payload.detail || "Не удалось выбрать файл");
        }
        window.location.reload();
      } catch (error) {
        showStatus(error.message, "error");
        button.disabled = false;
      }
    });
  });

  fileInput?.addEventListener("change", () => {
    setSelectedFile(fileInput.files?.[0], "selected");
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
    setSelectedFile(event.dataTransfer?.files?.[0], "dropped");
  });

  document.addEventListener("paste", (event) => {
    if (panel?.classList.contains("hidden")) return;
    const pastedFile = Array.from(event.clipboardData?.files || []).find((file) =>
      file.name.toLowerCase().endsWith(".xlsx"),
    );
    if (!pastedFile) return;
    event.preventDefault();
    setSelectedFile(pastedFile, "pasted");
  });

  uploadForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = selectedFile || fileInput?.files?.[0];
    if (!file) {
      showStatus("Выберите, перетащите или вставьте .xlsx файл", "error");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    setUploading(true);
    showStatus("Файл отправлен. Проверяем структуру на сервере...", "progress");
    try {
      const response = await fetch("/api/files/upload", {
        method: "POST",
        body: formData,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || "Файл не прошёл проверку");
      }
      showStatus("Файл загружен и выбран активным для этой сессии. Обновляем дашборд...", "success");
      window.setTimeout(() => window.location.reload(), 700);
    } catch (error) {
      showStatus(error.message, "error");
      setUploading(false);
    }
  });
}

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

function initFileMenuOpeners() {
  const panel = document.querySelector("[data-file-menu-panel]");
  if (!panel) return;

  const isMenuOpen = () => !panel.classList.contains("hidden");

  const closeMenu = () => {
    panel.classList.add("hidden");
  };

  const openMenu = () => {
    panel.classList.remove("hidden");
    panel.classList.remove("absolute", "right-0", "mt-3");
    panel.classList.add("fixed", "right-4", "top-[4.5rem]", "z-50");
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
  initSortableTables();
  initFileMenu();
  initFileMenuOpeners();
  initSidebar();
});
