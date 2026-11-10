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
    window.dispatchEvent(new CustomEvent("kf:unauthorized"));
    throw new Error(data.detail || "未登录");
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
  return ts.replace("T", " ").replace("Z", "").replace(" UTC", "");
}

export function fmtBalance(k) {
  if (k.balance === null || k.balance === undefined) return "—";
  return `${k.balance} ${k.currency || ""}`;
}
