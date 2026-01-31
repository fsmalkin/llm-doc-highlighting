const DEFAULT_QUESTION = "What is the date of visit?";
const DEFAULT_DOC = "./assets/Physician_Report_Scanned-ocr.pdf";

const statusEl = document.getElementById("status");
const answerEl = document.getElementById("answer");
const sourceTextEl = document.getElementById("sourceText");
const sourceMetaEl = document.getElementById("sourceMeta");
const whySummaryEl = document.getElementById("whySummary");
const llmRequestEl = document.getElementById("llmRequest");
const llmResponseEl = document.getElementById("llmResponse");
const valueTypeIndicatorEl = document.getElementById("valueTypeIndicator");
const debugEl = document.getElementById("debug");
const questionEl = document.getElementById("question");
const promptPresetEl = document.getElementById("promptPreset");
const valueTypeEl = document.getElementById("valueType");
const keyStatusEl = document.getElementById("keyStatus");
const railsStatusEl = document.getElementById("railsStatus");
const railsSourceEl = document.getElementById("railsSource");
const ocrStatusEl = document.getElementById("ocrStatus");
const cacheStatusEl = document.getElementById("cacheStatus");
const modelStatusEl = document.getElementById("modelStatus");
const systemStatusEl = document.getElementById("systemStatus");
const statusDetailsEl = document.getElementById("statusDetails");
const tabIndexedEl = document.getElementById("tabIndexed");
const tabRawEl = document.getElementById("tabRaw");

const btnAsk = document.getElementById("btnAsk");
const btnClear = document.getElementById("btnClear");

let viewerInstance = null;
let annotationManager = null;
let documentViewer = null;
let Core = null;
let Annotations = null;
let cacheReady = false;
let preparing = false;
let preparePromise = null;
let mode = "raw";

function setStatus(msg, kind) {
  statusEl.textContent = String(msg || "");
  statusEl.style.color = kind === "ok" ? "#7ee787" : kind === "bad" ? "#ff7b72" : "#aab3c0";
}

function setAnswer(text) {
  answerEl.textContent = text ? String(text) : "-";
}

function setSource(text, meta) {
  sourceTextEl.textContent = text ? String(text) : "-";
  sourceMetaEl.textContent = meta ? String(meta) : "-";
}

function setWhy(text) {
  if (!whySummaryEl) return;
  whySummaryEl.textContent = text ? String(text) : "-";
}

function setValueTypeIndicator(text) {
  if (!valueTypeIndicatorEl) return;
  if (!text) {
    valueTypeIndicatorEl.hidden = true;
    valueTypeIndicatorEl.textContent = "";
    return;
  }
  valueTypeIndicatorEl.hidden = false;
  valueTypeIndicatorEl.textContent = String(text);
}

function setLlmLog(trace) {
  if (!llmRequestEl || !llmResponseEl) return;
  if (!trace) {
    llmRequestEl.textContent = "-";
    llmResponseEl.textContent = "-";
    return;
  }
  if (trace.pass1 || trace.pass2) {
    llmRequestEl.textContent = JSON.stringify({ pass1: trace.pass1?.request, pass2: trace.pass2?.request }, null, 2);
    llmResponseEl.textContent = JSON.stringify(
      { pass1: trace.pass1?.response, pass2: trace.pass2?.response, window: trace.pass2?.window },
      null,
      2
    );
    return;
  }
  const req = trace.request || {};
  const resp = trace.response || {};
  llmRequestEl.textContent = JSON.stringify(req, null, 2);
  if (typeof resp === "string") {
    llmResponseEl.textContent = resp;
  } else {
    llmResponseEl.textContent = JSON.stringify(resp, null, 2);
  }
}

function setDebug(obj) {
  debugEl.textContent = obj ? JSON.stringify(obj, null, 2) : "";
}

function setBadge(el, text, kind) {
  if (!el) return;
  el.textContent = text || "-";
  el.classList.remove("good", "bad", "warn");
  if (kind) el.classList.add(kind);
}

function setSystemStatus(text, kind, openDetails) {
  if (systemStatusEl) {
    setBadge(systemStatusEl, text, kind);
  }
  if (statusDetailsEl && typeof openDetails === "boolean") {
    statusDetailsEl.open = openDetails;
  }
}

async function getJson(url) {
  const res = await fetch(url, { method: "GET" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    const msg = data.error || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    const msg = data.error || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

function normalizeBool(value) {
  return value === true || value === "1" || value === 1;
}

function clampText(text, maxLen) {
  const raw = String(text || "");
  if (raw.length <= maxLen) return raw;
  return `${raw.slice(0, maxLen)}...`;
}

function buildWhySummary(data) {
  const citation = data?.citation || {};
  const span = data?.span || {};
  const mapped = data?.mapped || {};
  const parts = [];

  if (citation.start_token != null && citation.end_token != null) {
    parts.push(`Tokens: ${citation.start_token}-${citation.end_token}`);
  }
  const lineRange = span?.line_range || {};
  if (lineRange.start_line_no != null && lineRange.end_line_no != null) {
    parts.push(`Lines: ${lineRange.start_line_no}-${lineRange.end_line_no}`);
  }
  const wordIds = Array.isArray(mapped.word_ids) ? mapped.word_ids : [];
  if (wordIds.length) {
    parts.push(`Word ids: ${wordIds.length}`);
  }
  const pages = Array.isArray(mapped.pages) ? mapped.pages : [];
  const pageNums = pages.map((p) => p?.page).filter(Boolean);
  if (pageNums.length) {
    parts.push(`Pages: ${pageNums.join(", ")}`);
  }
  const spanText = citation.substr;
  if (spanText) {
    parts.push(`Span text: "${clampText(spanText, 200)}"`);
  }

  return parts.length ? parts.join("\n") : "-";
}

function updateSystemStatus(state) {
  const {
    keyPresent,
    railsRequired,
    railsOk,
    cacheReady: isCacheReady,
    ocrEnabled,
    model,
    preparing: isPreparing,
  } = state || {};

  if (isPreparing) {
    setSystemStatus("preparing...", "warn", false);
    return;
  }

  let hasError = false;
  let hasWarn = false;

  if (!keyPresent) hasError = true;
  if (railsRequired && !railsOk) hasError = true;
  if (!isCacheReady && !isPreparing) hasWarn = true;
  if (!ocrEnabled) hasWarn = true;
  if (!model) hasWarn = true;

  if (hasError) {
    setSystemStatus("setup required", "bad", true);
  } else if (hasWarn) {
    setSystemStatus("needs attention", "warn", false);
  } else {
    setSystemStatus("ready", "good", false);
  }
}

async function refreshStatus() {
  try {
    const data = await getJson("/api/status");
    const keyPresent = normalizeBool(data?.openai_key_present);
    setBadge(keyStatusEl, keyPresent ? "present" : "missing", keyPresent ? "good" : "bad");

    const railsRequired = normalizeBool(data?.rails_required);
    const railsOk = normalizeBool(data?.rails_ok);
    setBadge(
      railsStatusEl,
      railsOk ? (railsRequired ? "required ok" : "ok") : railsRequired ? "required" : "optional",
      railsOk ? "good" : railsRequired ? "bad" : "warn"
    );
    const railsSource = data?.rails_source || "-";
    const railsSourceKind = String(railsSource).startsWith("vision") ? "good" : "warn";
    setBadge(railsSourceEl, railsSource, railsSourceKind);

    const ocrEnabled = normalizeBool(data?.ocr_enabled);
    setBadge(ocrStatusEl, ocrEnabled ? "enabled" : "off", ocrEnabled ? "good" : "warn");

    cacheReady = normalizeBool(data?.cache_ready);
    setBadge(cacheStatusEl, cacheReady ? "ready" : "missing", cacheReady ? "good" : "warn");

    const model = data?.model || "-";
    setBadge(modelStatusEl, model, "good");

    setDebug(data);
    updateSystemStatus({
      keyPresent,
      railsRequired,
      railsOk,
      cacheReady,
      ocrEnabled,
      model,
      preparing,
    });
    return data;
  } catch (err) {
    const isFile = window.location.protocol === "file:";
    if (isFile) {
      setStatus("Status API unreachable. Open the demo server URL (not a file URL).", "bad");
    } else {
      setStatus(`Status API error: ${err.message}`, "bad");
    }
    setBadge(keyStatusEl, "unknown", "warn");
    setBadge(railsStatusEl, "unknown", "warn");
    setBadge(railsSourceEl, "unknown", "warn");
    setBadge(ocrStatusEl, "unknown", "warn");
    setBadge(cacheStatusEl, "unknown", "warn");
    setBadge(modelStatusEl, "unknown", "warn");
    setDebug({ error: err.message });
    cacheReady = false;
    setSystemStatus("status unavailable", "warn", false);
    return null;
  }
}

function quadToApryseQuad(CoreObj, q) {
  const nums = (q || []).map((v) => Number(v));
  if (nums.length !== 8 || nums.some((v) => Number.isNaN(v))) return null;
  const [TLx, TLy, BLx, BLy, TRx, TRy, BRx, BRy] = nums;
  return new CoreObj.Math.Quad(BLx, BLy, BRx, BRy, TRx, TRy, TLx, TLy);
}

function clearHighlights() {
  if (!annotationManager) return;
  const existing = annotationManager.getAnnotationsList?.() || [];
  for (const a of existing) {
    try {
      if (a?.getCustomData?.("demo_hl") === "1") {
        annotationManager.deleteAnnotation?.(a, false, true);
      }
    } catch {}
  }
}

function renderHighlights(pages) {
  if (!annotationManager || !Annotations || !Core) return null;
  clearHighlights();

  const byPage = new Map();
  for (const pg of pages || []) {
    const pageNo = Number(pg?.page || 0);
    const lineBoxes = Array.isArray(pg?.line_bboxes_abs) ? pg.line_bboxes_abs : [];
    const quads = Array.isArray(pg?.word_quads_abs) ? pg.word_quads_abs : [];
    if (!pageNo || (!lineBoxes.length && !quads.length)) continue;
    if (!byPage.has(pageNo)) byPage.set(pageNo, { lineBoxes: [], quads: [] });
    if (lineBoxes.length) {
      byPage.get(pageNo).lineBoxes.push(...lineBoxes);
    } else {
      byPage.get(pageNo).quads.push(...quads);
    }
  }

  const pagesSorted = Array.from(byPage.keys()).sort((a, b) => a - b);
  if (!pagesSorted.length) return null;

  let firstAnn = null;
  for (const pageNo of pagesSorted) {
    const hl = new Annotations.TextHighlightAnnotation();
    hl.PageNumber = pageNo;
    const payload = byPage.get(pageNo);
    if (payload.lineBoxes.length) {
      hl.Quads = payload.lineBoxes
        .map((b) => {
          const [x0, y0, x1, y1] = (b || []).map((v) => Number(v));
          if ([x0, y0, x1, y1].some((v) => Number.isNaN(v))) return null;
          const TLx = x0;
          const TLy = y1;
          const BLx = x0;
          const BLy = y0;
          const TRx = x1;
          const TRy = y1;
          const BRx = x1;
          const BRy = y0;
          return new Core.Math.Quad(BLx, BLy, BRx, BRy, TRx, TRy, TLx, TLy);
        })
        .filter(Boolean);
    } else {
      hl.Quads = payload.quads.map((q) => quadToApryseQuad(Core, q)).filter(Boolean);
    }
    hl.Color = new Annotations.Color(122, 162, 247);
    hl.Opacity = 0.45;
    hl.setCustomData?.("demo_hl", "1");
    annotationManager.addAnnotation(hl);
    annotationManager.redrawAnnotation(hl);
    firstAnn = firstAnn || hl;
  }

  return { firstAnn, pages: pagesSorted };
}

async function initViewer() {
  const webviewerPath = new URL("/webviewer", window.location.href).href.replace(/\/$/, "");
  const initialDoc = new URL(DEFAULT_DOC, window.location.href).href;

  viewerInstance = await WebViewer(
    {
      path: webviewerPath,
      initialDoc,
      fullAPI: true,
    },
    document.getElementById("wv")
  );

  Core = viewerInstance.Core;
  const UI = viewerInstance.UI;
  annotationManager = Core.annotationManager;
  documentViewer = Core.documentViewer;
  Annotations = Core.Annotations;

  if (documentViewer?.addEventListener) {
    documentViewer.addEventListener("documentLoaded", () => {
      if (UI?.setZoomLevel) {
        UI.setZoomLevel(1);
      } else if (documentViewer?.setZoomLevel) {
        documentViewer.setZoomLevel(1);
      }
    });
  }

  if (annotationManager?.setReadOnly) {
    annotationManager.setReadOnly(true);
  }
  if (documentViewer?.setReadOnly) {
    documentViewer.setReadOnly(true);
  }

  if (UI?.setHeaderItems) {
    UI.setHeaderItems((header) => {
      const items = header.getItems?.() || [];
      for (const item of items) {
        header.delete?.(item);
      }
    });
  }

  if (UI?.disableFeatures) {
    try {
      UI.disableFeatures([
        "Annotations",
        "AnnotationEdit",
        "AnnotationTools",
        "TextSelection",
        "Copy",
        "Search",
        "NotesPanel",
        "Outline",
        "ThumbnailsPanel",
        "LeftPanel",
        "RightPanel",
        "Ribbons",
        "Download",
        "Print",
        "Fullscreen",
        "ContentEdit",
        "Measurement",
        "MultiTab",
      ]);
    } catch {}
  }

  if (UI?.disableElements) {
    try {
      UI.disableElements([
        "header",
        "toolsHeader",
        "menuButton",
        "searchButton",
        "leftPanel",
        "rightPanel",
        "searchPanel",
        "notesPanel",
        "outlinePanel",
        "thumbnailsPanel",
        "rubberStampPanel",
        "redactionPanel",
        "signaturePanel",
        "stylePopup",
        "contextMenuPopup",
        "annotationPopup",
        "textPopup",
        "downloadButton",
        "printButton",
        "fullscreenButton",
        "viewControlsButton",
        "selectToolButton",
        "panToolButton",
        "textSelectButton",
        "annotateButton",
        "annotationToolsButton",
        "zoomOverlayButton",
        "pageNavOverlay",
        "pageNav",
        "pageNumberInput",
        "fitToPageButton",
        "fitToWidthButton",
        "rotateClockwiseButton",
        "rotateCounterClockwiseButton",
        "eraserToolButton",
        "editToolButton",
        "formsToolButton",
        "measureToolButton",
        "searchOverlay",
        "searchPanel",
        "contextMenuPopup",
        "annotationPopup",
        "textPopup",
        "annotationStylePopup",
      ]);
    } catch {}
  }
}

async function prepareCache() {
  setStatus("Preparing cache...", "");
  preparing = true;
  updateSystemStatus({ preparing: true });
  try {
    const data = await postJson("/api/preprocess", {});
    setStatus(`Cache ready. doc_hash=${data.doc_hash}`, "ok");
    setDebug(data);
    cacheReady = true;
    await refreshStatus();
    return true;
  } catch (err) {
    setStatus(`Preprocess failed: ${err.message}`, "bad");
    throw err;
  } finally {
    preparing = false;
  }
}

function ensurePrepared() {
  if (cacheReady) {
    return Promise.resolve(true);
  }
  if (preparePromise) {
    return preparePromise;
  }
  preparePromise = prepareCache().finally(() => {
    preparePromise = null;
  });
  return preparePromise;
}

async function askQuestion() {
  const q = String(questionEl.value || "").trim();
  if (!q) {
    setStatus("Please enter a question.", "bad");
    return;
  }
  const valueType = String(valueTypeEl?.value || "Auto");

  setStatus("Running LLM resolver...", "");
  btnAsk.disabled = true;
  setAnswer("-");
  setSource("-", "-");
  setWhy("-");
  setLlmLog(null);
  setValueTypeIndicator(null);

  try {
    const status = await refreshStatus();
    if (!status?.cache_ready) {
      await ensurePrepared();
    }
    const endpoint = mode === "raw" ? "/api/ask_raw" : "/api/ask";
    const data = await postJson(endpoint, { question: q, value_type: valueType });
    const answer = data?.answer || "";
    const citation = data?.citation || {};
    const pages = data?.mapped?.pages || [];
    const valueTypeResponse = data?.value_type;
    const valueTypeRequested = String(valueTypeEl?.value || "Auto");
    const valueTypeInferred = data?.meta?.value_type_inferred === true || valueTypeRequested === "Auto";

    setAnswer(answer || "(no answer)");
    const sourceText = data?.source || citation.substr || "(no citation)";
    const metaParts = [];
    if (citation.start_token != null && citation.end_token != null) {
      metaParts.push(`tokens ${citation.start_token}-${citation.end_token}`);
    }
    if (valueTypeResponse) {
      metaParts.push(`type ${valueTypeResponse}`);
    }
    if (Array.isArray(pages) && pages.length) {
      const pnums = pages.map((p) => p.page).filter(Boolean);
      if (pnums.length) metaParts.push(`pages ${pnums.join(", ")}`);
    }
    setSource(sourceText, metaParts.join(" | ") || "-");
    setWhy(buildWhySummary(data));
    setLlmLog(data?.trace);
    setDebug(data);
    const typeLabelRaw = valueTypeResponse || valueTypeRequested || "Free-text";
    const typeLabel = valueTypeRequested === "Auto" ? `Type: ${typeLabelRaw} (auto)` : `Type: ${typeLabelRaw}`;
    setValueTypeIndicator(typeLabel);

    const result = renderHighlights(pages);
    if (result && documentViewer) {
      documentViewer.setCurrentPage?.(result.pages[0]);
      requestAnimationFrame(() => {
        try {
          const dvJump = documentViewer.jumpToAnnotation;
          if (typeof dvJump === "function" && result.firstAnn) {
            dvJump.call(documentViewer, result.firstAnn, { animate: true });
          } else if (typeof documentViewer.scrollToAnnotation === "function" && result.firstAnn) {
            documentViewer.scrollToAnnotation(result.firstAnn, { animate: true });
          }
        } catch {}
      });
    }

    setStatus("Done.", "ok");
    await refreshStatus();
  } catch (err) {
    setStatus(`Ask failed: ${err.message}`, "bad");
    await refreshStatus();
  } finally {
    btnAsk.disabled = false;
  }
}

btnAsk.addEventListener("click", () => askQuestion());
btnClear.addEventListener("click", () => {
  clearHighlights();
  setStatus("Cleared highlights.", "ok");
});

function setMode(nextMode) {
  mode = nextMode === "raw" ? "raw" : "indexed";
  tabIndexedEl?.classList.toggle("active", mode === "indexed");
  tabRawEl?.classList.toggle("active", mode === "raw");
  setLlmLog(null);
  setWhy("-");
  setSource("-", "-");
  setAnswer("-");
}

tabIndexedEl?.addEventListener("click", () => setMode("indexed"));
tabRawEl?.addEventListener("click", () => setMode("raw"));
promptPresetEl?.addEventListener("change", () => {
  const nextValue = String(promptPresetEl.value || "").trim();
  if (!nextValue) return;
  questionEl.value = nextValue;
  questionEl.focus();
});

questionEl.value = DEFAULT_QUESTION;
setAnswer("-");
setSource("-", "-");
setWhy("-");
setLlmLog(null);
setValueTypeIndicator(null);
setDebug(null);
setMode("raw");

initViewer()
  .then(() => {
    setStatus("Viewer ready.", "ok");
    return null;
  })
  .catch((err) => setStatus(`Viewer failed: ${err.message}`, "bad"));

refreshStatus().then((status) => {
  if (!status?.cache_ready) {
    ensurePrepared().catch(() => {});
  }
});
