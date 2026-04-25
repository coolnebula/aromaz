import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "./api";
import { deleteQueuedMutations, enqueueMutation, getQueuedMutations } from "./offlineQueue";

const STATUS_PIPELINE = ["Open", "Served", "Billed", "Paid"];
const CACHE_KEY = "aromaz-pos-cache-v1";
/** API requires a manager_id starting with "manager-"; no prompt in UI — this default satisfies the check. */
const DEFAULT_DISCOUNT_MANAGER_ID = "manager-demo";
const LLM_MODEL_OPTIONS = [
  {
    value: "gemini-3.1-flash-lite",
    label: "Gemini 3.1 Flash Lite",
    availability: "500/day | 15 RPM | 250K TPM",
    availability_tone: "high",
  },
  {
    value: "gemini-3-flash",
    label: "Gemini 3 Flash",
    availability: "20/day | 5 RPM | 250K TPM",
    availability_tone: "medium",
  },
  {
    value: "gemini-2.5-flash",
    label: "Gemini 2.5 Flash",
    availability: "20/day | 5 RPM | 250K TPM",
    availability_tone: "medium",
  },
  {
    value: "gemma-4-31b",
    label: "Gemma 4 31B",
    availability: "1.5K/day | 15 RPM | Unlimited TPM",
    availability_tone: "high",
  },
  {
    value: "gemma-4-26b",
    label: "Gemma 4 26B",
    availability: "1.5K/day | 15 RPM | Unlimited TPM",
    availability_tone: "high",
  },
];

function mutation(action, payload) {
  return {
    mutation_id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    action,
    payload,
    actor_id: "cashier-demo",
    created_at: new Date().toISOString(),
  };
}

export default function App() {
  const [tables, setTables] = useState([]);
  const [menu, setMenu] = useState({});
  const [selectedTable, setSelectedTable] = useState("T1");
  const [selectedCategory, setSelectedCategory] = useState("");
  const [orderByTable, setOrderByTable] = useState({});
  const [syncState, setSyncState] = useState({ online: navigator.onLine, pending: 0 });
  const [rangeFrom, setRangeFrom] = useState(new Date().toISOString().slice(0, 10));
  const [rangeTo, setRangeTo] = useState(new Date().toISOString().slice(0, 10));
  const [historyDate, setHistoryDate] = useState(new Date().toISOString().slice(0, 10));
  const [summaryData, setSummaryData] = useState(null);
  const [historyData, setHistoryData] = useState([]);
  const [aiDashboardData, setAiDashboardData] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [aiDashboardLoading, setAiDashboardLoading] = useState(false);
  const [aiExpectedCharts, setAiExpectedCharts] = useState(0);
  const [aiActionSort, setAiActionSort] = useState("impact");
  const [aiHourScope, setAiHourScope] = useState("operating");
  const [aiLlmModel, setAiLlmModel] = useState("gemini-3.1-flash-lite");
  const [summaryRangeError, setSummaryRangeError] = useState("");
  const [aiDashboardError, setAiDashboardError] = useState("");
  const [aiDashboardMode, setAiDashboardMode] = useState("deterministic");
  const [mainTab, setMainTab] = useState("dashboard");
  const [reportsTab, setReportsTab] = useState("summary");
  const [menuAdminLoading, setMenuAdminLoading] = useState(false);
  const [menuAdminCategories, setMenuAdminCategories] = useState([]);
  const [menuAdminItems, setMenuAdminItems] = useState([]);
  const [menuSearch, setMenuSearch] = useState("");
  const [menuCategoryFilter, setMenuCategoryFilter] = useState("");
  const [menuIncludeInactive, setMenuIncludeInactive] = useState(true);
  const [newCategoryName, setNewCategoryName] = useState("");
  const [newItemName, setNewItemName] = useState("");
  const [newItemPrice, setNewItemPrice] = useState("");
  const [newItemCategoryId, setNewItemCategoryId] = useState("");
  const [taxRatePercent, setTaxRatePercent] = useState(5);
  const [taxRateInput, setTaxRateInput] = useState("5");
  const [taxRateSaving, setTaxRateSaving] = useState(false);
  const [error, setError] = useState("");
  const lastModalTriggerRef = useRef(null);
  const billCloseBtnRef = useRef(null);
  const aiDashboardStreamRef = useRef(null);
  const [billPreview, setBillPreview] = useState({
    open: false,
    generatedAt: "",
    email: "",
    sending: false,
    status: "",
    order: null,
  });
  const [billDiscountBusy, setBillDiscountBusy] = useState(false);
  const [auth, setAuth] = useState({
    loading: true,
    authenticated: false,
    configured: false,
    codeInput: "",
    info: "",
    setupKeyInput: "",
    userIdInput: "owner",
    provisioningUri: "",
    qrDataUrl: "",
    devSecret: "",
  });

  const activeOrder = orderByTable[selectedTable];
  const categories = Object.keys(menu);
  const items = menu[selectedCategory] || [];

  useEffect(() => {
    hydrateFromCache();
    initializeSession();
    const handleOnline = () => setSyncState((s) => ({ ...s, online: true }));
    const handleOffline = () => setSyncState((s) => ({ ...s, online: false }));
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  useEffect(() => {
    const aiDashboardCache = aiDashboardData
      ? {
          mode: aiDashboardData.mode,
          model: aiDashboardData.model,
          from_date: aiDashboardData.from_date,
          to_date: aiDashboardData.to_date,
          diagnostics: aiDashboardData.diagnostics,
          token_usage: aiDashboardData.token_usage,
          estimated_cost: aiDashboardData.estimated_cost,
          key_insights: aiDashboardData.key_insights,
          drilldown_suggestion: aiDashboardData.drilldown_suggestion,
          recommendations: aiDashboardData.recommendations,
          executive_summary: aiDashboardData.executive_summary,
          root_cause_hypotheses: aiDashboardData.root_cause_hypotheses,
          prioritized_actions: aiDashboardData.prioritized_actions,
          watchouts: aiDashboardData.watchouts,
          quality_flags: aiDashboardData.quality_flags,
          observability: aiDashboardData.observability,
          analytics_monthly: aiDashboardData.analytics_monthly,
          analytics_summary: aiDashboardData.analytics_summary,
          analytics_diagnostics: aiDashboardData.analytics_diagnostics,
          analytics_operating_context: aiDashboardData.analytics_operating_context,
          hour_scope: aiDashboardData.hour_scope || aiHourScope,
          selected_llm_model: aiDashboardData.selected_llm_model || aiLlmModel,
        }
      : null;
    const snapshot = {
      tables,
      menu,
      selectedTable,
      selectedCategory,
      orderByTable,
      rangeFrom,
      rangeTo,
      historyDate,
      mainTab,
      reportsTab,
      aiHourScope,
      aiLlmModel,
      menuSearch,
      menuCategoryFilter,
      menuIncludeInactive,
      taxRatePercent,
      taxRateInput,
      summaryData,
      historyData,
      aiDashboardData: aiDashboardCache,
    };
    localStorage.setItem(CACHE_KEY, JSON.stringify(snapshot));
  }, [
    tables,
    menu,
    selectedTable,
    selectedCategory,
    orderByTable,
    rangeFrom,
    rangeTo,
    historyDate,
    mainTab,
    reportsTab,
    aiHourScope,
    aiLlmModel,
    menuSearch,
    menuCategoryFilter,
    menuIncludeInactive,
    taxRatePercent,
    taxRateInput,
    summaryData,
    historyData,
    aiDashboardData,
  ]);

  useEffect(() => {
    if (syncState.online) {
      syncPending();
    }
  }, [syncState.online, auth.authenticated]);

  useEffect(() => {
    if (!auth.authenticated || mainTab !== "reports" || reportsTab !== "history" || !historyDate) return;
    loadHistory(historyDate, historyDate);
  }, [auth.authenticated, historyDate, mainTab, reportsTab]);

  useEffect(() => {
    if (!auth.authenticated || mainTab !== "reports" || reportsTab !== "summary" || !rangeFrom || !rangeTo) return;
    loadSummary();
  }, [auth.authenticated, rangeFrom, rangeTo, mainTab, reportsTab]);

  useEffect(() => {
    if (!auth.authenticated || mainTab !== "reports" || reportsTab !== "ai-dashboard" || !rangeFrom || !rangeTo) return;
    loadAiDashboard();
  }, [auth.authenticated, rangeFrom, rangeTo, mainTab, reportsTab, aiDashboardMode, aiHourScope, aiLlmModel]);

  useEffect(() => {
    return () => {
      if (aiDashboardStreamRef.current) {
        aiDashboardStreamRef.current.close();
        aiDashboardStreamRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!auth.authenticated || mainTab !== "menu-management") return;
    loadMenuManagementData();
  }, [auth.authenticated, mainTab, menuIncludeInactive]);

  useEffect(() => {
    if (!billPreview.open) return undefined;

    const clearPrintMode = () => document.body.classList.remove("bill-print-mode");
    const handleKeydown = (event) => {
      if (event.key === "Escape") {
        closeItemizedBill();
      }
    };
    document.body.classList.add("modal-open");
    window.requestAnimationFrame(() => {
      billCloseBtnRef.current?.focus();
    });
    window.addEventListener("afterprint", clearPrintMode);
    window.addEventListener("keydown", handleKeydown);
    return () => {
      window.removeEventListener("afterprint", clearPrintMode);
      window.removeEventListener("keydown", handleKeydown);
      document.body.classList.remove("modal-open");
      clearPrintMode();
    };
  }, [billPreview.open]);

  async function refreshPending() {
    const queued = await getQueuedMutations();
    setSyncState((s) => ({ ...s, pending: queued.length }));
  }

  async function bootstrap() {
    try {
      const data = await api.getBootstrap();
      setTables(data.tables);
      setMenu(data.menu);
      const tr =
        typeof data.tax_rate_percent === "number" && Number.isFinite(data.tax_rate_percent)
          ? data.tax_rate_percent
          : 5;
      setTaxRatePercent(tr);
      setTaxRateInput(String(tr));
      setOrderByTable((prev) => {
        const serverActive = data.active_orders || {};
        const normalizedServerActive = Object.fromEntries(
          Object.entries(serverActive).map(([tableId, order]) => [tableId, normalizeOrder(order)])
        );
        const localOnly = Object.fromEntries(
          Object.entries(prev).filter(([, order]) => String(order?.id || "").startsWith("local-"))
        );
        return { ...normalizedServerActive, ...localOnly };
      });
      const first = Object.keys(data.menu)[0] || "";
      setSelectedCategory((prev) => prev || first);
      setError("");
    } catch (err) {
      if (err.status === 401) {
        setAuth((a) => ({ ...a, authenticated: false, loading: false }));
        return;
      }
      setError("API unavailable. Running with local fallback data.");
      setTables([{ table_id: "T1" }, { table_id: "T2" }, { table_id: "T3" }, { table_id: "T4" }]);
      setMenu({
        "Coffee & Chocolates": [{ name: "Espresso", price: 75 }, { name: "Iced Coffee", price: 125 }],
        "Tea & Infusions": [{ name: "Darjeeling Tea", price: 80 }],
      });
      setSelectedCategory("Coffee & Chocolates");
    }
  }

  async function initializeSession() {
    await refreshPending();
    try {
      const session = await api.checkSession();
      if (session.authenticated) {
        setAuth((a) => ({
          ...a,
          loading: false,
          authenticated: true,
          configured: Boolean(session.totp_configured),
          userIdInput: session.user_id || a.userIdInput,
          info: "",
        }));
        await bootstrap();
      } else {
        setAuth((a) => ({
          ...a,
          loading: false,
          authenticated: false,
          configured: Boolean(session.totp_configured),
          userIdInput: session.user_id || a.userIdInput,
          info: session.totp_configured
            ? "Enter authenticator code to continue."
            : "Set up authenticator app first.",
        }));
      }
    } catch {
      setAuth((a) => ({ ...a, loading: false, authenticated: false, info: "Backend unavailable." }));
    }
  }

  async function setupAuthenticator() {
    try {
      const data = await api.setupTotp(auth.setupKeyInput, "browser", auth.userIdInput || "owner");
      setAuth((a) => ({
        ...a,
        configured: Boolean(data.configured),
        provisioningUri: data.provisioning_uri || "",
        qrDataUrl: data.qr_data_url || "",
        devSecret: data.secret || "",
        info: data.configured
          ? `Authenticator already configured for '${data.user_id || a.userIdInput}'. Enter your app code.`
          : `Scan URI for '${data.user_id || a.userIdInput}' in authenticator app (or use secret in development), then verify code.`,
      }));
    } catch (err) {
      setAuth((a) => ({ ...a, info: err.message || "Failed to request code." }));
    }
  }

  async function verifyAuthenticatorCode() {
    try {
      await api.verifyTotp(auth.codeInput, "browser", auth.userIdInput || "owner");
      setAuth((a) => ({
        ...a,
        authenticated: true,
        configured: true,
        info: "",
        codeInput: "",
        provisioningUri: "",
        qrDataUrl: "",
        devSecret: "",
      }));
      await bootstrap();
    } catch (err) {
      setAuth((a) => ({ ...a, info: err.message || "Invalid code." }));
    }
  }

  function hydrateFromCache() {
    try {
      const raw = localStorage.getItem(CACHE_KEY);
      if (!raw) return;
      const today = new Date().toISOString().slice(0, 10);
      const cached = JSON.parse(raw);
      if (cached.tables) setTables(cached.tables);
      if (cached.menu) setMenu(cached.menu);
      if (cached.selectedTable) setSelectedTable(cached.selectedTable);
      if (cached.selectedCategory) setSelectedCategory(cached.selectedCategory);
      if (cached.orderByTable) {
        const cleaned = Object.fromEntries(
          Object.entries(cached.orderByTable)
            .filter(([, order]) => !["Paid", "Cancelled"].includes(order?.status))
            .map(([tableId, order]) => [tableId, normalizeOrder(order)])
        );
        setOrderByTable(cleaned);
      }
      if (cached.rangeFrom) {
        setRangeFrom(cached.rangeFrom > today ? today : cached.rangeFrom);
      }
      // Always reset report "to date" to current date on reload.
      setRangeTo(today);
      // Day-wise report should default to today's date on reload.
      setHistoryDate(today);
      if (cached.mainTab) setMainTab(cached.mainTab);
      if (cached.reportsTab) setReportsTab(cached.reportsTab);
      if (cached.aiHourScope === "all" || cached.aiHourScope === "operating") {
        setAiHourScope(cached.aiHourScope);
      }
      if (typeof cached.aiLlmModel === "string" && cached.aiLlmModel.trim()) {
        setAiLlmModel(cached.aiLlmModel.trim());
      }
      if (cached.menuSearch) setMenuSearch(cached.menuSearch);
      if (cached.menuCategoryFilter) setMenuCategoryFilter(cached.menuCategoryFilter);
      if (Object.prototype.hasOwnProperty.call(cached, "menuIncludeInactive")) {
        setMenuIncludeInactive(Boolean(cached.menuIncludeInactive));
      }
      if (typeof cached.taxRatePercent === "number" && Number.isFinite(cached.taxRatePercent)) {
        setTaxRatePercent(cached.taxRatePercent);
      }
      if (typeof cached.taxRateInput === "string" && cached.taxRateInput.trim()) {
        setTaxRateInput(cached.taxRateInput.trim());
      } else if (typeof cached.taxRatePercent === "number" && Number.isFinite(cached.taxRatePercent)) {
        setTaxRateInput(String(cached.taxRatePercent));
      }
      if (cached.summaryData) setSummaryData(cached.summaryData);
      if (cached.historyData) setHistoryData(cached.historyData);
      if (cached.aiDashboardData) setAiDashboardData(cached.aiDashboardData);
    } catch {
      // Ignore invalid cache snapshots.
    }
  }

  async function ensureOrder(tableId) {
    const existing = orderByTable[tableId];
    if (existing?.id && !["Paid", "Cancelled"].includes(existing.status)) {
      return existing;
    }
    try {
      const created = await api.createOrder(tableId);
      setOrderByTable((prev) => ({
        ...prev,
        [tableId]: { id: created.id, status: "Open", items: [], totals: created.totals || { total: 0 } },
      }));
      return { id: created.id, status: "Open", items: [], totals: created.totals || { total: 0 } };
    } catch {
      const local = {
        id: `local-${tableId}`,
        status: "Open",
        items: [],
        totals: { subtotal: 0, discount: 0, tax: 0, total: 0 },
      };
      setOrderByTable((prev) => ({ ...prev, [tableId]: local }));
      await enqueueMutation(mutation("CREATE_ORDER", { tableId, clientOrderId: local.id }));
      refreshPending();
      return local;
    }
  }

  async function addItem(item) {
    const current = await ensureOrder(selectedTable);
    const payload = {
      name: item.name,
      price: item.price,
      qty: 1,
      modifiers: { less_sugar: false, no_ice: false, note: "" },
    };
    const localItem = { ...payload, served: false, served_qty: 0, served_at: null };
    if (!syncState.online || current.id.startsWith("local-")) {
      const m = mutation("ADD_ITEM", { tableId: selectedTable, orderId: current.id, ...payload });
      await enqueueMutation(m);
      setOrderByTable((prev) => {
        const base = prev[selectedTable] || current;
        const nextItems = [...(base.items || []), localItem];
        return {
          ...prev,
          [selectedTable]: {
            ...base,
            items: nextItems,
            totals: calcTotals(nextItems, base.totals?.discount || 0, taxRatePercent),
          },
        };
      });
      refreshPending();
      return;
    }
    try {
      const updated = await api.addItem(current.id, payload);
      setOrderByTable((prev) => ({ ...prev, [selectedTable]: normalizeOrder(updated) }));
      setError("");
    } catch (err) {
      setError(err.message || "Unable to add item.");
    }
  }

  async function moveStatus() {
    const current = activeOrder;
    if (!current) return;
    const idx = STATUS_PIPELINE.indexOf(current.status);
    if (idx < 0 || idx >= STATUS_PIPELINE.length - 1) return;
    const next = STATUS_PIPELINE[idx + 1];
    if (next === "Billed" && pendingServeCount > 0) {
      setError("Serve all pending items before moving this order to billed.");
      return;
    }
    if (!syncState.online || current.id.startsWith("local-")) {
      const m = mutation("STATUS_UPDATE", { orderId: current.id, tableId: selectedTable, status: next });
      await enqueueMutation(m);
      if (next === "Paid") {
        setOrderByTable((prev) => {
          const { [selectedTable]: _closed, ...rest } = prev;
          return rest;
        });
      } else {
        setOrderByTable((prev) => {
          const nowIso = new Date().toISOString();
          const nextItems =
            next === "Served"
              ? (current.items || []).map((line) => {
                  if (line.voided || pendingQtyForItem(line) <= 0) return line;
                  return { ...line, served: true, served_qty: Number(line.qty || 1), served_at: nowIso };
                })
              : current.items || [];
          return { ...prev, [selectedTable]: { ...current, status: next, items: nextItems } };
        });
      }
      refreshPending();
      return;
    }
    try {
      const updated = await api.updateStatus(current.id, next);
      if (next === "Paid") {
        setOrderByTable((prev) => {
          const { [selectedTable]: _closed, ...rest } = prev;
          return rest;
        });
      } else {
        setOrderByTable((prev) => ({ ...prev, [selectedTable]: normalizeOrder(updated) }));
      }
      setError("");
    } catch (err) {
      setError(err.message || "Unable to update order status.");
    }
  }

  async function servePendingItems() {
    const current = activeOrder;
    if (!current || current.status !== "Served") return;
    if (pendingServeCount <= 0) return;
    const servedAt = new Date().toISOString();

    if (!syncState.online || current.id.startsWith("local-")) {
      await enqueueMutation(
        mutation("SERVE_PENDING_ITEMS", {
          orderId: current.id,
          tableId: selectedTable,
        })
      );
      setOrderByTable((prev) => {
        const base = prev[selectedTable];
        if (!base) return prev;
        const nextItems = (base.items || []).map((line) => {
          if (line.voided || pendingQtyForItem(line) <= 0) return line;
          return { ...line, served: true, served_qty: Number(line.qty || 1), served_at: servedAt };
        });
        return { ...prev, [selectedTable]: { ...base, items: nextItems } };
      });
      setError("");
      refreshPending();
      return;
    }

    try {
      const updated = await api.servePending(current.id);
      setOrderByTable((prev) => ({ ...prev, [selectedTable]: normalizeOrder(updated) }));
      setError("");
    } catch (err) {
      setError(err.message || "Unable to serve newly added items.");
    }
  }

  async function syncPending() {
    if (!auth.authenticated) return;
    const queued = await getQueuedMutations();
    if (!queued.length) return;
    try {
      const result = await api.syncBatch(queued);
      const clearIds = [...(result.accepted_ids || []), ...(result.duplicate_ids || [])];
      await deleteQueuedMutations(clearIds);
      await refreshPending();
      if ((result.failed || 0) > 0) {
        setError(`${result.failed} queued mutation(s) need attention and were not applied.`);
      } else {
        setError("");
      }
      await bootstrap();
    } catch {
      // Keep local queue when backend is still unavailable.
    }
  }

  async function loadSummary() {
    if (!rangeFrom || !rangeTo) return;
    if (rangeFrom > rangeTo) {
      setSummaryRangeError("From date cannot be after To date.");
      return;
    }
    setSummaryRangeError("");
    setSummaryLoading(true);
    try {
      const data = await api.summaryRange(rangeFrom, rangeTo);
      setSummaryData(data);
    } catch {
      setSummaryData({ date: `${rangeFrom}..${rangeTo}`, summary: {} });
    } finally {
      setSummaryLoading(false);
    }
  }

  async function loadHistory(fromDate = historyDate, toDate = historyDate) {
    if (!fromDate || !toDate) return;
    setHistoryLoading(true);
    try {
      const data = await api.historyRange(fromDate, toDate);
      setHistoryData(data.orders || []);
    } catch {
      setHistoryData([]);
    } finally {
      setHistoryLoading(false);
    }
  }

  async function loadAiDashboard() {
    if (!rangeFrom || !rangeTo) return;
    if (rangeFrom > rangeTo) {
      setAiDashboardError("From date cannot be after To date.");
      return;
    }
    if (aiDashboardStreamRef.current) {
      aiDashboardStreamRef.current.close();
      aiDashboardStreamRef.current = null;
    }
    setAiDashboardError("");
    setAiDashboardLoading(true);
    setAiExpectedCharts(0);
    try {
      if (aiDashboardMode === "llm") {
        await streamAiDashboard();
        return;
      }
      const data = await api.dashboardRange(rangeFrom, rangeTo, aiDashboardMode, "all", "");
      setAiDashboardData(data);
    } catch (err) {
      setAiDashboardData(null);
      setAiDashboardError(err.message || "Unable to generate report dashboard.");
    } finally {
      setAiDashboardLoading(false);
    }
  }

  async function streamAiDashboard() {
    const url = api.dashboardStreamPath(rangeFrom, rangeTo, "llm", aiHourScope, aiLlmModel);
    const base = {
      mode: "llm",
      model: "",
      from_date: rangeFrom,
      to_date: rangeTo,
      diagnostics: [],
      token_usage: {},
      estimated_cost: {},
      key_insights: [],
      drilldown_suggestion: null,
      recommendations: [],
      executive_summary: "",
      root_cause_hypotheses: [],
      prioritized_actions: [],
      watchouts: [],
      quality_flags: {},
      observability: {},
      blocks: [],
      analytics_monthly: [],
      analytics_summary: {},
      analytics_diagnostics: {},
      analytics_operating_context: {},
      hour_scope: aiHourScope,
      selected_llm_model: aiLlmModel,
    };
    setAiDashboardData(base);

    await new Promise((resolve, reject) => {
      let completed = false;
      const stream = new EventSource(url, { withCredentials: true });
      aiDashboardStreamRef.current = stream;

      const close = () => {
        stream.close();
        if (aiDashboardStreamRef.current === stream) {
          aiDashboardStreamRef.current = null;
        }
      };

      const parse = (event) => {
        try {
          return JSON.parse(event.data || "{}");
        } catch {
          return {};
        }
      };

      stream.addEventListener("meta", (event) => {
        const payload = parse(event);
        setAiDashboardData((prev) => ({
          ...(prev || base),
          ...payload,
        }));
        if (payload.expected_charts) {
          setAiExpectedCharts(Number(payload.expected_charts) || 0);
        }
      });

      stream.addEventListener("key_insights", (event) => {
        const payload = parse(event);
        setAiDashboardData((prev) => ({
          ...(prev || base),
          key_insights: Array.isArray(payload.items) ? payload.items : [],
          drilldown_suggestion: payload.drilldown_suggestion || null,
          recommendations: Array.isArray(payload.recommendations) ? payload.recommendations : [],
          executive_summary: typeof payload.executive_summary === "string" ? payload.executive_summary : "",
          root_cause_hypotheses: Array.isArray(payload.root_cause_hypotheses) ? payload.root_cause_hypotheses : [],
          prioritized_actions: Array.isArray(payload.prioritized_actions) ? payload.prioritized_actions : [],
          watchouts: Array.isArray(payload.watchouts) ? payload.watchouts : [],
        }));
      });

      stream.addEventListener("chart", (event) => {
        const payload = parse(event);
        const block = payload.block;
        if (!block) return;
        setAiDashboardData((prev) => ({
          ...(prev || base),
          blocks: [...((prev || base).blocks || []), block],
        }));
      });

      stream.addEventListener("complete", () => {
        completed = true;
        close();
        resolve(true);
      });

      stream.onerror = () => {
        close();
        if (!completed) {
          reject(new Error("Dashboard stream interrupted."));
        }
      };
    });
  }

  async function loadMenuManagementData() {
    setMenuAdminLoading(true);
    try {
      const [cats, items] = await Promise.all([
        api.listMenuCategories(),
        api.listMenuItemsAdmin({
          includeInactive: menuIncludeInactive,
          query: menuSearch.trim(),
          category: menuCategoryFilter,
        }),
      ]);
      setMenuAdminCategories(cats.categories || []);
      setMenuAdminItems(items.items || []);
      if (!newItemCategoryId && (cats.categories || []).length) {
        setNewItemCategoryId(cats.categories[0].id);
      }
      setError("");
    } catch (err) {
      setError(err.message || "Unable to load menu management data.");
    } finally {
      setMenuAdminLoading(false);
    }
  }

  async function saveTaxRate() {
    const raw = (taxRateInput || "").trim().replace(/,/g, ".");
    const next = Number(raw);
    if (!Number.isFinite(next) || next < 0 || next > 100) {
      setError("Tax rate should be a number from 0 to 100.");
      return;
    }
    setTaxRateSaving(true);
    try {
      const res = await api.putTaxSettings(next, (auth.userIdInput || "owner").trim() || "owner");
      const applied =
        typeof res?.tax_rate_percent === "number" && Number.isFinite(res.tax_rate_percent)
          ? res.tax_rate_percent
          : next;
      setTaxRatePercent(applied);
      setTaxRateInput(String(applied));
      setError("");
      await bootstrap();
    } catch (err) {
      setError(err.message || "Unable to save tax rate.");
    } finally {
      setTaxRateSaving(false);
    }
  }

  async function createCategory() {
    const name = newCategoryName.trim();
    if (!name) {
      setError("Category name is required.");
      return;
    }
    try {
      await api.createMenuCategory({ name, position: menuAdminCategories.length, is_active: true });
      setNewCategoryName("");
      await loadMenuManagementData();
      await bootstrap();
    } catch (err) {
      setError(err.message || "Unable to create category.");
    }
  }

  async function renameCategory(category) {
    const next = window.prompt("Rename category", category.name);
    if (next === null) return;
    const name = next.trim();
    if (!name || name === category.name) return;
    try {
      await api.updateMenuCategory(category.id, { name });
      await loadMenuManagementData();
      await bootstrap();
    } catch (err) {
      setError(err.message || "Unable to rename category.");
    }
  }

  async function toggleCategoryVisibility(category) {
    try {
      await api.updateMenuCategory(category.id, { is_active: !category.is_active });
      await loadMenuManagementData();
      await bootstrap();
    } catch (err) {
      setError(err.message || "Unable to update category visibility.");
    }
  }

  async function deleteCategory(category) {
    const others = menuAdminCategories.filter((c) => c.id !== category.id);
    let moveToCategoryId = "";
    if ((category.item_count || 0) > 0) {
      if (!others.length) {
        setError("Cannot delete the only category when it contains items.");
        return;
      }
      const optionsLabel = others.map((c, idx) => `${idx + 1}. ${c.name}`).join("\n");
      const selected = window.prompt(
        `Category '${category.name}' has ${category.item_count} item(s).\nMove items to which category?\n${optionsLabel}`,
        others[0].name
      );
      if (selected === null) return;
      const target = others.find((c) => c.name.toLowerCase() === selected.trim().toLowerCase());
      if (!target) {
        setError("Valid target category is required to move items.");
        return;
      }
      moveToCategoryId = target.id;
    }
    if (!window.confirm(`Delete category '${category.name}'?`)) return;
    try {
      await api.deleteMenuCategory(category.id, moveToCategoryId);
      await loadMenuManagementData();
      await bootstrap();
    } catch (err) {
      setError(err.message || "Unable to delete category.");
    }
  }

  async function createMenuItem() {
    const name = newItemName.trim();
    const price = Number(newItemPrice);
    if (!name) {
      setError("Item name is required.");
      return;
    }
    if (!newItemCategoryId) {
      setError("Select a category for item.");
      return;
    }
    if (!Number.isFinite(price) || price <= 0) {
      setError("Item price should be greater than 0.");
      return;
    }
    try {
      await api.createMenuItemAdmin({ name, price, category_id: newItemCategoryId, position: menuAdminItems.length });
      setNewItemName("");
      setNewItemPrice("");
      await loadMenuManagementData();
      await bootstrap();
    } catch (err) {
      setError(err.message || "Unable to create menu item.");
    }
  }

  function resetMenuFilters() {
    setMenuSearch("");
    setMenuCategoryFilter("");
    setMenuIncludeInactive(true);
  }

  async function editMenuItem(item) {
    const nameInput = window.prompt("Item name", item.name);
    if (nameInput === null) return;
    const priceInput = window.prompt("Item price", String(item.price));
    if (priceInput === null) return;
    const categoryInput = window.prompt(
      `Category (${menuAdminCategories.map((c) => c.name).join(", ")})`,
      item.category
    );
    if (categoryInput === null) return;
    const nextName = nameInput.trim();
    const nextPrice = Number(priceInput);
    const category = menuAdminCategories.find((c) => c.name.toLowerCase() === categoryInput.trim().toLowerCase());
    if (!nextName) {
      setError("Item name is required.");
      return;
    }
    if (!Number.isFinite(nextPrice) || nextPrice <= 0) {
      setError("Item price should be greater than 0.");
      return;
    }
    if (!category) {
      setError("Enter a valid category name.");
      return;
    }
    try {
      await api.updateMenuItemAdmin(item.id, {
        name: nextName,
        price: nextPrice,
        category_id: category.id,
      });
      await loadMenuManagementData();
      await bootstrap();
    } catch (err) {
      setError(err.message || "Unable to update menu item.");
    }
  }

  async function toggleItemVisibility(item) {
    try {
      await api.updateMenuItemAdmin(item.id, { is_active: !item.is_active });
      await loadMenuManagementData();
      await bootstrap();
    } catch (err) {
      setError(err.message || "Unable to update item visibility.");
    }
  }

  async function deleteMenuItem(item) {
    if (!window.confirm(`Delete menu item '${item.name}'?`)) return;
    try {
      await api.deleteMenuItemAdmin(item.id);
      await loadMenuManagementData();
      await bootstrap();
    } catch (err) {
      setError(err.message || "Unable to delete menu item.");
    }
  }

  async function editItem(itemIndex) {
    if (!activeOrder) return;
    const current = activeOrder.items?.[itemIndex];
    if (!current || current.voided) return;
    const qtyRaw = window.prompt("Quantity", String(current.qty || 1));
    if (!qtyRaw) return;
    const qty = Number(qtyRaw);
    if (!Number.isFinite(qty) || qty < 1) {
      setError("Quantity should be a positive number.");
      return;
    }
    const noteInput = window.prompt("Item note", current.modifiers?.note || "");
    const note = noteInput ?? current.modifiers?.note ?? "";
    const lessSugarInput = window.prompt(
      "Less sugar? (y/n, leave blank to keep current)",
      current.modifiers?.less_sugar ? "y" : ""
    );
    const noIceInput = window.prompt(
      "No ice? (y/n, leave blank to keep current)",
      current.modifiers?.no_ice ? "y" : ""
    );
    const lessSugar = parseTernaryBoolean(lessSugarInput, current.modifiers?.less_sugar || false);
    const noIce = parseTernaryBoolean(noIceInput, current.modifiers?.no_ice || false);
    const payload = {
      qty: Math.round(qty),
      modifiers: { less_sugar: lessSugar, no_ice: noIce, note },
    };

    if (!syncState.online || activeOrder.id.startsWith("local-")) {
      await enqueueMutation(mutation("UPDATE_ITEM", { tableId: selectedTable, orderId: activeOrder.id, itemIndex, ...payload }));
      setOrderByTable((prev) => {
        const base = prev[selectedTable];
        if (!base) return prev;
        const nextItems = [...(base.items || [])];
        nextItems[itemIndex] = normalizeItemServiceState({ ...nextItems[itemIndex], ...payload }, base.status);
        return {
          ...prev,
          [selectedTable]: { ...base, items: nextItems, totals: calcTotals(nextItems, base.totals?.discount || 0, taxRatePercent) },
        };
      });
      refreshPending();
      return;
    }
    try {
      const updated = await api.updateItem(activeOrder.id, itemIndex, payload);
      setOrderByTable((prev) => ({ ...prev, [selectedTable]: normalizeOrder(updated) }));
      setError("");
    } catch (err) {
      setError(err.message || "Unable to edit item.");
    }
  }

  async function voidOrderItem(itemIndex) {
    if (!activeOrder) return;
    const reason = window.prompt("Cancel item reason");
    if (!reason?.trim()) return;
    if (!syncState.online || activeOrder.id.startsWith("local-")) {
      await enqueueMutation(
        mutation("VOID_ITEM", { tableId: selectedTable, orderId: activeOrder.id, itemIndex, reason: reason.trim() })
      );
      setOrderByTable((prev) => {
        const base = prev[selectedTable];
        if (!base) return prev;
        const nextItems = [...(base.items || [])];
        nextItems[itemIndex] = {
          ...nextItems[itemIndex],
          voided: true,
          void_reason: reason.trim(),
          voided_by: "cashier-demo",
          voided_at: new Date().toISOString(),
        };
        return {
          ...prev,
          [selectedTable]: { ...base, items: nextItems, totals: calcTotals(nextItems, base.totals?.discount || 0, taxRatePercent) },
        };
      });
      refreshPending();
      return;
    }
    try {
      const updated = await api.voidItem(activeOrder.id, itemIndex, reason.trim());
      setOrderByTable((prev) => ({ ...prev, [selectedTable]: normalizeOrder(updated) }));
      setError("");
    } catch (err) {
      setError(err.message || "Unable to cancel item.");
    }
  }

  /**
   * Apply a fixed discount amount (currency) to the active order for this table.
   * Returns the updated order shape for callers that need to sync the itemized bill modal.
   */
  async function applyOrderDiscountAmount(amount, reason, managerId = DEFAULT_DISCOUNT_MANAGER_ID) {
    if (!activeOrder) {
      setError("No active order.");
      return null;
    }
    const mid = (managerId || DEFAULT_DISCOUNT_MANAGER_ID).trim();
    if (!Number.isFinite(amount) || amount < 0) {
      setError("Discount amount must be zero or greater.");
      return null;
    }
    if (!reason?.trim()) {
      setError("Discount reason is required.");
      return null;
    }
    if (!mid.startsWith("manager-")) {
      setError("Manager ID must start with manager-.");
      return null;
    }
    if (["Paid", "Cancelled"].includes(activeOrder.status)) {
      setError("Cannot apply discount to a paid or cancelled order.");
      return null;
    }
    if (!syncState.online || activeOrder.id.startsWith("local-")) {
      await enqueueMutation(
        mutation("APPLY_DISCOUNT", {
          tableId: selectedTable,
          orderId: activeOrder.id,
          amount,
          managerId: mid,
          reason: reason.trim(),
        })
      );
      let nextOrder = null;
      setOrderByTable((prev) => {
        const base = prev[selectedTable];
        if (!base) return prev;
        const totals = calcTotals(base.items || [], amount, taxRatePercent);
        nextOrder = { ...base, discount: amount, totals };
        return { ...prev, [selectedTable]: nextOrder };
      });
      refreshPending();
      setError("");
      return nextOrder;
    }
    try {
      const updated = await api.applyDiscount(activeOrder.id, amount, mid, reason.trim());
      const normalized = normalizeOrder(updated);
      setOrderByTable((prev) => ({ ...prev, [selectedTable]: normalized }));
      setError("");
      return { ...normalized, table_id: updated.table_id || selectedTable };
    } catch (err) {
      setError(err.message || "Unable to apply discount.");
      return null;
    }
  }

  function billDiscountGuard() {
    if (!activeOrder || !billPreview.order) {
      setError("No order on this bill.");
      return false;
    }
    if (billPreview.order.id !== activeOrder.id) {
      setError("Discount only applies to the current table’s order. Close and open the bill from the table.");
      return false;
    }
    if (["Paid", "Cancelled"].includes(activeOrder.status)) {
      return false;
    }
    return true;
  }

  async function clearBillDiscount() {
    if (!billDiscountGuard()) {
      return;
    }
    setBillDiscountBusy(true);
    try {
      const updated = await applyOrderDiscountAmount(0, "Itemized bill: clear discount");
      if (updated) {
        setBillPreview((prev) => ({
          ...prev,
          order: {
            ...updated,
            table_id: updated.table_id || prev.order?.table_id || selectedTable,
          },
        }));
      }
    } finally {
      setBillDiscountBusy(false);
    }
  }

  async function applyBillDiscountPercent(percent) {
    if (!billDiscountGuard()) {
      return;
    }
    const billable = (billPreview.order?.items || []).filter((i) => !i.voided);
    const subtotal = billable.reduce(
      (sum, i) => sum + (Number(i.price) || 0) * (Number(i.qty) || 1),
      0
    );
    const amount = Math.round((subtotal * percent) / 100 * 100) / 100;
    if (amount <= 0) {
      setError("Subtotal is too small for this discount.");
      return;
    }
    if (
      !window.confirm(
        `Apply ${percent}% discount (about ${formatCurrency(amount)} on the current subtotal of ${formatCurrency(
          subtotal
        )})?`
      )
    ) {
      return;
    }
    setBillDiscountBusy(true);
    try {
      const reason = `Itemized bill: ${percent}% discount`;
      const updated = await applyOrderDiscountAmount(amount, reason);
      if (updated) {
        setBillPreview((prev) => ({
          ...prev,
          order: {
            ...updated,
            table_id: updated.table_id || prev.order?.table_id || selectedTable,
          },
        }));
      }
    } finally {
      setBillDiscountBusy(false);
    }
  }

  async function cancelOrder() {
    if (!activeOrder) return;
    if (["Paid", "Cancelled"].includes(activeOrder.status)) return;
    const reason = window.prompt("Cancel reason");
    if (!reason?.trim()) {
      setError("Cancel reason is required.");
      return;
    }
    if (!window.confirm("Cancel this order? This cannot be undone.")) {
      return;
    }

    if (!syncState.online || activeOrder.id.startsWith("local-")) {
      await enqueueMutation(
        mutation("STATUS_UPDATE", {
          orderId: activeOrder.id,
          tableId: selectedTable,
          status: "Cancelled",
          reason: reason.trim(),
        })
      );
      setOrderByTable((prev) => {
        const { [selectedTable]: _closed, ...rest } = prev;
        return rest;
      });
      refreshPending();
      return;
    }
    try {
      const updated = await api.updateStatus(activeOrder.id, "Cancelled", reason.trim());
      if (updated.status === "Cancelled") {
        setOrderByTable((prev) => {
          const { [selectedTable]: _closed, ...rest } = prev;
          return rest;
        });
      } else {
        setOrderByTable((prev) => ({ ...prev, [selectedTable]: normalizeOrder(updated) }));
      }
      setError("");
    } catch (err) {
      setError(err.message || "Unable to cancel order.");
    }
  }

  function openItemizedBill() {
    if (!activeOrder) return;
    lastModalTriggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setBillPreview({
      open: true,
      generatedAt: new Date().toISOString(),
      email: "",
      sending: false,
      status: "",
      order: { ...activeOrder, table_id: selectedTable },
    });
  }

  async function openHistoryItemizedBill(orderId) {
    try {
      lastModalTriggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      const fullOrder = await api.getOrder(orderId);
      setBillPreview({
        open: true,
        generatedAt: new Date().toISOString(),
        email: "",
        sending: false,
        status: "",
        order: fullOrder,
      });
      setError("");
    } catch (err) {
      setError(err.message || "Unable to load order details for bill.");
    }
  }

  async function deleteHistoryOrder(orderId) {
    if (!window.confirm(`Delete order ${orderId} from billing history?\n\nThis action cannot be undone.`)) {
      return;
    }
    try {
      await api.deleteOrder(orderId);
      setHistoryData((prev) => prev.filter((row) => row.id !== orderId));
      setOrderByTable((prev) => {
        return Object.fromEntries(Object.entries(prev).filter(([, order]) => order?.id !== orderId));
      });
      if (billPreview.open && billPreview.order?.id === orderId) {
        closeItemizedBill();
      }
      await loadSummary();
      setError("");
    } catch (err) {
      setError(err.message || "Unable to delete order from history.");
    }
  }

  function closeItemizedBill() {
    setBillPreview((prev) => ({ ...prev, open: false, sending: false, order: null }));
    if (lastModalTriggerRef.current && document.contains(lastModalTriggerRef.current)) {
      window.requestAnimationFrame(() => {
        lastModalTriggerRef.current?.focus();
      });
    }
  }

  function handleMainTabsKeyDown(event) {
    const order = ["dashboard", "reports", "menu-management"];
    const index = order.indexOf(mainTab);
    if (event.key === "ArrowRight") {
      event.preventDefault();
      const next = order[(index + 1) % order.length];
      setMainTab(next);
      document.getElementById(`main-tab-${next}`)?.focus();
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      const next = order[(index - 1 + order.length) % order.length];
      setMainTab(next);
      document.getElementById(`main-tab-${next}`)?.focus();
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      setMainTab(order[0]);
      document.getElementById(`main-tab-${order[0]}`)?.focus();
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      setMainTab(order[order.length - 1]);
      document.getElementById(`main-tab-${order[order.length - 1]}`)?.focus();
    }
  }

  function handleReportsTabsKeyDown(event) {
    const order = ["summary", "history", "ai-dashboard"];
    const index = order.indexOf(reportsTab);
    if (event.key === "ArrowRight") {
      event.preventDefault();
      const next = order[(index + 1) % order.length];
      setReportsTab(next);
      document.getElementById(`reports-tab-${next}`)?.focus();
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      const next = order[(index - 1 + order.length) % order.length];
      setReportsTab(next);
      document.getElementById(`reports-tab-${next}`)?.focus();
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      setReportsTab(order[0]);
      document.getElementById(`reports-tab-${order[0]}`)?.focus();
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      setReportsTab(order[order.length - 1]);
      document.getElementById(`reports-tab-${order[order.length - 1]}`)?.focus();
    }
  }

  function printItemizedBill() {
    document.body.classList.add("bill-print-mode");
    const runPrint = () => {
      window.print();
      window.setTimeout(() => {
        document.body.classList.remove("bill-print-mode");
      }, 500);
    };
    if (typeof window.requestAnimationFrame === "function") {
      // Wait two paint frames so print-mode styles are fully applied before browser snapshots content.
      window.requestAnimationFrame(() => window.requestAnimationFrame(runPrint));
      return;
    }
    window.setTimeout(runPrint, 0);
  }

  async function sendEbillEmail() {
    if (!billPreview.order?.id) return;
    const email = (billPreview.email || "").trim();
    if (!email) {
      setBillPreview((prev) => ({ ...prev, status: "Enter customer email." }));
      return;
    }
    setBillPreview((prev) => ({ ...prev, sending: true, status: "" }));
    try {
      const result = await api.sendEbillEmail(billPreview.order.id, email);
      setBillPreview((prev) => ({
        ...prev,
        sending: false,
        status: `eBill email sent to ${result.email_masked}.`,
      }));
    } catch (err) {
      setBillPreview((prev) => ({
        ...prev,
        sending: false,
        status: err.message || "Unable to send eBill email.",
      }));
    }
  }

  const totals = useMemo(
    () => activeOrder?.totals || { subtotal: 0, discount: 0, tax: 0, total: 0 },
    [activeOrder]
  );
  const summaryEntries = useMemo(
    () => Object.entries(summaryData?.summary || {}),
    [summaryData]
  );
  const summaryTotals = useMemo(() => {
    return summaryEntries.reduce(
      (acc, [, row]) => {
        acc.count += row?.count || 0;
        acc.amount += row?.total_amount || 0;
        return acc;
      },
      { count: 0, amount: 0 }
    );
  }, [summaryEntries]);
  const activeStatus = activeOrder?.status || "Open";
  const nextStatus = getNextStatus(activeStatus);
  const pendingClass = syncState.pending > 0 ? "warn" : "ok";
  const canModifyOrder = activeOrder && !["Billed", "Paid", "Cancelled"].includes(activeStatus);
  const pendingServeCount = useMemo(
    () =>
      (activeOrder?.items || []).reduce((sum, item) => sum + pendingQtyForItem(item), 0),
    [activeOrder]
  );
  const canServePendingItems = activeOrder && activeStatus === "Served" && pendingServeCount > 0;
  const canOpenItemizedBill = activeOrder && ["Served", "Billed"].includes(activeStatus);
  const currentOrderBillItems = useMemo(() => (activeOrder?.items || []).filter((item) => !item.voided), [activeOrder]);
  const hasCurrentBillableItems = currentOrderBillItems.length > 0;
  const billOrder = billPreview.order;
  const billItems = useMemo(() => (billOrder?.items || []).filter((item) => !item.voided), [billOrder]);
  const { billTotals, billImpliedDiscountPercent } = useMemo(() => {
    const lineSubtotal = billItems.reduce(
      (sum, i) => sum + (Number(i.price) || 0) * (Number(i.qty) || 1),
      0
    );
    let rawDiscount = 0;
    if (billOrder) {
      if (billOrder.discount != null && billOrder.discount !== "") {
        rawDiscount = Number(billOrder.discount);
      } else {
        rawDiscount = Number(billOrder.totals?.discount ?? 0);
      }
    }
    if (!Number.isFinite(rawDiscount) || rawDiscount < 0) {
      rawDiscount = 0;
    }
    const discountIn = Math.min(rawDiscount, lineSubtotal);
    const totals = calcTotals(billItems, discountIn, taxRatePercent);
    let impliedPct = null;
    if (totals.discount > 0.005 && lineSubtotal > 0.005) {
      impliedPct = Math.round((totals.discount / lineSubtotal) * 1000) / 10;
    }
    return { billTotals: totals, billImpliedDiscountPercent: impliedPct };
  }, [billItems, billOrder, taxRatePercent]);
  const billItemCount = useMemo(
    () => billItems.reduce((sum, item) => sum + Number(item.qty || 1), 0),
    [billItems]
  );
  const aiModeIsLlm = aiDashboardMode === "llm";
  const aiDashboardBlocks = aiDashboardData?.blocks || [];
  const aiDashboardInsights = Array.isArray(aiDashboardData?.key_insights)
    ? aiDashboardData.key_insights
        .map((insight) => {
          if (typeof insight === "string") {
            return { text: insight, confidence: null, citations: [] };
          }
          return {
            text: insight?.text || "",
            confidence:
              typeof insight?.confidence === "number" ? Number(insight.confidence) : null,
            citations: Array.isArray(insight?.citations) ? insight.citations : [],
          };
        })
        .filter((insight) => insight.text)
    : [];
  const aiDrilldownSuggestion = aiDashboardData?.drilldown_suggestion || null;
  const aiRecommendations = Array.isArray(aiDashboardData?.recommendations)
    ? aiDashboardData.recommendations
    : [];
  const aiExecutiveSummary =
    typeof aiDashboardData?.executive_summary === "string" ? aiDashboardData.executive_summary : "";
  const aiRootCauses = Array.isArray(aiDashboardData?.root_cause_hypotheses)
    ? aiDashboardData.root_cause_hypotheses
    : [];
  const aiPrioritizedActions = Array.isArray(aiDashboardData?.prioritized_actions)
    ? aiDashboardData.prioritized_actions
    : [];
  const aiWatchouts = Array.isArray(aiDashboardData?.watchouts) ? aiDashboardData.watchouts : [];
  const aiPendingCharts = Math.max(aiExpectedCharts - aiDashboardBlocks.length, 0);
  const selectedLlmModelOption =
    LLM_MODEL_OPTIONS.find((row) => row.value === aiLlmModel) ||
    ({ value: aiLlmModel, label: aiLlmModel, availability: "Availability unknown", availability_tone: "low" });
  const sortedAiPrioritizedActions = useMemo(() => {
    const impactRank = { high: 3, medium: 2, low: 1 };
    const effortRank = { low: 1, medium: 2, high: 3 };
    const timeRank = { immediate: 1, this_week: 2, this_month: 3 };
    return [...aiPrioritizedActions].sort((a, b) => {
      const impactA = impactRank[a?.impact] || 0;
      const impactB = impactRank[b?.impact] || 0;
      const effortA = effortRank[a?.effort] || 99;
      const effortB = effortRank[b?.effort] || 99;
      const timeA = timeRank[a?.time_horizon] || 99;
      const timeB = timeRank[b?.time_horizon] || 99;
      if (aiActionSort === "effort") {
        return effortA - effortB || impactB - impactA || timeA - timeB;
      }
      return impactB - impactA || effortA - effortB || timeA - timeB;
    });
  }, [aiPrioritizedActions, aiActionSort]);
  const deterministicMetrics = aiDashboardData?.deterministic_metrics || {};
  const deterministicKpis = deterministicMetrics.kpi_deltas || {};
  const deterministicSla = deterministicMetrics.sla_panel || {};
  const deterministicForecast = deterministicMetrics.forecast || {};

  return (
    <div className="page">
      {auth.loading ? (
        <section className="card authCard">
          <h3>Loading</h3>
          <div className="muted">Checking session...</div>
        </section>
      ) : !auth.authenticated ? (
        <section className="card authCard">
          <h3>Secure Access</h3>
          <div className="muted">{auth.info || "Use authenticator app code to continue."}</div>
          <div className="row authRow">
            <input
              type="text"
              placeholder="User ID (e.g., cashier-1)"
              value={auth.userIdInput}
              onChange={(e) => setAuth((a) => ({ ...a, userIdInput: e.target.value }))}
            />
            <input
              type="text"
              placeholder="Setup key (if required)"
              value={auth.setupKeyInput}
              onChange={(e) => setAuth((a) => ({ ...a, setupKeyInput: e.target.value }))}
            />
            <button onClick={setupAuthenticator}>Setup Auth App</button>
          </div>
          {auth.provisioningUri && (
            <div className="error">
              Provisioning URI: {auth.provisioningUri}
            </div>
          )}
          {auth.qrDataUrl && (
            <div className="authQrWrap">
              <img
                src={auth.qrDataUrl}
                alt="TOTP QR code"
                className="authQrImg"
              />
            </div>
          )}
          {auth.devSecret && <div className="error">Development secret: {auth.devSecret}</div>}
          <div className="row authRow">
            <input
              type="text"
              placeholder="User ID"
              value={auth.userIdInput}
              onChange={(e) => setAuth((a) => ({ ...a, userIdInput: e.target.value }))}
            />
            <input
              type="text"
              placeholder="Enter authenticator code"
              value={auth.codeInput}
              onChange={(e) => setAuth((a) => ({ ...a, codeInput: e.target.value }))}
            />
            <button className="primary" onClick={verifyAuthenticatorCode}>
              Verify
            </button>
          </div>
        </section>
      ) : (
        <>
          <header className="top">
            <div className="brandBlock">
              <h1>Aromaz Cafe</h1>
              <p>Single Origin Arabica</p>
            </div>
            <div className="chips">
              <span className={`statusPill ${syncState.online ? "ok" : "offline"}`}>
                {syncState.online ? "Online" : "Offline"}
              </span>
              <span className={`statusPill ${pendingClass}`}>Pending: {syncState.pending}</span>
              <span className="statusPill neutral">Active: {selectedTable}</span>
            </div>
          </header>

          {error && <div className="error" role="alert">{error}</div>}

          <div className="viewTabs" role="tablist" aria-label="Primary sections" onKeyDown={handleMainTabsKeyDown}>
            <button
              id="main-tab-dashboard"
              role="tab"
              aria-selected={mainTab === "dashboard"}
              aria-controls="main-panel-dashboard"
              tabIndex={mainTab === "dashboard" ? 0 : -1}
              className={`chipBtn ${mainTab === "dashboard" ? "active" : ""}`}
              onClick={() => setMainTab("dashboard")}
            >
              Dashboard
            </button>
            <button
              id="main-tab-reports"
              role="tab"
              aria-selected={mainTab === "reports"}
              aria-controls="main-panel-reports"
              tabIndex={mainTab === "reports" ? 0 : -1}
              className={`chipBtn ${mainTab === "reports" ? "active" : ""}`}
              onClick={() => setMainTab("reports")}
            >
              Reports
            </button>
            <button
              id="main-tab-menu-management"
              role="tab"
              aria-selected={mainTab === "menu-management"}
              aria-controls="main-panel-menu-management"
              tabIndex={mainTab === "menu-management" ? 0 : -1}
              className={`chipBtn ${mainTab === "menu-management" ? "active" : ""}`}
              onClick={() => setMainTab("menu-management")}
            >
              Menu Management
            </button>
          </div>

          {mainTab === "dashboard" ? (
            <section id="main-panel-dashboard" role="tabpanel" aria-labelledby="main-tab-dashboard" className="layout">
              <aside className="card tablesCard">
                <h3>Tables</h3>
                <div className="tablesWrap">
                  {tables.map((t) => {
                    const id = t.table_id;
                    const order = orderByTable[id];
                    const orderStatus = !order || ["Paid", "Cancelled"].includes(order.status) ? "Open" : order.status;
                    return (
                      <button
                        key={id}
                        className={`tableBtn ${selectedTable === id ? "active" : ""}`}
                        onClick={() => setSelectedTable(id)}
                      >
                        <span>{id}</span>
                        <small className={`tableStatus ${statusClassName(orderStatus)}`}>{statusLabel(orderStatus)}</small>
                      </button>
                    );
                  })}
                </div>
              </aside>

              <main className="card">
                <h3>Menu</h3>
                <div className="chips">
                  {categories.map((cat) => (
                    <button
                      key={cat}
                      className={`chipBtn ${selectedCategory === cat ? "active" : ""}`}
                      onClick={() => setSelectedCategory(cat)}
                    >
                      {cat}
                    </button>
                  ))}
                </div>
                <div className="menuGrid">
                  {items.map((item) => (
                    <button key={item.name} className="menuItem" onClick={() => addItem(item)}>
                      <span>{item.name}</span>
                      <strong>₹{item.price}</strong>
                    </button>
                  ))}
                </div>
              </main>

              <aside className="card">
                <h3>Current Order</h3>
                <div className="muted">Table {selectedTable}</div>
                <div className="muted">
                  Status: <span className={`statusPill inline ${statusClassName(activeStatus)}`}>{statusLabel(activeStatus)}</span>
                </div>
                {canServePendingItems ? (
                  <div className="muted pendingServeNotice">{pendingServeCount} qty pending service</div>
                ) : null}
                <div className="orderList">
                  {(activeOrder?.items || []).map((item, idx) => (
                    <div key={`${item.name}-${idx}`} className={`orderItem ${item.voided ? "voided" : ""}`}>
                      <div className="row">
                        <span>
                          {item.name} x{item.qty || 1}
                        </span>
                        <span>₹{item.price}</span>
                      </div>
                      <div className="muted">
                        {item.modifiers?.note ? `Note: ${item.modifiers.note}` : "No note"}
                        {item.modifiers?.less_sugar ? " | less sugar" : ""}
                        {item.modifiers?.no_ice ? " | no ice" : ""}
                        {item.voided ? ` | Cancelled item: ${item.void_reason || "reason missing"}` : ""}
                        {!item.voided && pendingQtyForItem(item) > 0 ? ` | Pending serve: ${pendingQtyForItem(item)}` : ""}
                      </div>
                      {!item.voided && canModifyOrder && (
                        <div className="row itemActions">
                          <button onClick={() => editItem(idx)}>Edit</button>
                          <button
                            className="iconDanger"
                            title="Cancel item"
                            aria-label="Cancel item"
                            onClick={() => voidOrderItem(idx)}
                          >
                            ×
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                <div className="totals">
                  <div className="row"><span>Subtotal</span><strong>₹{Math.round(totals.subtotal || 0)}</strong></div>
                  <div className="row"><span>Tax</span><strong>₹{Math.round(totals.tax || 0)}</strong></div>
                  <div className="row"><span>Total</span><strong>₹{Math.round(totals.total || 0)}</strong></div>
                </div>
                {canServePendingItems ? (
                  <button className="secondaryAction" onClick={servePendingItems}>
                    Serve new items
                  </button>
                ) : null}
                <button
                  className="primary"
                  onClick={moveStatus}
                  disabled={!activeOrder || !nextStatus || (nextStatus === "Billed" && pendingServeCount > 0)}
                >
                  {nextStatus ? `Move to ${statusLabel(nextStatus)}` : "Status Complete"}
                </button>
                <button
                  onClick={openItemizedBill}
                  disabled={!canOpenItemizedBill || !hasCurrentBillableItems}
                  title={!hasCurrentBillableItems ? "No billable items to print" : "Preview customer bill"}
                >
                  Itemized Bill
                </button>
                <button className="danger" onClick={cancelOrder} disabled={!activeOrder || ["Paid", "Cancelled"].includes(activeStatus)}>
                  Cancel Order
                </button>
              </aside>
            </section>
          ) : mainTab === "reports" ? (
            <section id="main-panel-reports" role="tabpanel" aria-labelledby="main-tab-reports" className="card report">
              <div className="reportTabs" role="tablist" aria-label="Reports sections" onKeyDown={handleReportsTabsKeyDown}>
                <button
                  id="reports-tab-summary"
                  role="tab"
                  aria-selected={reportsTab === "summary"}
                  aria-controls="reports-panel-summary"
                  tabIndex={reportsTab === "summary" ? 0 : -1}
                  className={`chipBtn ${reportsTab === "summary" ? "active" : ""}`}
                  onClick={() => setReportsTab("summary")}
                >
                  Summary
                </button>
                <button
                  id="reports-tab-history"
                  role="tab"
                  aria-selected={reportsTab === "history"}
                  aria-controls="reports-panel-history"
                  tabIndex={reportsTab === "history" ? 0 : -1}
                  className={`chipBtn ${reportsTab === "history" ? "active" : ""}`}
                  onClick={() => setReportsTab("history")}
                >
                  Day-wise Order History
                </button>
                <button
                  id="reports-tab-ai-dashboard"
                  role="tab"
                  aria-selected={reportsTab === "ai-dashboard"}
                  aria-controls="reports-panel-ai-dashboard"
                  tabIndex={reportsTab === "ai-dashboard" ? 0 : -1}
                  className={`chipBtn ${reportsTab === "ai-dashboard" ? "active" : ""}`}
                  onClick={() => setReportsTab("ai-dashboard")}
                >
                  AI Dashboard
                </button>
              </div>
              {reportsTab === "summary" ? (
                <section id="reports-panel-summary" role="tabpanel" aria-labelledby="reports-tab-summary">
                  <h3>
                    Summary {summaryLoading ? <span className="muted">(Refreshing...)</span> : null}
                  </h3>
                  <div className="row">
                    <input type="date" value={rangeFrom} onChange={(e) => setRangeFrom(e.target.value)} />
                    <input type="date" value={rangeTo} onChange={(e) => setRangeTo(e.target.value)} />
                  </div>
                  {summaryRangeError ? <div className="error">{summaryRangeError}</div> : null}
                  <div className="reportMeta muted">
                    Range: {summaryData?.from_date || rangeFrom} to {summaryData?.to_date || rangeTo}
                  </div>
                  {summaryEntries.length ? (
                    <>
                      <div className="reportSummaryCards">
                        <div className="reportSummaryCard">
                          <span className="muted">Orders</span>
                          <strong>{summaryTotals.count}</strong>
                        </div>
                        <div className="reportSummaryCard">
                          <span className="muted">Total Amount</span>
                          <strong>{formatCurrency(summaryTotals.amount)}</strong>
                        </div>
                      </div>
                      <div className="reportGrid">
                        {summaryEntries.map(([status, row]) => (
                          <div key={status} className="reportStatusCard">
                            <div className="row">
                              <span className={`statusPill inline ${statusClassName(status)}`}>{statusLabel(status)}</span>
                              <strong>{row?.count || 0}</strong>
                            </div>
                            <div className="muted">Amount: {formatCurrency(row?.total_amount || 0)}</div>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="reportEmpty muted">No summary data for selected range.</div>
                  )}
                </section>
              ) : reportsTab === "history" ? (
                <section id="reports-panel-history" role="tabpanel" aria-labelledby="reports-tab-history">
                  <h3>
                    Day-wise Order History {historyLoading ? <span className="muted">(Refreshing...)</span> : null}
                  </h3>
                  <div className="row">
                    <input type="date" value={historyDate} onChange={(e) => setHistoryDate(e.target.value)} />
                  </div>
                  <div className="reportMeta muted">
                    Date: {historyDate} | Orders: {historyData.length}
                  </div>
                  {historyData.length ? (
                    <div className="historyTableWrap">
                      <table className="historyTable">
                        <thead>
                          <tr>
                            <th>Created</th>
                            <th>Table</th>
                            <th>Status</th>
                            <th>Items</th>
                            <th className="right">Total</th>
                            <th className="right">Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {historyData.map((order) => (
                            <tr key={order.id}>
                              <td>{formatDateTime(order.created_at)}</td>
                              <td>{order.table_id}</td>
                              <td>
                                <span className={`statusPill inline ${statusClassName(order.status)}`}>
                                  {statusLabel(order.status)}
                                </span>
                              </td>
                              <td>{order.item_count || 0}</td>
                              <td className="right">{formatCurrency(order.total || 0)}</td>
                              <td className="right">
                                <div className="historyActions">
                                  <button className="historyBillBtn" onClick={() => openHistoryItemizedBill(order.id)}>
                                    Itemized Bill
                                  </button>
                                  <button
                                    className="historyDeleteBtn"
                                    title="Delete order history"
                                    aria-label={`Delete order ${order.id}`}
                                    onClick={() => deleteHistoryOrder(order.id)}
                                  >
                                    X
                                  </button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="reportEmpty muted">No orders found for selected date.</div>
                  )}
                </section>
              ) : (
                <section id="reports-panel-ai-dashboard" role="tabpanel" aria-labelledby="reports-tab-ai-dashboard">
                  <h3>
                    AI Dashboard {aiDashboardLoading ? <span className="muted">(Generating...)</span> : null}
                  </h3>
                  <div className="row">
                    <input type="date" value={rangeFrom} onChange={(e) => setRangeFrom(e.target.value)} />
                    <input type="date" value={rangeTo} onChange={(e) => setRangeTo(e.target.value)} />
                    <div className="aiModeSwitchWrap">
                      <span className="aiModeTitle">Mode</span>
                      <span className={`aiModeLabel ${!aiModeIsLlm ? "active" : ""}`}>Deterministic</span>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={aiModeIsLlm}
                        aria-label={`Toggle AI dashboard mode. Current mode: ${aiModeIsLlm ? "LLM" : "Deterministic"}`}
                        title={`Switch to ${aiModeIsLlm ? "Deterministic" : "LLM"} mode`}
                        className={`aiModeSwitch ${aiModeIsLlm ? "on" : ""}`}
                        onClick={() => setAiDashboardMode((mode) => (mode === "llm" ? "deterministic" : "llm"))}
                      >
                        <span className="aiModeSwitchThumb" />
                      </button>
                      <span className={`aiModeLabel ${aiModeIsLlm ? "active" : ""}`}>LLM</span>
                    </div>
                    {aiModeIsLlm ? (
                      <div className="aiModeSwitchWrap">
                        <span className="aiModeTitle">Hours</span>
                        <button
                          type="button"
                          className={`aiSortBtn ${aiHourScope === "operating" ? "active" : ""}`}
                          onClick={() => setAiHourScope("operating")}
                          aria-pressed={aiHourScope === "operating"}
                        >
                          Business Hours
                        </button>
                        <button
                          type="button"
                          className={`aiSortBtn ${aiHourScope === "all" ? "active" : ""}`}
                          onClick={() => setAiHourScope("all")}
                          aria-pressed={aiHourScope === "all"}
                        >
                          All hours
                        </button>
                      </div>
                    ) : null}
                    {aiModeIsLlm ? (
                      <div className="aiModelPickerWrap">
                        <label className="aiModeTitle" htmlFor="ai-llm-model-select">
                          Model
                        </label>
                        <select
                          id="ai-llm-model-select"
                          value={aiLlmModel}
                          onChange={(e) => setAiLlmModel(e.target.value)}
                        >
                          {LLM_MODEL_OPTIONS.map((row) => (
                            <option key={row.value} value={row.value}>
                              {row.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    ) : null}
                  </div>
                  <div className="reportMeta muted">
                    Range: {aiDashboardData?.from_date || rangeFrom} to {aiDashboardData?.to_date || rangeTo}
                    {aiDashboardData?.mode ? ` | Mode: ${aiDashboardData.mode}` : ""}
                    {aiDashboardData?.model ? ` | Model: ${aiDashboardData.model}` : ""}
                    {aiDashboardData?.hour_scope
                      ? ` | Hour Scope: ${aiDashboardData.hour_scope === "operating" ? "Business Hours" : "All Hours"}`
                      : ""}
                  </div>
                  {aiModeIsLlm ? (
                    <div className="reportMeta muted">
                      Model Availability:{" "}
                      <span className={`aiAvailabilityBadge ${selectedLlmModelOption.availability_tone || "low"}`}>
                        {selectedLlmModelOption.availability}
                      </span>
                    </div>
                  ) : null}
                  {aiDashboardData?.analytics_operating_context?.open_hours_local ? (
                    <div className="reportMeta muted">
                      Operating Hours: {aiDashboardData.analytics_operating_context.open_hours_local}
                      {" | "}Off Day: {aiDashboardData.analytics_operating_context.off_day || "Monday"}
                    </div>
                  ) : null}
                  {aiDashboardData?.mode === "deterministic" && deterministicMetrics?.kpi_deltas ? (
                    <section className="deterministicPanel">
                      <h4>Deterministic KPI Delta (Last 7d vs Prev 7d)</h4>
                      <div className="deterministicKpiGrid">
                        <div className="deterministicKpiCard">
                          <span>Orders</span>
                          <strong>{deterministicKpis.orders?.current || 0}</strong>
                          <small className={Number(deterministicKpis.orders?.delta || 0) >= 0 ? "deltaUp" : "deltaDown"}>
                            Δ {Number(deterministicKpis.orders?.delta || 0)}
                          </small>
                        </div>
                        <div className="deterministicKpiCard">
                          <span>Revenue</span>
                          <strong>{formatCurrency(deterministicKpis.revenue?.current || 0)}</strong>
                          <small className={Number(deterministicKpis.revenue?.delta || 0) >= 0 ? "deltaUp" : "deltaDown"}>
                            Δ {formatCurrency(deterministicKpis.revenue?.delta || 0)}
                          </small>
                        </div>
                        <div className="deterministicKpiCard">
                          <span>Avg Order Value</span>
                          <strong>{formatCurrency(deterministicKpis.avg_order_value?.current || 0)}</strong>
                          <small
                            className={Number(deterministicKpis.avg_order_value?.delta || 0) >= 0 ? "deltaUp" : "deltaDown"}
                          >
                            Δ {formatCurrency(deterministicKpis.avg_order_value?.delta || 0)}
                          </small>
                        </div>
                        <div className="deterministicKpiCard">
                          <span>Cancellation Rate</span>
                          <strong>{Number(deterministicKpis.cancellation_rate?.current || 0).toFixed(2)}%</strong>
                          <small
                            className={
                              Number(deterministicKpis.cancellation_rate?.current || 0) <=
                              Number(deterministicKpis.cancellation_rate?.target_max || 8)
                                ? "deltaUp"
                                : "deltaDown"
                            }
                          >
                            Target {"<="} {Number(deterministicKpis.cancellation_rate?.target_max || 8).toFixed(2)}%
                          </small>
                        </div>
                      </div>
                      <div className="deterministicSla">
                        <div>
                          <span>High dwell share:</span>{" "}
                          <strong>{Number(deterministicSla.high_dwell_share_pct || 0).toFixed(2)}%</strong>
                        </div>
                        <div>
                          <span>Billing completion:</span>{" "}
                          <strong>{Number(deterministicSla.billing_completion_rate_pct || 0).toFixed(2)}%</strong>
                        </div>
                        <div>
                          <span>Cancellation rate:</span>{" "}
                          <strong>{Number(deterministicSla.cancellation_rate_pct || 0).toFixed(2)}%</strong>
                        </div>
                        <div className="deterministicAlerts">
                          Alerts:
                          {deterministicSla.alerts?.high_dwell ? " High dwell" : ""}
                          {deterministicSla.alerts?.billing_completion_low ? " Low completion" : ""}
                          {deterministicSla.alerts?.cancellation_high ? " High cancellations" : ""}
                          {!deterministicSla.alerts?.high_dwell &&
                          !deterministicSla.alerts?.billing_completion_low &&
                          !deterministicSla.alerts?.cancellation_high
                            ? " Healthy"
                            : ""}
                        </div>
                      </div>
                      <div className="deterministicForecast">
                        Forecast ({deterministicForecast.method || "moving average"}): Next day ~{" "}
                        <strong>{formatCurrency(deterministicForecast.next_day_revenue || 0)}</strong> /{" "}
                        <strong>{Number(deterministicForecast.next_day_orders || 0).toFixed(1)} orders</strong> | Next week ~{" "}
                        <strong>{formatCurrency(deterministicForecast.next_week_revenue || 0)}</strong>
                      </div>
                    </section>
                  ) : null}
                  {aiDashboardError ? <div className="error">{aiDashboardError}</div> : null}
                  {aiModeIsLlm && aiDashboardData?.quality_flags?.used_fallback ? (
                    <div className="reportMeta aiFallbackBanner" role="status" aria-live="polite">
                      Fallback active: deterministic charts are shown because LLM output was partially invalid.
                    </div>
                  ) : null}
                  {(aiDashboardData?.diagnostics || []).length ? (
                    <div className="reportMeta muted">Diagnostics: {aiDashboardData.diagnostics.join(" | ")}</div>
                  ) : null}
                  {aiDashboardData?.token_usage?.total_tokens ? (
                    <div className="reportMeta muted">
                      Tokens: {aiDashboardData.token_usage.total_tokens}
                      {" | "}Prompt: {aiDashboardData.token_usage.prompt_tokens || 0}
                      {" | "}Candidate: {aiDashboardData.token_usage.candidate_tokens || 0}
                      {" | "}Thought: {aiDashboardData.token_usage.thought_tokens || 0}
                    </div>
                  ) : null}
                  {aiDashboardData?.estimated_cost?.total_cost ? (
                    <div className="reportMeta muted">
                      Estimated Cost ({aiDashboardData.estimated_cost.currency || "USD"}): $
                      {Number(aiDashboardData.estimated_cost.total_cost || 0).toFixed(6)}
                      {" | "}Input: ${Number(aiDashboardData.estimated_cost.input_cost || 0).toFixed(6)}
                      {" | "}Output: ${Number(aiDashboardData.estimated_cost.output_cost || 0).toFixed(6)}
                    </div>
                  ) : null}
                  {aiModeIsLlm && aiDashboardData?.quality_flags ? (
                    <div className="aiTrustMeta">
                      <span className={`aiTrustPill ${aiDashboardData.quality_flags.grounded_insights ? "ok" : "warn"}`}>
                        Quality: {aiDashboardData.quality_flags.grounded_insights ? "Grounded" : "Fallback"}
                      </span>
                      <span className="aiTrustPill">Schema fallback: {aiDashboardData.quality_flags.schema_fallback ? "Yes" : "No"}</span>
                      <span className="aiTrustPill">API error: {aiDashboardData.quality_flags.api_error ? "Yes" : "No"}</span>
                    </div>
                  ) : null}
                  {aiModeIsLlm &&
                  Array.isArray(aiDashboardData?.quality_flags?.attempted_models) &&
                  aiDashboardData.quality_flags.attempted_models.length ? (
                    <div className="reportMeta muted">
                      Tried models: {aiDashboardData.quality_flags.attempted_models.join(" -> ")}
                      {aiDashboardData?.quality_flags?.failover_used ? " | Failover: Yes" : " | Failover: No"}
                    </div>
                  ) : null}
                  {aiModeIsLlm && aiDashboardData?.observability?.today ? (
                    <div className="aiTrustMeta">
                      <span className="aiTrustPill">LLM today: {aiDashboardData.observability.today.llm_requests || 0} req</span>
                      <span className="aiTrustPill">Fallbacks: {aiDashboardData.observability.today.fallbacks || 0}</span>
                      <span className="aiTrustPill">Schema: {aiDashboardData.observability.today.schema_fallbacks || 0}</span>
                      <span className="aiTrustPill">
                        Avg latency:{" "}
                        {Number(
                          (aiDashboardData.observability.today.latency_ms || 0) /
                            Math.max(aiDashboardData.observability.today.llm_requests || 0, 1)
                        ).toFixed(0)}
                        ms
                      </span>
                    </div>
                  ) : null}
                  {aiModeIsLlm && aiExecutiveSummary ? (
                    <section className="aiAnalystBriefCard">
                      <h4>Analyst Brief</h4>
                      <p>{aiExecutiveSummary}</p>
                    </section>
                  ) : null}
                  {aiModeIsLlm && aiRootCauses.length ? (
                    <section className="aiRootCauseCard">
                      <h4>Why this is happening</h4>
                      <ul className="aiRootCauseList">
                        {aiRootCauses.map((item, idx) => (
                          <li key={`root-cause-${idx}`} className="aiRootCauseItem">
                            <strong>{item.title || "Root cause hypothesis"}</strong>
                            <p>{item.rationale || ""}</p>
                            <div className="aiInsightMeta">
                              {typeof item.confidence === "number" ? (
                                <span className="aiTrustBadge">Confidence {Math.round(item.confidence * 100)}%</span>
                              ) : null}
                              {item.risk_level ? <span className="aiCitationTag">Risk: {item.risk_level}</span> : null}
                              {(Array.isArray(item.citations) ? item.citations : []).slice(0, 2).map((citation, cIdx) => (
                                <span key={`root-cause-${idx}-citation-${cIdx}`} className="aiCitationTag">
                                  {citation.metric}: {String(citation.value)}
                                </span>
                              ))}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </section>
                  ) : null}
                  {aiModeIsLlm && aiPrioritizedActions.length ? (
                    <section className="aiActionPlanCard">
                      <div className="aiSectionHeader">
                        <h4>Action Plan</h4>
                        <div className="aiSortToggle" role="group" aria-label="Sort action plan">
                          <button
                            type="button"
                            className={`aiSortBtn ${aiActionSort === "impact" ? "active" : ""}`}
                            onClick={() => setAiActionSort("impact")}
                            aria-pressed={aiActionSort === "impact"}
                          >
                            Impact first
                          </button>
                          <button
                            type="button"
                            className={`aiSortBtn ${aiActionSort === "effort" ? "active" : ""}`}
                            onClick={() => setAiActionSort("effort")}
                            aria-pressed={aiActionSort === "effort"}
                          >
                            Effort first
                          </button>
                        </div>
                      </div>
                      <ul className="aiRecommendationList">
                        {sortedAiPrioritizedActions.map((item, idx) => (
                          <li key={`action-${idx}`} className="aiRecommendationItem">
                            <strong>{item.action}</strong>
                            <div className="aiInsightMeta">
                              <span className="aiCitationTag">Impact: {item.impact || "n/a"}</span>
                              <span className="aiCitationTag">Effort: {item.effort || "n/a"}</span>
                              <span className="aiCitationTag">Window: {item.time_horizon || "n/a"}</span>
                            </div>
                            <p className="muted aiActionPlanMeta">
                              Owner: {item.owner_hint || "Team lead"} | Success: {item.success_metric || "Track conversion and throughput"}
                            </p>
                          </li>
                        ))}
                      </ul>
                    </section>
                  ) : null}
                  {aiModeIsLlm && aiWatchouts.length ? (
                    <section className="aiWatchoutsCard">
                      <h4>Watchouts</h4>
                      <ul>
                        {aiWatchouts.map((item, idx) => (
                          <li key={`watchout-${idx}`}>{item}</li>
                        ))}
                      </ul>
                    </section>
                  ) : null}
                  {aiDashboardInsights.length ? (
                    <section className="aiInsightCard">
                      <h4>Key Insights</h4>
                      <ul className="aiInsightList">
                        {aiDashboardInsights.map((insight, idx) => (
                          <li key={`${idx}-${insight.text.slice(0, 24)}`} className="aiInsightItem">
                            <p>{insight.text}</p>
                            <div className="aiInsightMeta">
                              {typeof insight.confidence === "number" ? (
                                <span className="aiTrustBadge">
                                  Confidence {Math.round(insight.confidence * 100)}%
                                </span>
                              ) : null}
                              {(insight.citations || []).slice(0, 3).map((citation, cIdx) => (
                                <span key={`${idx}-citation-${cIdx}`} className="aiCitationTag">
                                  {citation.metric}: {String(citation.value)}
                                </span>
                              ))}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </section>
                  ) : null}
                  {aiModeIsLlm && (aiDrilldownSuggestion || aiRecommendations.length) ? (
                    <section className="aiRecommendationCard">
                      <h4>Recommended Next Steps</h4>
                      {aiDrilldownSuggestion ? (
                        <p className="muted aiDrilldownText">
                          Drilldown: <strong>{aiDrilldownSuggestion.dimension}</strong> -{" "}
                          {aiDrilldownSuggestion.reason} ({aiDrilldownSuggestion.next_step})
                        </p>
                      ) : null}
                      {aiRecommendations.length ? (
                        <ul className="aiRecommendationList">
                          {aiRecommendations.map((item, idx) => (
                            <li key={`rec-${idx}`} className="aiRecommendationItem">
                              <strong>{item.action}</strong> - {item.assumption} (Impact{" "}
                              {Number(item.expected_impact_pct || 0).toFixed(1)}%)
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </section>
                  ) : null}
                  {aiDashboardBlocks.length ? (
                    <div className="aiDashboardHtml">
                      {aiDashboardBlocks.map((block) => (
                        <div
                          key={block.id || `${block.title}-${block.insight_priority || 0}`}
                          dangerouslySetInnerHTML={{ __html: block.html || "" }}
                        />
                      ))}
                    </div>
                  ) : aiDashboardLoading ? (
                    <div className="reportEmpty muted" role="status" aria-live="polite">
                      Preparing dashboard stream...
                    </div>
                  ) : (
                    <div className="reportEmpty muted">
                      No AI dashboard generated for selected range yet. Adjust date range or switch to deterministic mode.
                    </div>
                  )}
                  {aiDashboardLoading && aiPendingCharts > 0 ? (
                    <div className="aiSkeletonGrid">
                      {Array.from({ length: aiPendingCharts }).map((_, idx) => (
                        <div key={`skeleton-${idx}`} className="aiSkeletonCard" />
                      ))}
                    </div>
                  ) : null}
                  {(aiDashboardData?.analytics_monthly || []).length ? (
                    <div className="historyTableWrap">
                      <table className="historyTable">
                        <thead>
                          <tr>
                            <th>Month</th>
                            <th className="right">Orders</th>
                            <th className="right">Revenue</th>
                            <th className="right">Avg Order Value</th>
                          </tr>
                        </thead>
                        <tbody>
                          {aiDashboardData.analytics_monthly.map((row) => (
                            <tr key={row.month}>
                              <td>{row.month}</td>
                              <td className="right">{row.orders || 0}</td>
                              <td className="right">{formatCurrency(row.revenue || 0)}</td>
                              <td className="right">{formatCurrency(row.avg_order_value || 0)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}
                </section>
              )}
            </section>
          ) : (
            <section id="main-panel-menu-management" role="tabpanel" aria-labelledby="main-tab-menu-management" className="card report">
              <h3>Menu Management {menuAdminLoading ? <span className="muted">(Refreshing...)</span> : null}</h3>
              <div className="menuSubSection">
                <h4>POS tax</h4>
                <p className="muted">Applies to new totals calculations and open orders (after save).</p>
                <div className="row menuAdminRow">
                  <label>
                    <span className="muted" style={{ marginRight: 8 }}>Rate (%)</span>
                    <input
                      type="text"
                      inputMode="decimal"
                      value={taxRateInput}
                      onChange={(e) => setTaxRateInput(e.target.value)}
                      style={{ maxWidth: 120 }}
                    />
                  </label>
                  <button type="button" onClick={saveTaxRate} disabled={taxRateSaving}>
                    {taxRateSaving ? "Saving..." : "Save tax rate"}
                  </button>
                </div>
              </div>
              <div className="menuAdminGrid">
                <section className="menuAdminSection">
                  <h4>Categories</h4>
                  <div className="row menuAdminRow">
                    <input
                      type="text"
                      placeholder="New category name"
                      value={newCategoryName}
                      onChange={(e) => setNewCategoryName(e.target.value)}
                    />
                    <button onClick={createCategory}>Add Category</button>
                  </div>
                  <div className="menuAdminList">
                    {menuAdminCategories.map((category) => (
                      <div key={category.id} className="menuAdminCard">
                        <div className="row">
                          <strong>{category.name}</strong>
                          <span className="muted">{category.item_count || 0} items</span>
                        </div>
                        <div className="row menuAdminActions">
                          <button onClick={() => renameCategory(category)}>Rename</button>
                          <button onClick={() => toggleCategoryVisibility(category)}>
                            {category.is_active ? "Disable" : "Enable"}
                          </button>
                          <button className="danger" onClick={() => deleteCategory(category)}>Delete</button>
                        </div>
                      </div>
                    ))}
                    {!menuAdminCategories.length && <div className="reportEmpty muted">No categories found.</div>}
                  </div>
                </section>

                <section className="menuAdminSection">
                  <h4>Items</h4>
                  <div className="menuSubSection">
                    <h5>Filter Items</h5>
                    <div className="row menuAdminRow">
                      <input
                        type="text"
                        placeholder="Search items"
                        value={menuSearch}
                        onChange={(e) => setMenuSearch(e.target.value)}
                      />
                      <select value={menuCategoryFilter} onChange={(e) => setMenuCategoryFilter(e.target.value)}>
                        <option value="">All categories</option>
                        {menuAdminCategories.map((category) => (
                          <option key={category.id} value={category.name}>
                            {category.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="row menuAdminRow">
                      <label className="menuInlineCheck">
                        <input
                          type="checkbox"
                          checked={menuIncludeInactive}
                          onChange={(e) => setMenuIncludeInactive(e.target.checked)}
                        />
                        <span>Show inactive items</span>
                      </label>
                      <div className="menuActionGroup">
                        <button onClick={resetMenuFilters}>Reset</button>
                        <button onClick={loadMenuManagementData}>Apply</button>
                      </div>
                    </div>
                  </div>

                  <div className="menuSubSection">
                    <h5>Add New Item</h5>
                    <div className="row menuAdminRow">
                      <input
                        type="text"
                        placeholder="Item name"
                        value={newItemName}
                        onChange={(e) => setNewItemName(e.target.value)}
                      />
                      <input
                        type="number"
                        min="1"
                        step="1"
                        placeholder="Price"
                        value={newItemPrice}
                        onChange={(e) => setNewItemPrice(e.target.value)}
                      />
                      <select value={newItemCategoryId} onChange={(e) => setNewItemCategoryId(e.target.value)}>
                        <option value="">Select category</option>
                        {menuAdminCategories.map((category) => (
                          <option key={category.id} value={category.id}>
                            {category.name}
                          </option>
                        ))}
                      </select>
                      <button className="primary" onClick={createMenuItem}>Add Item</button>
                    </div>
                  </div>
                  <div className="historyTableWrap">
                    <table className="historyTable">
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>Category</th>
                          <th className="right">Price</th>
                          <th>Status</th>
                          <th className="right">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {menuAdminItems.map((item) => (
                          <tr key={item.id}>
                            <td>{item.name}</td>
                            <td>{item.category}</td>
                            <td className="right">{formatCurrency(item.price || 0)}</td>
                            <td>{item.is_active ? "Active" : "Inactive"}</td>
                            <td className="right">
                              <div className="historyActions">
                                <button className="historyBillBtn" onClick={() => editMenuItem(item)}>Edit</button>
                                <button className="historyBillBtn" onClick={() => toggleItemVisibility(item)}>
                                  {item.is_active ? "Disable" : "Enable"}
                                </button>
                                <button className="historyDeleteBtn" onClick={() => deleteMenuItem(item)}>X</button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!menuAdminItems.length && <div className="reportEmpty muted">No menu items found.</div>}
                  </div>
                </section>
              </div>
            </section>
          )}

          {billPreview.open && billOrder && (
            <div
              className="billPreviewBackdrop"
              role="dialog"
              aria-modal="true"
              aria-label="Itemized bill preview"
              onClick={(e) => {
                if (e.target === e.currentTarget) closeItemizedBill();
              }}
            >
              <section className="billPreviewSheet">
                <div className="billHeading thermalHead">
                  <div className="billBrand">Aromaz Cafe</div>
                  <div className="billTitle">Itemized Bill</div>
                  <div className="muted thermalMeta">Contact: 9051584252</div>
                  <div className="muted thermalMeta">Table {billOrder.table_id || selectedTable}</div>
                  <div className="muted thermalMeta">Order {billOrder.id}</div>
                  <div className="muted thermalMeta">
                    Generated: {formatDateTime(billPreview.generatedAt)}
                  </div>
                </div>

                <div className="billItems thermalSection">
                  <div className="billColHead">
                    <span>Item</span>
                    <span>Amount</span>
                  </div>
                  {billItems.length ? (
                    billItems.map((item, idx) => (
                      <div key={`${item.name}-${idx}`} className="billItemRow">
                        <div className="billItemBody">
                          <div className="billItemName">
                            {item.name}
                          </div>
                          <div className="muted thermalMeta">
                            {item.qty || 1} x {formatCurrency(item.price || 0)}
                          </div>
                          <div className="muted">
                            {item.modifiers?.note ? `Note: ${item.modifiers.note}` : "No note"}
                            {item.modifiers?.less_sugar ? " | less sugar" : ""}
                            {item.modifiers?.no_ice ? " | no ice" : ""}
                          </div>
                        </div>
                        <strong>{formatCurrency((item.price || 0) * (item.qty || 1))}</strong>
                      </div>
                    ))
                  ) : (
                    <div className="reportEmpty muted">No served billable items available.</div>
                  )}
                </div>

                <div className="totals billTotals">
                  <div className="row">
                    <span>Items</span>
                    <strong>{billItemCount}</strong>
                  </div>
                  <div className="row">
                    <span>Subtotal</span>
                    <strong>{formatCurrency(billTotals.subtotal || 0)}</strong>
                  </div>
                  {billTotals.discount > 0.005 ? (
                    <div className="row">
                      <span>
                        Discount
                        {billImpliedDiscountPercent != null ? (
                          <span className="muted thermalMeta">
                            {" "}
                            ({billImpliedDiscountPercent}% of subtotal)
                          </span>
                        ) : null}
                      </span>
                      <strong>-{formatCurrency(billTotals.discount || 0)}</strong>
                    </div>
                  ) : null}
                  <div className="row">
                    <span>Tax</span>
                    <strong>{formatCurrency(billTotals.tax || 0)}</strong>
                  </div>
                  <div className="row">
                    <span>Total</span>
                    <strong>{formatCurrency(billTotals.total || 0)}</strong>
                  </div>
                </div>
                {activeOrder &&
                billOrder &&
                billOrder.id === activeOrder.id &&
                !["Paid", "Cancelled"].includes(billOrder.status) &&
                billItems.length > 0 ? (
                  <div className="billDiscountRow">
                    <p className="muted billDiscountHint">
                      Clear discount removes any reduction and recalculates subtotal, tax, and total. Use 10% / 20% / 30%
                      for a percent of subtotal.
                    </p>
                    <div className="billDiscountChips">
                      <button
                        type="button"
                        className="billDiscountClearBtn"
                        disabled={billDiscountBusy || !(billTotals.discount > 0.005)}
                        onClick={clearBillDiscount}
                      >
                        Clear discount
                      </button>
                      {[10, 20, 30].map((pct) => (
                        <button
                          key={pct}
                          type="button"
                          title={`Apply ${pct}% discount`}
                          disabled={billDiscountBusy}
                          onClick={() => applyBillDiscountPercent(pct)}
                        >
                          {pct}%
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
                <div className="billFooter muted">Thank you. Please visit again.</div>

                <div className="row ebillRow">
                  <input
                    type="email"
                    placeholder="Customer email"
                    value={billPreview.email}
                    onChange={(e) => setBillPreview((prev) => ({ ...prev, email: e.target.value }))}
                  />
                  <button onClick={sendEbillEmail} disabled={!billItems.length || billPreview.sending}>
                    {billPreview.sending ? "Sending..." : "Send eBill Email"}
                  </button>
                </div>
                {billPreview.status && <div className="muted ebillStatus">{billPreview.status}</div>}

                <div className="row billActions">
                  <button className="primary" onClick={printItemizedBill} disabled={!billItems.length}>
                    Print
                  </button>
                  <button ref={billCloseBtnRef} onClick={closeItemizedBill}>Close</button>
                </div>
              </section>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function calcTotals(items, discount = 0, taxRatePercent = 5) {
  const subtotal = items.reduce((sum, i) => {
    if (i.voided) return sum;
    return sum + i.price * (i.qty || 1);
  }, 0);
  const boundedDiscount = Math.min(Math.max(discount || 0, 0), subtotal);
  const rateRaw = Number(taxRatePercent);
  const rate = Number.isFinite(rateRaw) ? Math.min(Math.max(rateRaw, 0), 100) / 100 : 0.05;
  const tax = Math.round((subtotal - boundedDiscount) * rate * 100) / 100;
  const total = Math.round((subtotal - boundedDiscount + tax) * 100) / 100;
  return { subtotal, discount: boundedDiscount, tax, total };
}

function pendingQtyForItem(item) {
  if (!item || item.voided) return 0;
  const qty = Math.max(1, Number(item.qty || 1));
  const servedRaw = Number(item.served_qty || 0);
  const servedQty = Math.max(0, Math.min(Number.isFinite(servedRaw) ? servedRaw : 0, qty));
  return Math.max(qty - servedQty, 0);
}

function normalizeItemServiceState(item, status) {
  const qty = Math.max(1, Number(item?.qty || 1));
  const servedByStatus = ["Served", "Billed", "Paid"].includes(status);
  const hasServedQty = Object.prototype.hasOwnProperty.call(item || {}, "served_qty");
  const servedQtyRaw = hasServedQty
    ? Number(item?.served_qty || 0)
    : Object.prototype.hasOwnProperty.call(item || {}, "served")
      ? (item?.served ? qty : 0)
      : (servedByStatus && !item?.voided ? qty : 0);
  const servedQty = Math.max(0, Math.min(Number.isFinite(servedQtyRaw) ? servedQtyRaw : 0, qty));
  const served = !item?.voided && servedQty >= qty;
  return {
    ...item,
    qty,
    served_qty: servedQty,
    served,
    served_at: item?.served_at || null,
  };
}

function normalizeOrder(order) {
  const status = order?.status || "Open";
  const normalizedItems = (order?.items || []).map((item) => normalizeItemServiceState(item, status));
  const totals = order.totals || { subtotal: 0, discount: 0, tax: 0, total: 0 };
  let discount = 0;
  if (order?.discount != null && order.discount !== "") {
    discount = Number(order.discount) || 0;
  } else {
    discount = Number(totals.discount) || 0;
  }
  if (!Number.isFinite(discount) || discount < 0) {
    discount = 0;
  }
  return {
    id: order.id,
    status,
    items: normalizedItems,
    discount,
    totals,
  };
}

function getNextStatus(status) {
  const idx = STATUS_PIPELINE.indexOf(status);
  if (idx < 0 || idx >= STATUS_PIPELINE.length - 1) {
    return "";
  }
  return STATUS_PIPELINE[idx + 1];
}

function statusClassName(status) {
  if (status === "Open") return "open";
  if (status === "SentToKitchen") return "billed";
  if (status === "Served") return "billed";
  if (status === "Billed") return "billed";
  if (status === "Paid") return "paid";
  if (status === "Cancelled") return "cancelled";
  return "neutral";
}

function statusLabel(status) {
  if (status === "SentToKitchen") return "Served";
  return status;
}

function parseTernaryBoolean(input, fallback) {
  if (input === null) return fallback;
  const normalized = String(input).trim().toLowerCase();
  if (!normalized) return fallback;
  if (["y", "yes", "true", "1"].includes(normalized)) return true;
  if (["n", "no", "false", "0"].includes(normalized)) return false;
  return fallback;
}

function formatCurrency(value) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(
    Number(value || 0)
  );
}

function formatDateTime(value) {
  if (!value) return "-";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "-";
  return dt.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
}
