import axios from "axios";
import { ElMessage, ElMessageBox } from "element-plus";

const http = axios.create({ baseURL: "" });

http.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  const company = localStorage.getItem("company_id");
  if (company) config.headers["X-Company-Id"] = company;
  return config;
});

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

function detailText(detail) {
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object") {
          const loc = (item.loc || []).filter((part) => part !== "body" && part !== "query").join(".");
          const msg = String(item.msg || "").trim();
          return loc && msg ? `${loc}：${msg}` : msg || loc;
        }
        return String(item || "").trim();
      })
      .filter(Boolean)
      .join("；");
  }
  if (typeof detail === "string") return detail.trim();
  return "";
}

function pickMessage(body, error) {
  if (body && typeof body === "object") {
    const message = typeof body.message === "string" ? body.message.trim() : "";
    if (message) return message;
    const detail = detailText(body.detail);
    if (detail && detail !== "Internal Server Error") return detail;
  }
  if (typeof body === "string") {
    const text = body.trim();
    if (text && !text.startsWith("<")) return text.slice(0, 500);
  }
  const status = error?.response?.status;
  if (status) return `请求失败（${status}）`;
  if (error?.message) return error.message;
  return "请求失败";
}

let errorOpen = false;

function showError(body, error) {
  const message = pickMessage(body, error);
  const refs = Array.isArray(body?.data?.refs) ? body.data.refs : [];
  if (errorOpen) return;
  errorOpen = true;
  const list = refs.map((item) => `<div>${escapeHtml(item)}</div>`).join("");
  const html = `<div class="err-detail">${escapeHtml(message)}</div>${list ? `<div class="ref-list">${list}</div>` : ""}`;
  ElMessageBox.alert(html, "提示", {
    type: refs.length || message === "后续已生成单据，无法删除。" ? "warning" : "error",
    confirmButtonText: "确定",
    dangerouslyUseHTMLString: true,
    closeOnClickModal: false,
    closeOnPressEscape: false,
    customClass: refs.length ? "ref-alert" : "err-alert",
  }).catch(() => {}).finally(() => {
    errorOpen = false;
  });
}

http.interceptors.response.use(
  (res) => {
    if (res.config.responseType === "blob") return res;
    const body = res.data;
    if (body && typeof body.code === "number" && body.code !== 0) {
      showError(body);
      return Promise.reject(body);
    }
    return body;
  },
  async (error) => {
    let body = error.response?.data;
    if (typeof Blob !== "undefined" && body instanceof Blob) {
      try {
        body = JSON.parse(await body.text());
      } catch {
        body = null;
      }
    }
    if (error.response?.status === 401) {
      localStorage.removeItem("token");
      if (!location.hash.includes("/login")) location.hash = "#/login";
    }
    showError(body, error);
    return Promise.reject(body || error);
  }
);

export async function batchDelete(shell, rows, url) {
  const set = shell?.selected || new Set();
  const picked = [];
  const seen = new Set();
  for (const row of rows || []) {
    const key = row.id || `${row.order_id}-${row.material_code}`;
    if (!set.has(key)) continue;
    const id = row.order_id || row.id;
    if (id == null || seen.has(id)) continue;
    seen.add(id);
    picked.push({ id, version: row.version });
  }
  if (!picked.length) {
    ElMessage.warning("请先勾选要删除的记录");
    return false;
  }
  await ElMessageBox.confirm(`确定删除选中的 ${picked.length} 条？`, "批量删除", { type: "warning" });
  await http.post(url, { items: picked });
  ElMessage.success("已删除");
  return true;
}

export function money(value) {
  const num = Number(value || 0);
  return num.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export async function downloadBlob(url, fallback, { method = "get", params, data } = {}) {
  const res = await http.request({ url, method, params, data, responseType: "blob" });
  const blob = res.data;
  const header = res.headers["content-disposition"] || "";
  const star = header.match(/filename\*=UTF-8''([^;]+)/i);
  const plain = header.match(/filename="?([^";]+)"?/i);
  const name = decodeURIComponent(star?.[1] || plain?.[1] || fallback || "下载");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.click();
  URL.revokeObjectURL(link.href);
}

export async function downloadExport(module, payload, fallback) {
  const res = await http.post(`/api/export/${module}`, payload || {}, { responseType: "blob" });
  const blob = res.data;
  const header = res.headers["content-disposition"] || "";
  const star = header.match(/filename\*=UTF-8''([^;]+)/i);
  const plain = header.match(/filename="?([^";]+)"?/i);
  const name = decodeURIComponent(star?.[1] || plain?.[1] || fallback || "导出.xlsx");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.click();
  URL.revokeObjectURL(link.href);
}

export default http;
