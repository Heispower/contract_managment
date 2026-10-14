(function () {
  document.querySelectorAll(".nav-parent").forEach(function (button) {
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      const group = button.parentElement;
      const open = group.classList.contains("open");
      document.querySelectorAll(".nav-group.open").forEach(function (item) {
        if (item !== group) item.classList.remove("open");
      });
      group.classList.toggle("open", !open);
      button.setAttribute("aria-expanded", open ? "false" : "true");
    });
  });
  document.addEventListener("click", function () {
    document.querySelectorAll(".nav-group.open").forEach(function (item) {
      item.classList.remove("open");
      const button = item.querySelector(".nav-parent");
      if (button) button.setAttribute("aria-expanded", "false");
    });
  });

  document.querySelectorAll(".expand-btn").forEach(function (button) {
    button.addEventListener("click", function () {
      const panel = document.getElementById(button.getAttribute("data-expand"));
      if (!panel) return;
      panel.classList.toggle("open");
      button.textContent = panel.classList.contains("open") ? "收起" : "展开";
    });
  });

  document.querySelectorAll(".table-card table").forEach(function (table) {
    const heads = Array.from(table.querySelectorAll("thead th"));
    if (!heads.length) return;
    const storageKey = "colw:" + location.pathname + ":" + heads.map(function (th, index) {
      return th.getAttribute("data-col") || ("c" + index);
    }).join("|");
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch (err) { saved = {}; }
    heads.forEach(function (th, index) {
      if (!th.getAttribute("data-col")) th.setAttribute("data-col", "c" + index);
      if (th.classList.contains("check")) return;
      const handle = document.createElement("span");
      handle.className = "col-resizer";
      handle.title = "拖动调整列宽";
      th.appendChild(handle);
    });
    const natural = heads.map(function (th) {
      return Math.max(48, Math.round(th.getBoundingClientRect().width));
    });
    let sum = 0;
    heads.forEach(function (th, index) {
      const width = saved[th.getAttribute("data-col")] || natural[index];
      th.style.width = width + "px";
      sum += width;
    });
    table.style.tableLayout = "fixed";
    table.style.width = sum + "px";

    function syncWidth() {
      let total = 0;
      heads.forEach(function (th) {
        total += parseFloat(th.style.width) || th.getBoundingClientRect().width;
      });
      table.style.width = Math.ceil(total) + "px";
    }

    heads.forEach(function (th) {
      const handle = th.querySelector(".col-resizer");
      if (!handle) return;
      handle.addEventListener("mousedown", function (event) {
        event.preventDefault();
        event.stopPropagation();
        const startX = event.clientX;
        const startW = parseFloat(th.style.width) || th.getBoundingClientRect().width;
        const fromLeft = th.classList.contains("ops");
        handle.classList.add("active");
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        function move(ev) {
          const delta = fromLeft ? startX - ev.clientX : ev.clientX - startX;
          const min = th.classList.contains("ops") ? 120 : 64;
          th.style.width = Math.max(min, Math.round(startW + delta)) + "px";
          syncWidth();
        }
        function up() {
          document.removeEventListener("mousemove", move);
          document.removeEventListener("mouseup", up);
          handle.classList.remove("active");
          document.body.style.cursor = "";
          document.body.style.userSelect = "";
          saved[th.getAttribute("data-col")] = Math.round(parseFloat(th.style.width));
          localStorage.setItem(storageKey, JSON.stringify(saved));
        }
        document.addEventListener("mousemove", move);
        document.addEventListener("mouseup", up);
      });
    });
  });

  document.querySelectorAll(".check-all").forEach(function (box) {
    box.addEventListener("change", function () {
      const table = box.closest("table");
      table.querySelectorAll(".row-check").forEach(function (item) {
        item.checked = box.checked;
      });
    });
  });

  const mask = document.getElementById("confirm-mask");
  const form = document.getElementById("confirm-form");
  const text = document.getElementById("confirm-text");
  const ids = document.getElementById("confirm-ids");
  if (!mask || !form) return;

  function openConfirm(action, message) {
    form.action = action;
    text.textContent = message;
    ids.innerHTML = "";
    mask.hidden = false;
  }

  document.querySelectorAll(".js-delete").forEach(function (button) {
    button.addEventListener("click", function () {
      openConfirm(button.getAttribute("data-action"), button.getAttribute("data-message"));
    });
  });

  document.querySelectorAll(".js-batch-delete").forEach(function (button) {
    button.addEventListener("click", function () {
      const checked = Array.from(document.querySelectorAll(".row-check:checked"));
      if (!checked.length) {
        window.alert("请先选择数据");
        return;
      }
      openConfirm(button.getAttribute("data-action"), button.getAttribute("data-message"));
      checked.forEach(function (item) {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "ids";
        input.value = item.value;
        ids.appendChild(input);
      });
    });
  });

  document.getElementById("confirm-cancel").addEventListener("click", function () {
    mask.hidden = true;
  });
  mask.addEventListener("click", function (event) {
    if (event.target === mask) mask.hidden = true;
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") mask.hidden = true;
  });
})();
