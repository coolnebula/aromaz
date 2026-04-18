const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const message = await response.text();
    const err = new Error(message || `HTTP ${response.status}`);
    err.status = response.status;
    throw err;
  }
  return response.json();
}

export const api = {
  checkSession: () => request("/access/session"),
  setupTotp: (setupKey = "", deviceLabel = "browser", userId = "owner") =>
    request("/access/totp/setup", {
      method: "POST",
      body: JSON.stringify({ setup_key: setupKey, device_label: deviceLabel, user_id: userId }),
    }),
  verifyTotp: (code, deviceLabel = "browser", userId = "owner") =>
    request("/access/totp/verify", {
      method: "POST",
      body: JSON.stringify({ code, device_label: deviceLabel, user_id: userId }),
    }),
  logout: () => request("/access/logout", { method: "POST" }),
  getBootstrap: () => request("/bootstrap"),
  getOrder: (orderId) => request(`/orders/${orderId}`),
  deleteOrder: (orderId) => request(`/orders/${orderId}`, { method: "DELETE" }),
  createOrder: (tableId) => request("/orders", { method: "POST", body: JSON.stringify({ table_id: tableId }) }),
  addItem: (orderId, payload) => request(`/orders/${orderId}/items`, { method: "POST", body: JSON.stringify(payload) }),
  updateItem: (orderId, itemIndex, payload) =>
    request(`/orders/${orderId}/items/${itemIndex}`, { method: "PATCH", body: JSON.stringify(payload) }),
  voidItem: (orderId, itemIndex, reason) =>
    request(`/orders/${orderId}/items/${itemIndex}/void`, { method: "POST", body: JSON.stringify({ reason }) }),
  servePending: (orderId) => request(`/orders/${orderId}/serve-pending`, { method: "POST", body: JSON.stringify({}) }),
  updateStatus: (orderId, status, reason = "") =>
    request(`/orders/${orderId}/status`, { method: "POST", body: JSON.stringify({ status, reason }) }),
  applyDiscount: (orderId, amount, managerId, reason) =>
    request(`/orders/${orderId}/discount`, { method: "POST", body: JSON.stringify({ amount, manager_id: managerId, reason }) }),
  sendEbillSms: (orderId, mobile) =>
    request(`/ebill/sms/${orderId}`, { method: "POST", body: JSON.stringify({ mobile }) }),
  sendEbillEmail: (orderId, email) =>
    request(`/ebill/email/${orderId}`, { method: "POST", body: JSON.stringify({ email }) }),
  syncBatch: (mutations) => request("/sync/batch", { method: "POST", body: JSON.stringify({ mutations }) }),
  summaryRange: (fromDate, toDate) =>
    request(`/reports/end-of-day?from_date=${encodeURIComponent(fromDate)}&to_date=${encodeURIComponent(toDate)}`),
  historyRange: (fromDate, toDate) =>
    request(`/reports/history?from_date=${encodeURIComponent(fromDate)}&to_date=${encodeURIComponent(toDate)}`),
  dashboardRange: (fromDate, toDate, mode = "deterministic", hourScope = "all", llmModel = "") =>
    request(
      `/reports/dashboard-html?from_date=${encodeURIComponent(fromDate)}&to_date=${encodeURIComponent(toDate)}&mode=${encodeURIComponent(mode)}&hour_scope=${encodeURIComponent(hourScope)}&llm_model=${encodeURIComponent(llmModel)}`
    ),
  dashboardStreamPath: (fromDate, toDate, mode = "llm", hourScope = "operating", llmModel = "") =>
    `${API_BASE}/reports/dashboard-stream?from_date=${encodeURIComponent(fromDate)}&to_date=${encodeURIComponent(toDate)}&mode=${encodeURIComponent(mode)}&hour_scope=${encodeURIComponent(hourScope)}&llm_model=${encodeURIComponent(llmModel)}`,
  listMenuCategories: () => request("/menu/categories"),
  createMenuCategory: (payload) => request("/menu/categories", { method: "POST", body: JSON.stringify(payload) }),
  updateMenuCategory: (categoryId, payload) =>
    request(`/menu/categories/${categoryId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteMenuCategory: (categoryId, moveToCategoryId = "") => {
    const suffix = moveToCategoryId ? `?move_to_category_id=${encodeURIComponent(moveToCategoryId)}` : "";
    return request(`/menu/categories/${categoryId}${suffix}`, { method: "DELETE" });
  },
  listMenuItemsAdmin: (options = {}) => {
    const params = new URLSearchParams();
    if (Object.prototype.hasOwnProperty.call(options, "includeInactive")) {
      params.set("include_inactive", String(Boolean(options.includeInactive)));
    }
    if (options.query) params.set("query", options.query);
    if (options.category) params.set("category", options.category);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request(`/menu/items${suffix}`);
  },
  createMenuItemAdmin: (payload) => request("/menu/items", { method: "POST", body: JSON.stringify(payload) }),
  updateMenuItemAdmin: (itemId, payload) =>
    request(`/menu/items/${itemId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteMenuItemAdmin: (itemId) => request(`/menu/items/${itemId}`, { method: "DELETE" }),
};
