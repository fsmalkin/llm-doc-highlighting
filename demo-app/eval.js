const DEFAULT_DOC = "./assets/Physician_Report_Scanned-ocr.pdf";

const evalRunMetaEl = document.getElementById("evalRunMeta");
const evalRunNameEl = document.getElementById("evalRunName");
const evalRunSelectEl = document.getElementById("evalRunSelect");
const docSearchEl = document.getElementById("docSearch");
const docSelectEl = document.getElementById("docSelect");
const exampleSelectEl = document.getElementById("exampleSelect");
const docListEl = document.getElementById("docList");
const prevSampleEl = document.getElementById("prevSample");
const nextSampleEl = document.getElementById("nextSample");

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

const showMergedEl = document.getElementById("showMerged");
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
let filteredDocIds = [];
let currentDocId = null;
let pendingOverlay = null;
let currentRunName = "";
let pendingSelection = null;
let pendingFocusTag = null;
let lastRender = null;

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

function mergeBoxesToLines(boxes) {
  const norm = normalizeBoxes(boxes);
  if (!norm.length) return [];
  const heights = norm.map((b) => Math.max(1, b[3] - b[1]));
  const sortedHeights = heights.slice().sort((a, b) => a - b);
  const mid = Math.floor(sortedHeights.length / 2);
  const medianHeight =
    sortedHeights.length % 2 === 0 ? (sortedHeights[mid - 1] + sortedHeights[mid]) / 2 : sortedHeights[mid];
  const yTol = Math.max(2, medianHeight * 0.6);
  const gapTol = Math.max(10, medianHeight * 2);

  const items = norm
    .map((b) => ({ box: b, y: (b[1] + b[3]) / 2, x: b[0] }))
    .sort((a, b) => (a.y === b.y ? a.x - b.x : a.y - b.y));

  const clusters = [];
  for (const item of items) {
    const last = clusters[clusters.length - 1];
    if (last && Math.abs(item.y - last.centerY) <= yTol) {
      last.items.push(item.box);
      last.centerY = (last.centerY * (last.items.length - 1) + item.y) / last.items.length;
    } else {
      clusters.push({ centerY: item.y, items: [item.box] });
    }
  }

  const merged = [];
  for (const cluster of clusters) {
    const boxesSorted = cluster.items.slice().sort((a, b) => a[0] - b[0]);
    let segment = null;
    for (const b of boxesSorted) {
      if (!segment) {
        segment = { x0: b[0], y0: b[1], x1: b[2], y1: b[3] };
        continue;
      }
      const gap = b[0] - segment.x1;
      if (gap > gapTol) {
        merged.push([segment.x0, segment.y0, segment.x1, segment.y1]);
        segment = { x0: b[0], y0: b[1], x1: b[2], y1: b[3] };
      } else {
        segment.x0 = Math.min(segment.x0, b[0]);
        segment.y0 = Math.min(segment.y0, b[1]);
        segment.x1 = Math.max(segment.x1, b[2]);
        segment.y1 = Math.max(segment.y1, b[3]);
      }
    }
    if (segment) merged.push([segment.x0, segment.y0, segment.x1, segment.y1]);
  }
  return merged;
}

function dedupeWords(words) {
  const seen = new Set();
  const out = [];
  for (const w of words || []) {
    const text = String(w?.text || "").trim();
    const box = Array.isArray(w?.box) ? w.box.map((v) => Number(v)) : null;
    if (!text || !box || box.length !== 4 || box.some((v) => Number.isNaN(v))) continue;
    const key = `${text}|${box.map((v) => Math.round(v * 100) / 100).join(",")}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ text, box });
  }
  return out;
}

function sanitizeExample(ex) {
  if (!ex) return ex;
  const expectedWords = dedupeWords(ex.expected_words || []);
  const expectedAnswer =
    expectedWords.length > 0 ? expectedWords.map((w) => w.text).join(" ").trim() : ex.expected_answer;
  const methods = ex.methods || {};
  return {
    ...ex,
    expected_words: expectedWords,
    expected_answer: expectedAnswer || ex.expected_answer,
    methods,
  };
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
  const rect = annotations.reduce(
    (acc, ann) => {
      const x0 = Number(ann?.X ?? 0);
      const y0 = Number(ann?.Y ?? 0);
      const x1 = x0 + Number(ann?.Width ?? 0);
      const y1 = y0 + Number(ann?.Height ?? 0);
      if (!acc) return { x0, y0, x1, y1 };
      return {
        x0: Math.min(acc.x0, x0),
        y0: Math.min(acc.y0, y0),
        x1: Math.max(acc.x1, x1),
        y1: Math.max(acc.y1, y1),
      };
    },
    null
  );
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
        return;
      } else if (typeof documentViewer.scrollToAnnotation === "function") {
        documentViewer.scrollToAnnotation(first, { animate: true });
        return;
      }
    } catch {}
    if (rect && Core?.Math?.Rect && typeof documentViewer.setViewRect === "function") {
      const viewRect = new Core.Math.Rect(rect.x0, rect.y0, rect.x1 - rect.x0, rect.y1 - rect.y0);
      documentViewer.setViewRect(viewRect, true, true);
    }
  });
}

function focusOnBoxes(boxes, pageNo) {
  if (!boxes || !boxes.length || !documentViewer || !Core?.Math?.Rect) return false;
  const rect = boxes.reduce((acc, b) => {
    const x0 = Number(b?.[0] ?? 0);
    const y0 = Number(b?.[1] ?? 0);
    const x1 = Number(b?.[2] ?? 0);
    const y1 = Number(b?.[3] ?? 0);
    if (!acc) return { x0, y0, x1, y1 };
    return {
      x0: Math.min(acc.x0, x0),
      y0: Math.min(acc.y0, y0),
      x1: Math.max(acc.x1, x1),
      y1: Math.max(acc.y1, y1),
    };
  }, null);
  if (!rect) return false;
  try {
    if (viewerInstance?.UI?.setZoomLevel) {
      viewerInstance.UI.setZoomLevel(2);
    } else if (documentViewer?.setZoomLevel) {
      documentViewer.setZoomLevel(2);
    }
  } catch {}
  try {
    documentViewer.setCurrentPage?.(pageNo || 1);
  } catch {}
  requestAnimationFrame(() => {
    try {
      const viewRect = new Core.Math.Rect(rect.x0, rect.y0, rect.x1 - rect.x0, rect.y1 - rect.y0);
      documentViewer.setViewRect(viewRect, true, true);
    } catch {}
  });
  return true;
}

function getAnnotationsByTag(tag) {
  if (!annotationManager) return [];
  const list = Array.from(annotationManager.getAnnotationsList?.() || []);
  return list.filter((ann) => ann?.getCustomData?.("eval_tag") === tag);
}

function focusByTag(tag) {
  if (!tag) return;
  if (!annotationManager || !documentViewer) {
    pendingFocusTag = tag;
    return;
  }
  let resolvedTag = tag;
  const showRaw = showRawEl ? showRawEl.checked : true;
  const showIndexed = showIndexedEl ? showIndexedEl.checked : true;
  if ((tag === "raw" || tag === "indexed") && showRaw && showIndexed) {
    resolvedTag = "ab";
  }
  if (lastRender && lastRender.page) {
    const renderBoxes =
      resolvedTag === "gt"
        ? lastRender.gt
        : resolvedTag === "raw"
        ? lastRender.raw
        : resolvedTag === "indexed"
        ? lastRender.indexed
        : lastRender.ab;
    if (focusOnBoxes(renderBoxes, lastRender.page)) {
      pendingFocusTag = null;
      return;
    }
  }
  let anns = getAnnotationsByTag(resolvedTag);
  if (!anns.length && resolvedTag !== tag) {
    anns = getAnnotationsByTag(tag);
  }
  if (!anns.length) {
    const ex = findExampleById(String(exampleSelectEl?.value || ""));
    pendingFocusTag = tag;
    if (ex) renderExample(ex, { focus: false });
    return;
  }
  const pageNo = anns[0]?.PageNumber || 1;
  focusOnAnnotations(anns, pageNo);
  pendingFocusTag = null;
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
  filteredDocIds = items.map((d) => d.docId);
  docSelectEl.innerHTML = "";
  if (docListEl) docListEl.innerHTML = "";
  if (!items.length) {
    filteredDocIds = [];
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

function loadExamplesForDoc(docId, selectedExampleId = null) {
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
  const target =
    selectedExampleId && entry.examples.find((ex) => ex.id === selectedExampleId)
      ? entry.examples.find((ex) => ex.id === selectedExampleId)
      : entry.examples[0];
  exampleSelectEl.value = target?.id || "";
  renderExample(target, { focus: true });
  updateSelectionInUrl();
}

function stepSample(direction) {
  if (!filteredDocIds.length) return;
  const currentDoc = String(docSelectEl?.value || currentDocId || "");
  let docPos = filteredDocIds.indexOf(currentDoc);
  if (docPos < 0) docPos = 0;
  const entry = docIndex.find((d) => d.docId === filteredDocIds[docPos]);
  const examples = entry?.examples || [];
  if (!examples.length) return;
  const currentId = String(exampleSelectEl?.value || "");
  let exPos = examples.findIndex((ex) => ex.id === currentId);
  if (exPos < 0) exPos = 0;

  let nextDocPos = docPos;
  let nextExPos = exPos + direction;

  if (nextExPos < 0) {
    nextDocPos = docPos - 1;
    if (nextDocPos < 0) {
      nextDocPos = 0;
      nextExPos = 0;
    } else {
      const prevEntry = docIndex.find((d) => d.docId === filteredDocIds[nextDocPos]);
      nextExPos = Math.max(0, (prevEntry?.examples?.length || 1) - 1);
    }
  } else if (nextExPos >= examples.length) {
    nextDocPos = docPos + 1;
    if (nextDocPos >= filteredDocIds.length) {
      nextDocPos = filteredDocIds.length - 1;
      nextExPos = examples.length - 1;
    } else {
      nextExPos = 0;
    }
  }

  const targetDocId = filteredDocIds[nextDocPos];
  const targetEntry = docIndex.find((d) => d.docId === targetDocId);
  const targetExample = targetEntry?.examples?.[nextExPos];
  if (!targetExample) return;
  docSelectEl.value = targetDocId;
  loadExamplesForDoc(targetDocId, targetExample.id);
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

  const gtBoxes = dedupeBoxes((ex.expected_words || []).map((w) => w.box).filter(Boolean));
  const rawBoxes = dedupeBoxes(collectBoxes(rawData));
  const indexedBoxes = dedupeBoxes(collectBoxes(indexedData));
  const useMerged = showMergedEl ? showMergedEl.checked : false;
  const gtRender = useMerged ? mergeBoxesToLines(gtBoxes) : gtBoxes;
  const rawRender = useMerged ? mergeBoxesToLines(rawBoxes) : rawBoxes;
  const indexedRender = useMerged ? mergeBoxesToLines(indexedBoxes) : indexedBoxes;
  const abRender = dedupeBoxes([...(rawRender || []), ...(indexedRender || [])]);
  lastRender = { gt: gtRender, raw: rawRender, indexed: indexedRender, ab: abRender, page: pageNo };
  const pageNo = rawData?.mapped?.pages?.[0]?.page || indexedData?.mapped?.pages?.[0]?.page || 1;

  const docId = ex.doc_id;
  const url = `/api/eval_pdf?doc_id=${encodeURIComponent(docId)}`;
  if (!viewerInstance || !documentViewer) {
    pendingOverlay = { gt: gtRender, raw: rawRender, indexed: indexedRender, page: pageNo, focus: opts.focus };
    currentDocId = docId;
    return;
  }
  if (currentDocId !== docId) {
    currentDocId = docId;
    pendingOverlay = { gt: gtRender, raw: rawRender, indexed: indexedRender, page: pageNo, focus: opts.focus };
    try {
      viewerInstance.UI.loadDocument(url);
    } catch {}
  } else {
    const anns = renderOverlay(gtRender, rawRender, indexedRender, pageNo) || [];
    if (opts.focus) {
      focusOnAnnotations(anns, pageNo);
    }
    if (pendingFocusTag) {
      focusByTag(pendingFocusTag);
    }
  }
}

function getEvalParams() {
  const params = new URLSearchParams(window.location.search || "");
  return {
    run: params.get("run") || "",
    doc: params.get("doc") || "",
    example: params.get("ex") || params.get("example") || "",
  };
}

function updateRunInUrl(name) {
  const params = new URLSearchParams(window.location.search || "");
  if (name) {
    params.set("run", name);
  } else {
    params.delete("run");
  }
  const qs = params.toString();
  const nextUrl = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
  if (window.history?.replaceState) {
    window.history.replaceState(null, "", nextUrl);
  }
}

function updateSelectionInUrl() {
  const params = new URLSearchParams(window.location.search || "");
  if (currentRunName) {
    params.set("run", currentRunName);
  } else {
    params.delete("run");
  }
  const docId = String(docSelectEl?.value || "");
  const exId = String(exampleSelectEl?.value || "");
  if (docId) {
    params.set("doc", docId);
  } else {
    params.delete("doc");
  }
  if (exId) {
    params.set("ex", exId);
  } else {
    params.delete("ex");
  }
  const qs = params.toString();
  const nextUrl = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
  if (window.history?.replaceState) {
    window.history.replaceState(null, "", nextUrl);
  }
}

function setRunEmptyState() {
  setText(evalRunNameEl, "No run selected");
  setText(evalRunMetaEl, "Choose a run to begin.");
  docSelectEl.innerHTML = "";
  exampleSelectEl.innerHTML = "";
  if (docListEl) {
    docListEl.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "doc-item empty";
    empty.textContent = "No run loaded";
    docListEl.appendChild(empty);
  }
}

async function loadRuns() {
  const data = await getJson("/api/eval_runs");
  const runs = data?.runs || [];
  if (!evalRunSelectEl) return;
  evalRunSelectEl.innerHTML = "";
  if (!runs.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No runs found";
    evalRunSelectEl.appendChild(opt);
    setRunEmptyState();
    return;
  }
  for (const name of runs) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    evalRunSelectEl.appendChild(opt);
  }
  const preferred = pendingSelection?.run || "";
  const initial = preferred && runs.includes(preferred) ? preferred : runs[0];
  evalRunSelectEl.value = initial;
  updateRunInUrl(initial);
  await loadRun(initial);
}

async function loadRun(name) {
  if (!name) return;
  const data = await getJson(`/api/eval_run?name=${encodeURIComponent(name)}`);
  const sanitizedExamples = (data?.examples || []).map((ex) => sanitizeExample(ex));
  runData = { ...data, examples: sanitizedExamples };
  currentRunName = name;
  const meta = data?.meta || {};
  const metaText = [`dataset ${meta.dataset}`, `split ${meta.split}`, `samples ${meta.sample_size}`]
    .filter(Boolean)
    .join(" | ");
  setText(evalRunNameEl, name);
  setText(evalRunMetaEl, metaText || "-");

  buildDocIndex(sanitizedExamples);
  applyDocFilter();
  if (pendingSelection && (!pendingSelection.run || pendingSelection.run === name)) {
    const docId = pendingSelection.doc;
    const exId = pendingSelection.example;
    let handled = false;
    if (exId) {
      const ex = findExampleById(exId);
      if (ex) {
        docSelectEl.value = ex.doc_id;
        loadExamplesForDoc(ex.doc_id, ex.id);
        handled = true;
      }
    }
    if (!handled && docId) {
      docSelectEl.value = docId;
      loadExamplesForDoc(docId, exId || null);
    }
    pendingSelection = null;
  }
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
      if (pendingFocusTag) {
        focusByTag(pendingFocusTag);
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

docSearchEl?.addEventListener("input", () => applyDocFilter());
docSelectEl?.addEventListener("change", () => loadExamplesForDoc(String(docSelectEl.value || "")));
exampleSelectEl?.addEventListener("change", () => {
  const ex = findExampleById(String(exampleSelectEl.value || ""));
  if (ex) renderExample(ex, { focus: true });
  updateSelectionInUrl();
});
showGtEl?.addEventListener("change", () => {
  const ex = findExampleById(String(exampleSelectEl.value || ""));
  if (ex) renderExample(ex, { focus: false });
});
showMergedEl?.addEventListener("change", () => {
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
evalRunSelectEl?.addEventListener("change", () => {
  const name = String(evalRunSelectEl.value || "");
  updateRunInUrl(name);
  if (name) {
    loadRun(name).catch(() => setRunEmptyState());
  } else {
    setRunEmptyState();
  }
});
prevSampleEl?.addEventListener("click", () => stepSample(-1));
nextSampleEl?.addEventListener("click", () => stepSample(1));
const focusTargets = [
  { el: evalExpectedValueEl, tag: "gt" },
  { el: evalAnswerRawEl, tag: "raw" },
  { el: evalAnswerIndexedEl, tag: "indexed" },
];
for (const target of focusTargets) {
  if (!target.el) continue;
  target.el.addEventListener("click", () => {
    if (target.tag === "gt" && showGtEl && !showGtEl.checked) showGtEl.checked = true;
    if (target.tag === "raw" && showRawEl && !showRawEl.checked) showRawEl.checked = true;
    if (target.tag === "indexed" && showIndexedEl && !showIndexedEl.checked) showIndexedEl.checked = true;
    const ex = findExampleById(String(exampleSelectEl.value || ""));
    if (ex) renderExample(ex, { focus: false });
    focusByTag(target.tag);
  });
}

initViewer()
  .then(() => {
    pendingSelection = getEvalParams();
    return loadRuns().catch(() => setRunEmptyState());
  })
  .catch(() => {});
