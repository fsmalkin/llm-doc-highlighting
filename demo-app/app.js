const DEFAULT_QUESTION = "What is the date of visit?";
const DEFAULT_DOC = "./assets/Physician_Report_Scanned.pdf";

const statusEl = document.getElementById("status");
const answerEl = document.getElementById("answer");
const sourceTextEl = document.getElementById("sourceText");
const sourceMetaEl = document.getElementById("sourceMeta");
const whySummaryEl = document.getElementById("whySummary");
const llmRequestEl = document.getElementById("llmRequest");
const llmResponseEl = document.getElementById("llmResponse");
const debugEl = document.getElementById("debug");
const questionEl = document.getElementById("question");
const keyStatusEl = document.getElementById("keyStatus");
const railsStatusEl = document.getElementById("railsStatus");
const ocrStatusEl = document.getElementById("ocrStatus");
const cacheStatusEl = document.getElementById("cacheStatus");
const modelStatusEl = document.getElementById("modelStatus");
const toggleOcrEl = document.getElementById("toggleOcr");
const toggleAutoPrepareEl = document.getElementById("toggleAutoPrepare");

const btnPrepare = document.getElementById("btnPrepare");
const btnAsk = document.getElementById("btnAsk");
const btnClear = document.getElementById("btnClear");
const stepPrepareEl = document.getElementById("stepPrepare");
const stepAskEl = document.getElementById("stepAsk");

let viewerInstance = null;
let annotationManager = null;
let documentViewer = null;
let Core = null;
let Annotations = null;
let cacheReady = false;
let preparing = false;

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

function setLlmLog(trace) {
  if (!llmRequestEl || !llmResponseEl) return;
  if (!trace) {
    llmRequestEl.textContent = "-";
    llmResponseEl.textContent = "-";
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

function setStepState(el, state) {
  if (!el) return;
  el.classList.remove("active", "done");
  if (state) el.classList.add(state);
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

async function refreshStatus() {
  try {
    const ocrParam = toggleOcrEl?.checked ? "1" : "0";
    const data = await getJson(`/api/status?ocr=${ocrParam}`);
    const keyPresent = normalizeBool(data?.openai_key_present);
    setBadge(keyStatusEl, keyPresent ? "present" : "missing", keyPresent ? "good" : "bad");

    const railsRequired = normalizeBool(data?.rails_required);
    const railsOk = normalizeBool(data?.rails_ok);
    setBadge(
      railsStatusEl,
      railsOk ? (railsRequired ? "required ok" : "ok") : railsRequired ? "required" : "optional",
      railsOk ? "good" : railsRequired ? "bad" : "warn"
    );

    const ocrEnabled = normalizeBool(data?.ocr_enabled);
    setBadge(ocrStatusEl, ocrEnabled ? "enabled" : "off", ocrEnabled ? "good" : "warn");

    const cacheReady = normalizeBool(data?.cache_ready);
    setBadge(cacheStatusEl, cacheReady ? "ready" : "missing", cacheReady ? "good" : "warn");
    updateFlow(cacheReady);

    const model = data?.model || "-";
    setBadge(modelStatusEl, model, "good");

    setDebug(data);
    return data;
  } catch (err) {
    const isFile = window.location.protocol === "file:";
    if (isFile) {
      setStatus("Status API unreachable. Open http://127.0.0.1:8000/ (not a file URL).", "bad");
    } else {
      setStatus(`Status API error: ${err.message}`, "bad");
    }
    setBadge(keyStatusEl, "unknown", "warn");
    setBadge(railsStatusEl, "unknown", "warn");
    setBadge(ocrStatusEl, "unknown", "warn");
    setBadge(cacheStatusEl, "unknown", "warn");
    setBadge(modelStatusEl, "unknown", "warn");
    setDebug({ error: err.message });
    updateFlow(false);
    return null;
  }
}

function updateFlow(isReady) {
  cacheReady = !!isReady;
  if (cacheReady) {
    setStepState(stepPrepareEl, "done");
    setStepState(stepAskEl, "active");
    btnAsk.disabled = false;
    btnAsk.classList.add("primary");
    btnPrepare.classList.remove("primary");
  } else {
    setStepState(stepPrepareEl, "active");
    setStepState(stepAskEl, "");
    const autoPrep = !!toggleAutoPrepareEl?.checked;
    btnAsk.disabled = !autoPrep;
    btnPrepare.classList.add("primary");
    btnAsk.classList.remove("primary");
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
    const quads = Array.isArray(pg?.word_quads_abs) ? pg.word_quads_abs : [];
    if (!pageNo || !quads.length) continue;
    if (!byPage.has(pageNo)) byPage.set(pageNo, []);
    byPage.get(pageNo).push(...quads);
  }

  const pagesSorted = Array.from(byPage.keys()).sort((a, b) => a - b);
  if (!pagesSorted.length) return null;

  let firstAnn = null;
  for (const pageNo of pagesSorted) {
    const hl = new Annotations.TextHighlightAnnotation();
    hl.PageNumber = pageNo;
    hl.Quads = byPage
      .get(pageNo)
      .map((q) => quadToApryseQuad(Core, q))
      .filter(Boolean);
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
  annotationManager = Core.annotationManager;
  documentViewer = Core.documentViewer;
  Annotations = Core.Annotations;
}

async function prepareCache() {
  if (preparing) return;
  setStatus("Preparing cache...", "");
  preparing = true;
  btnPrepare.disabled = true;
  try {
    const data = await postJson("/api/preprocess", { ocr: toggleOcrEl?.checked ? 1 : 0 });
    setStatus(`Cache ready. doc_hash=${data.doc_hash}`, "ok");
    setDebug(data);
    await refreshStatus();
  } catch (err) {
    setStatus(`Preprocess failed: ${err.message}`, "bad");
  } finally {
    btnPrepare.disabled = false;
    preparing = false;
  }
}

async function askQuestion() {
  const q = String(questionEl.value || "").trim();
  if (!q) {
    setStatus("Please enter a question.", "bad");
    return;
  }

  setStatus("Running LLM resolver...", "");
  btnAsk.disabled = true;
  setAnswer("-");
  setSource("-", "-");
  setWhy("-");
  setLlmLog(null);

  try {
    if (toggleAutoPrepareEl?.checked) {
      const status = await refreshStatus();
      if (!status?.cache_ready) {
        await prepareCache();
      }
    }
    const data = await postJson("/api/ask", {
      question: q,
      ocr: toggleOcrEl?.checked ? 1 : 0,
    });
    const answer = data?.answer || "";
    const citation = data?.citation || {};
    const pages = data?.mapped?.pages || [];

    setAnswer(answer || "(no answer)");
    const sourceText = citation.substr || "(no citation)";
    const metaParts = [];
    if (citation.start_token != null && citation.end_token != null) {
      metaParts.push(`tokens ${citation.start_token}-${citation.end_token}`);
    }
    if (Array.isArray(pages) && pages.length) {
      const pnums = pages.map((p) => p.page).filter(Boolean);
      if (pnums.length) metaParts.push(`pages ${pnums.join(", ")}`);
    }
    setSource(sourceText, metaParts.join(" | ") || "-");
    setWhy(buildWhySummary(data));
    setLlmLog(data?.trace);
    setDebug(data);

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

btnPrepare.addEventListener("click", () => prepareCache());
btnAsk.addEventListener("click", () => askQuestion());
btnClear.addEventListener("click", () => {
  clearHighlights();
  setStatus("Cleared highlights.", "ok");
});
toggleOcrEl?.addEventListener("change", () => refreshStatus());
toggleAutoPrepareEl?.addEventListener("change", () => updateFlow(cacheReady));

questionEl.value = DEFAULT_QUESTION;
setAnswer("-");
setSource("-", "-");
setWhy("-");
setLlmLog(null);
setDebug(null);

initViewer()
  .then(() => setStatus("Viewer ready.", "ok"))
  .catch((err) => setStatus(`Viewer failed: ${err.message}`, "bad"));

refreshStatus().then((status) => {
  if (toggleAutoPrepareEl?.checked && !status?.cache_ready) {
    prepareCache();
  }
});
