const DEFAULT_DOC = "./assets/Physician_Report_Scanned-ocr.pdf";

const evalRunSelectEl = document.getElementById("evalRunSelect");
const evalRunMetaEl = document.getElementById("evalRunMeta");
const docSearchEl = document.getElementById("docSearch");
const docSelectEl = document.getElementById("docSelect");
const exampleSelectEl = document.getElementById("exampleSelect");
const docListEl = document.getElementById("docList");

const evalFieldLabelEl = document.getElementById("evalFieldLabel");
const evalExpectedValueEl = document.getElementById("evalExpectedValue");
const evalAnswerRawEl = document.getElementById("evalAnswerRaw");
const evalAnswerIndexedEl = document.getElementById("evalAnswerIndexed");

const metricRawIouEl = document.getElementById("metricRawIou");
const metricRawPrecisionEl = document.getElementById("metricRawPrecision");
const metricRawRecallEl = document.getElementById("metricRawRecall");
const metricRawPass2El = document.getElementById("metricRawPass2");

const metricIndexedIouEl = document.getElementById("metricIndexedIou");
const metricIndexedPrecisionEl = document.getElementById("metricIndexedPrecision");
const metricIndexedRecallEl = document.getElementById("metricIndexedRecall");
const metricIndexedPass2El = document.getElementById("metricIndexedPass2");

const showGtEl = document.getElementById("showGt");
const showRawEl = document.getElementById("showRaw");
const showIndexedEl = document.getElementById("showIndexed");
const toggleABEl = document.getElementById("toggleAB");

let viewerInstance = null;
let documentViewer = null;
let annotationManager = null;
let Annotations = null;
let Core = null;

let runData = null;
let docIndex = [];
let currentDocId = null;
let pendingOverlay = null;

function setText(el, text) {
  if (!el) return;
  el.textContent = text ? String(text) : "-";
}

function setBadge(el, value) {
  if (!el) return;
  el.textContent = value == null || value === "" ? "-" : String(value);
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

function toFixed(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return num.toFixed(2);
}

function updateMetrics(rawMetrics, indexedMetrics) {
  setBadge(metricRawIouEl, toFixed(rawMetrics?.word_iou));
  setBadge(metricRawPrecisionEl, toFixed(rawMetrics?.precision));
  setBadge(metricRawRecallEl, toFixed(rawMetrics?.recall));
  setBadge(metricRawPass2El, rawMetrics?.used_pass2 ? "yes" : "no");

  setBadge(metricIndexedIouEl, toFixed(indexedMetrics?.word_iou));
  setBadge(metricIndexedPrecisionEl, toFixed(indexedMetrics?.precision));
  setBadge(metricIndexedRecallEl, toFixed(indexedMetrics?.recall));
  setBadge(metricIndexedPass2El, indexedMetrics?.used_pass2 ? "yes" : "no");
}

function clearOverlay() {
  if (!annotationManager) return;
  const existing = Array.from(annotationManager.getAnnotationsList?.() || []);
  for (const ann of existing) {
    try {
      if (ann?.getCustomData?.("eval_hl") === "1") {
        annotationManager.deleteAnnotation?.(ann, false, true);
      }
    } catch {}
  }
}

function addRect(pageNo, bbox, color, tag) {
  if (!annotationManager || !Annotations) return null;
  const nums = (bbox || []).map((v) => Number(v));
  if (nums.length !== 4 || nums.some((v) => Number.isNaN(v))) return null;
  let [x0, y0, x1, y1] = nums;
  if (x0 > x1) [x0, x1] = [x1, x0];
  if (y0 > y1) [y0, y1] = [y1, y0];
  const rect = new Annotations.RectangleAnnotation();
  rect.PageNumber = Number(pageNo || 1);
  rect.X = x0;
  rect.Y = y0;
  rect.Width = Math.max(0.5, x1 - x0);
  rect.Height = Math.max(0.5, y1 - y0);
  rect.StrokeColor = color;
  rect.StrokeThickness = 2;
  rect.NoFill = true;
  rect.setCustomData?.("eval_hl", "1");
  rect.setCustomData?.("eval_tag", tag || "");
  annotationManager.addAnnotation(rect);
  annotationManager.redrawAnnotation(rect);
  return rect;
}

function renderOverlay(gtBoxes, rawBoxes, indexedBoxes, pageNo) {
  if (!annotationManager || !Annotations) return;
  clearOverlay();
  const green = new Annotations.Color(126, 231, 135);
  const red = new Annotations.Color(255, 123, 114);
  const blue = new Annotations.Color(122, 162, 247);
  const amber = new Annotations.Color(249, 226, 175);

  const showGt = showGtEl ? showGtEl.checked : true;
  const showRaw = showRawEl ? showRawEl.checked : true;
  const showIndexed = showIndexedEl ? showIndexedEl.checked : true;
  const abState = showRaw && showIndexed ? "on" : !showRaw && !showIndexed ? "off" : "partial";

  const created = [];
  if (showGt) {
    for (const b of gtBoxes || []) {
      const ann = addRect(pageNo, b, green, "gt");
      if (ann) created.push(ann);
    }
  }
  if (abState === "on") {
    const merged = dedupeBoxes([...(rawBoxes || []), ...(indexedBoxes || [])]);
    for (const b of merged) {
      const ann = addRect(pageNo, b, amber, "ab");
      if (ann) created.push(ann);
    }
  } else if (abState === "partial") {
    if (showRaw) {
      for (const b of rawBoxes || []) {
        const ann = addRect(pageNo, b, red, "raw");
        if (ann) created.push(ann);
      }
    }
    if (showIndexed) {
      for (const b of indexedBoxes || []) {
        const ann = addRect(pageNo, b, blue, "indexed");
        if (ann) created.push(ann);
      }
    }
  }
  return created;
}

function collectBoxes(methodData) {
  const pages = methodData?.mapped?.pages || [];
  const boxes = [];
  for (const pg of pages) {
    const quads = pg?.word_quads_abs || [];
    for (const q of quads) {
      const nums = (q || []).map((v) => Number(v));
      if (nums.length !== 8 || nums.some((v) => Number.isNaN(v))) continue;
      const xs = [nums[0], nums[2], nums[4], nums[6]];
      const ys = [nums[1], nums[3], nums[5], nums[7]];
      boxes.push([Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]);
    }
  }
  return boxes;
}

function normalizeBoxes(boxes) {
  const out = (boxes || []).map((b) =>
    (b || []).map((v) => {
      const num = Number(v);
      if (!Number.isFinite(num)) return 0;
      return Math.round(num * 100) / 100;
    })
  );
  return out.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
}

function dedupeBoxes(boxes) {
  const norm = normalizeBoxes(boxes);
  const seen = new Set();
  const out = [];
  for (const b of norm) {
    const key = JSON.stringify(b);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(b);
  }
  return out;
}

function syncABMaster() {
  if (!toggleABEl) return;
  const a = showRawEl ? showRawEl.checked : false;
  const b = showIndexedEl ? showIndexedEl.checked : false;
  if (a && b) {
    toggleABEl.checked = true;
    toggleABEl.indeterminate = false;
  } else if (!a && !b) {
    toggleABEl.checked = false;
    toggleABEl.indeterminate = false;
  } else {
    toggleABEl.checked = false;
    toggleABEl.indeterminate = true;
  }
}

function focusOnAnnotations(annotations, pageNo) {
  if (!annotations || !annotations.length || !viewerInstance || !documentViewer) return;
  const first = annotations[0];
  try {
    if (viewerInstance?.UI?.setZoomLevel) {
      viewerInstance.UI.setZoomLevel(2);
    } else if (documentViewer?.setZoomLevel) {
      documentViewer.setZoomLevel(2);
    }
  } catch {}
  try {
    documentViewer.setCurrentPage?.(pageNo);
  } catch {}
  requestAnimationFrame(() => {
    try {
      if (typeof documentViewer.jumpToAnnotation === "function") {
        documentViewer.jumpToAnnotation(first, { animate: true });
      } else if (typeof documentViewer.scrollToAnnotation === "function") {
        documentViewer.scrollToAnnotation(first, { animate: true });
      }
    } catch {}
  });
}

function buildDocIndex(examples) {
  const map = new Map();
  for (const ex of examples || []) {
    const docId = ex.doc_id;
    if (!map.has(docId)) map.set(docId, []);
    map.get(docId).push(ex);
  }
  docIndex = Array.from(map.entries()).map(([docId, items]) => ({
    docId,
    examples: items,
  }));
}

function applyDocFilter() {
  const term = String(docSearchEl?.value || "").trim().toLowerCase();
  const items = term
    ? docIndex.filter((d) => d.docId.toLowerCase().includes(term))
    : docIndex.slice();
  docSelectEl.innerHTML = "";
  if (docListEl) docListEl.innerHTML = "";
  if (!items.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No matches";
    docSelectEl.appendChild(opt);
    exampleSelectEl.innerHTML = "";
    const opt2 = document.createElement("option");
    opt2.value = "";
    opt2.textContent = "Select a document";
    exampleSelectEl.appendChild(opt2);
    if (docListEl) {
      const empty = document.createElement("div");
      empty.className = "doc-item empty";
      empty.textContent = "No documents match";
      docListEl.appendChild(empty);
    }
    return;
  }
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = item.docId;
    opt.textContent = `${item.docId} (${item.examples.length})`;
    docSelectEl.appendChild(opt);
  }
  if (docListEl) {
    for (const item of items) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "doc-item";
      btn.dataset.docId = item.docId;
      btn.textContent = `${item.docId} (${item.examples.length})`;
      btn.addEventListener("click", () => {
        docSelectEl.value = item.docId;
        loadExamplesForDoc(item.docId);
      });
      docListEl.appendChild(btn);
    }
  }
  docSelectEl.value = items[0].docId;
  loadExamplesForDoc(items[0].docId);
}

function loadExamplesForDoc(docId) {
  const entry = docIndex.find((d) => d.docId === docId);
  exampleSelectEl.innerHTML = "";
  if (docListEl) {
    const items = Array.from(docListEl.querySelectorAll(".doc-item"));
    for (const item of items) {
      item.classList.toggle("active", item.dataset.docId === docId);
    }
  }
  if (!entry) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "Select a document";
    exampleSelectEl.appendChild(opt);
    return;
  }
  for (const ex of entry.examples) {
    const opt = document.createElement("option");
    opt.value = ex.id;
    opt.textContent = ex.question;
    exampleSelectEl.appendChild(opt);
  }
  exampleSelectEl.value = entry.examples[0]?.id || "";
  renderExample(entry.examples[0], { focus: true });
}

function findExampleById(id) {
  for (const entry of docIndex) {
    const ex = entry.examples.find((e) => e.id === id);
    if (ex) return ex;
  }
  return null;
}

function renderExample(ex, opts = { focus: true }) {
  if (!ex) return;
  syncABMaster();
  setText(evalFieldLabelEl, ex.question);
  setText(evalExpectedValueEl, ex.expected_answer);

  const rawData = ex.methods?.raw || {};
  const indexedData = ex.methods?.indexed || {};

  setText(evalAnswerRawEl, rawData?.answer || rawData?.error || "-");
  setText(evalAnswerIndexedEl, indexedData?.answer || indexedData?.error || "-");
  updateMetrics(rawData?.metrics || {}, indexedData?.metrics || {});

  const gtBoxes = (ex.expected_words || []).map((w) => w.box).filter(Boolean);
  const rawBoxes = collectBoxes(rawData);
  const indexedBoxes = collectBoxes(indexedData);
  const pageNo = rawData?.mapped?.pages?.[0]?.page || indexedData?.mapped?.pages?.[0]?.page || 1;

  const docId = ex.doc_id;
  const url = `/api/eval_pdf?doc_id=${encodeURIComponent(docId)}`;
  if (!viewerInstance || !documentViewer) {
    pendingOverlay = { gt: gtBoxes, raw: rawBoxes, indexed: indexedBoxes, page: pageNo, focus: opts.focus };
    currentDocId = docId;
    return;
  }
  if (currentDocId !== docId) {
    currentDocId = docId;
    pendingOverlay = { gt: gtBoxes, raw: rawBoxes, indexed: indexedBoxes, page: pageNo, focus: opts.focus };
    try {
      viewerInstance.UI.loadDocument(url);
    } catch {}
  } else {
    const anns = renderOverlay(gtBoxes, rawBoxes, indexedBoxes, pageNo) || [];
    if (opts.focus) {
      focusOnAnnotations(anns, pageNo);
    }
  }
}

async function loadRuns() {
  const data = await getJson("/api/eval_runs");
  const runs = data?.runs || [];
  evalRunSelectEl.innerHTML = "";
  if (!runs.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No runs found";
    evalRunSelectEl.appendChild(opt);
    return;
  }
  for (const name of runs) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    evalRunSelectEl.appendChild(opt);
  }
  evalRunSelectEl.value = runs[0];
  await loadRun(runs[0]);
}

async function loadRun(name) {
  if (!name) return;
  const data = await getJson(`/api/eval_run?name=${encodeURIComponent(name)}`);
  runData = data;
  const meta = data?.meta || {};
  const metaText = [`dataset ${meta.dataset}`, `split ${meta.split}`, `samples ${meta.sample_size}`]
    .filter(Boolean)
    .join(" | ");
  setText(evalRunMetaEl, metaText || "-");

  buildDocIndex(data?.examples || []);
  applyDocFilter();
}

async function initViewer() {
  const webviewerPath = new URL("/webviewer", window.location.href).href.replace(/\/$/, "");
  const initialDoc = new URL(DEFAULT_DOC, window.location.href).href;
  viewerInstance = await WebViewer({ path: webviewerPath, initialDoc, fullAPI: true }, document.getElementById("wv"));
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
      if (pendingOverlay) {
        const anns =
          renderOverlay(pendingOverlay.gt, pendingOverlay.raw, pendingOverlay.indexed, pendingOverlay.page) || [];
        if (pendingOverlay.focus) {
          focusOnAnnotations(anns, pendingOverlay.page);
        }
        pendingOverlay = null;
      }
    });
  }

  if (annotationManager?.setReadOnly) annotationManager.setReadOnly(true);
  if (documentViewer?.setReadOnly) documentViewer.setReadOnly(true);
  if (UI?.setHeaderItems) {
    UI.setHeaderItems((header) => {
      const items = header.getItems?.() || [];
      for (const item of items) header.delete?.(item);
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

evalRunSelectEl?.addEventListener("change", () => loadRun(String(evalRunSelectEl.value || "")));
docSearchEl?.addEventListener("input", () => applyDocFilter());
docSelectEl?.addEventListener("change", () => loadExamplesForDoc(String(docSelectEl.value || "")));
exampleSelectEl?.addEventListener("change", () => {
  const ex = findExampleById(String(exampleSelectEl.value || ""));
  if (ex) renderExample(ex, { focus: true });
});
showGtEl?.addEventListener("change", () => {
  const ex = findExampleById(String(exampleSelectEl.value || ""));
  if (ex) renderExample(ex, { focus: false });
});
showRawEl?.addEventListener("change", () => {
  const ex = findExampleById(String(exampleSelectEl.value || ""));
  if (ex) renderExample(ex, { focus: false });
});
showIndexedEl?.addEventListener("change", () => {
  const ex = findExampleById(String(exampleSelectEl.value || ""));
  if (ex) renderExample(ex, { focus: false });
});
toggleABEl?.addEventListener("change", () => {
  const checked = toggleABEl.checked;
  if (showRawEl) showRawEl.checked = checked;
  if (showIndexedEl) showIndexedEl.checked = checked;
  toggleABEl.indeterminate = false;
  const ex = findExampleById(String(exampleSelectEl.value || ""));
  if (ex) renderExample(ex, { focus: false });
});

initViewer().then(() => loadRuns().catch(() => {})).catch(() => {});
