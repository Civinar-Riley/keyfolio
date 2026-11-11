/** API 封装：401 时广播事件回到登录页。 */

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  let data = null;
  try { data = await resp.json(); } catch { data = {}; }
  if (resp.status === 401) {
    // 登录/解锁类接口的 401 是"密码错误"，不是会话失效
    if (!path.startsWith("/api/auth/")) {
      window.dispatchEvent(new CustomEvent("kf:unauthorized"));
    }
    throw new Error(data.detail || "未登录");
  }
  if (resp.status === 423 && !path.startsWith("/api/auth/")) {
    window.dispatchEvent(new CustomEvent("kf:locked"));
    throw new Error(data.detail || "已锁定，请先解锁");
  }
  if (!resp.ok) {
    const detail = data.detail;
    const msg = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map(d => d.msg || JSON.stringify(d)).join("; ")
        : `请求失败 (${resp.status})`;
    throw new Error(msg);
  }
  return data;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b) => request("POST", p, b ?? {}),
  put: (p, b) => request("PUT", p, b),
  del: (p) => request("DELETE", p),
};

export function fmtTime(ts) {
  if (!ts) return "—";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;
  return date.toLocaleString(undefined, {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

export function fmtBalance(k) {
  if (k.balance === null || k.balance === undefined) return "—";
  const n = Number(k.balance);
  const v = Number.isNaN(n)
    ? String(k.balance)
    : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${v} ${k.currency || ""}`;
}

export function expiryInfo(value) {
  if (!value) return null;
  const text = String(value).trim();
  const date = new Date(text.length === 10 ? text + "T23:59:59" : text);
  if (Number.isNaN(date.getTime())) return { text, cls: "" };
  const days = Math.ceil((date.getTime() - Date.now()) / 86400000);
  if (days < 0) return { text: `已过期 ${text}`, cls: "fail" };
  if (days <= 7) return { text: `${days} 天后到期`, cls: "warn" };
  return { text: `到期 ${text}`, cls: "" };
}

export async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // 局域网 HTTP 没有 Clipboard API，退回 textarea + execCommand
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  const ok = document.execCommand("copy");
  document.body.removeChild(area);
  if (!ok) throw new Error("复制失败，请手动选择文本");
}
