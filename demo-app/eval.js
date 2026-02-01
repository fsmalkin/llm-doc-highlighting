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
const docReviewStatusEl = document.getElementById("docReviewStatus");
const docReviewCountsEl = document.getElementById("docReviewCounts");
const browseSearchEl = document.getElementById("browseSearch");
const toggleSearchEl = document.getElementById("toggleSearch");

const evalFieldLabelEl = document.getElementById("evalFieldLabel");
const fieldReviewStatusEl = document.getElementById("fieldReviewStatus");
const evalExpectedValueEl = document.getElementById("evalExpectedValue");
const gtStatusChipEl = document.getElementById("gtStatusChip");
const evalAnswerRawEl = document.getElementById("evalAnswerRaw");
const evalAnswerIndexedEl = document.getElementById("evalAnswerIndexed");
const gtPickInputs = Array.from(document.querySelectorAll('input[name="gtPick"]'));

const gtStatusBadgeEl = document.getElementById("gtStatusBadge");
const gtStatusNoteEl = document.getElementById("gtStatusNote");
const gtDecisionInputs = Array.from(document.querySelectorAll('input[name="gtDecision"]'));
const gtExcludeEl = document.getElementById("gtExclude");
const gtApplyBtn = document.getElementById("gtApplyBtn");
const gtExcludedCountEl = document.getElementById("gtExcludedCount");
const gtNoteEl = document.getElementById("gtNote");
const gtNoteWrapEl = document.getElementById("gtNoteWrap");
const gtNoteToggleEl = document.getElementById("toggleGtNote");
const gtEmptyStateEl = document.getElementById("gtEmptyState");
const gtMarkReviewedBtn = document.getElementById("gtMarkReviewedBtn");

const metricRawIouEl = document.getElementById("metricRawIou");
const metricRawPrecisionEl = document.getElementById("metricRawPrecision");
const metricRawRecallEl = document.getElementById("metricRawRecall");
const metricRawPass2El = document.getElementById("metricRawPass2");

const metricIndexedIouEl = document.getElementById("metricIndexedIou");
const metricIndexedPrecisionEl = document.getElementById("metricIndexedPrecision");
const metricIndexedRecallEl = document.getElementById("metricIndexedRecall");
const metricIndexedPass2El = document.getElementById("metricIndexedPass2");
const abStatusChipEl = document.getElementById("abStatusChip");
const abStatusNoteEl = document.getElementById("abStatusNote");

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
let pendingDocId = null;
let pendingOverlay = null;
let currentRunName = "";
let pendingSelection = null;
let pendingFocusTag = null;
let currentExample = null;
let correctionsCache = new Map();
let currentSavedNote = "";
let currentGtResolved = null;
let gtSaveInFlight = false;
let reviewStatsByDoc = new Map();
let reviewStatsLoading = false;
let currentHasCorrection = false;
let noteOpen = false;
let pendingDecision = "";

function setText(el, text) {
  if (!el) return;
  el.textContent = text ? String(text) : "-";
}

function updateSearchToggleLabel() {
  if (!browseSearchEl || !toggleSearchEl) return;
  const collapsed = browseSearchEl.classList.contains("collapsed");
  toggleSearchEl.textContent = collapsed ? "Search" : "Hide search";
}

function setBadge(el, value) {
  if (!el) return;
  el.textContent = value == null || value === "" ? "-" : String(value);
}

function setBadgeVariant(el, variant) {
  if (!el) return;
  el.classList.remove("good", "bad", "warn");
  if (variant) el.classList.add(variant);
}

function normalizeLabel(text) {
  return String(text || "")
    .trim()
    .replace(/\\s+/g, " ")
    .replace(/:+$/, "")
    .toLowerCase();
}

function cleanWordBoxes(boxes) {
  const out = [];
  for (const box of boxes || []) {
    if (!Array.isArray(box) || box.length !== 4) continue;
    const nums = box.map((v) => Number(v));
    if (nums.some((v) => Number.isNaN(v))) continue;
    out.push(nums);
  }
  return out;
}

function unionBoxes(boxes) {
  const clean = cleanWordBoxes(boxes);
  if (!clean.length) return null;
  const xs0 = clean.map((b) => b[0]);
  const ys0 = clean.map((b) => b[1]);
  const xs1 = clean.map((b) => b[2]);
  const ys1 = clean.map((b) => b[3]);
  return [Math.min(...xs0), Math.min(...ys0), Math.max(...xs1), Math.max(...ys1)];
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

async function postJson(url, payload) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: controller.signal,
  });
  clearTimeout(timer);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    const msg = data.error || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

async function loadCorrectionsForDoc(docId) {
  if (!docId) return { items: [], byExample: new Map(), byLabel: new Map() };
  if (correctionsCache.has(docId)) return correctionsCache.get(docId);
  let payload = { doc_id: docId, items: [] };
  try {
    const data = await getJson(`/api/gt/corrections?doc=${encodeURIComponent(docId)}`);
    payload = data?.payload || payload;
  } catch {
    payload = { doc_id: docId, items: [] };
  }
  const items = Array.isArray(payload.items) ? payload.items : [];
  const byExample = new Map();
  const byLabel = new Map();
  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    const exId = item?.links?.eval_example_id || item?.item_id;
    if (exId) {
      byExample.set(String(exId), item);
      continue;
    }
    const labelKey = normalizeLabel(item?.field_label || "");
    if (labelKey) byLabel.set(labelKey, item);
  }
  const entry = { items, byExample, byLabel };
  correctionsCache.set(docId, entry);
  return entry;
}

function toFixed(value) {
  if (value == null || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return num.toFixed(2);
}

function updateMetrics(rawMetrics, indexedMetrics) {
  setBadge(metricRawIouEl, toFixed(rawMetrics?.word_iou));
  setBadge(metricRawPrecisionEl, toFixed(rawMetrics?.precision));
  setBadge(metricRawRecallEl, toFixed(rawMetrics?.recall));
  if (rawMetrics?.used_pass2 == null || rawMetrics?.excluded) {
    setBadge(metricRawPass2El, "-");
  } else {
    setBadge(metricRawPass2El, rawMetrics?.used_pass2 ? "yes" : "no");
  }

  setBadge(metricIndexedIouEl, toFixed(indexedMetrics?.word_iou));
  setBadge(metricIndexedPrecisionEl, toFixed(indexedMetrics?.precision));
  setBadge(metricIndexedRecallEl, toFixed(indexedMetrics?.recall));
  if (indexedMetrics?.used_pass2 == null || indexedMetrics?.excluded) {
    setBadge(metricIndexedPass2El, "-");
  } else {
    setBadge(metricIndexedPass2El, indexedMetrics?.used_pass2 ? "yes" : "no");
  }

  const alignThreshold = 0.85;
  const rawAligned = Number(rawMetrics?.word_iou || 0) >= alignThreshold && !rawMetrics?.excluded;
  const idxAligned = Number(indexedMetrics?.word_iou || 0) >= alignThreshold && !indexedMetrics?.excluded;
  let status = "Needs review";
  let variant = "warn";
  if (rawAligned && idxAligned) {
    status = "Aligned";
    variant = "good";
  } else if (rawAligned || idxAligned) {
    status = "Partial";
    variant = "warn";
  }
  if (abStatusChipEl) {
    abStatusChipEl.textContent = status;
    setBadgeVariant(abStatusChipEl, variant);
  }
  if (abStatusNoteEl) {
    if (status === "Aligned") {
      abStatusNoteEl.textContent = "GT matches both methods at IoU >= 0.85.";
    } else if (status === "Partial") {
      abStatusNoteEl.textContent = "Only one method aligns with GT at IoU >= 0.85.";
    } else {
      abStatusNoteEl.textContent = "Neither method aligns at IoU >= 0.85.";
    }
  }
}

function resolveGtForExample(ex, correctionEntry) {
  const datasetBoxes = dedupeBoxes((ex.expected_words || []).map((w) => w.box).filter(Boolean));
  const datasetValue = ex.expected_answer || "";
  if (!correctionEntry) {
    return {
      status: "use_dataset",
      source: "dataset",
      decision: "dataset",
      value: datasetValue,
      boxes: datasetBoxes,
      note: "Using dataset ground truth.",
    };
  }
  let status = String(correctionEntry.gt_status || "").toLowerCase();
  if (!status) {
    status = correctionEntry.value || correctionEntry.bbox || correctionEntry.word_boxes ? "use_correction" : "use_dataset";
  }
  if (status === "exclude") {
    return {
      status: "exclude",
      source: "excluded",
      decision: "exclude",
      value: "Excluded from scoring",
      boxes: [],
      note: "Excluded from scoring (both wrong).",
    };
  }
  if (status === "use_dataset") {
    return {
      status: "use_dataset",
      source: "dataset",
      decision: "dataset",
      value: datasetValue,
      boxes: datasetBoxes,
      note: "Using dataset ground truth.",
    };
  }
  const wordBoxes = cleanWordBoxes(correctionEntry.word_boxes || correctionEntry.boxes || []);
  const singleBox = cleanWordBoxes(correctionEntry.bbox ? [correctionEntry.bbox] : []);
  const boxes = wordBoxes.length ? wordBoxes : singleBox;
  const value = String(correctionEntry.value || datasetValue || "").trim();
  const method = correctionEntry?.source?.method || correctionEntry?.links?.method || "correction";
  if (!boxes.length) {
    return {
      status: "use_dataset",
      source: "dataset",
      decision: "dataset",
      value: datasetValue,
      boxes: datasetBoxes,
      note: "Correction missing boxes; falling back to dataset GT.",
    };
  }
  return {
    status: "use_correction",
    source: method,
    decision: method === "raw" ? "raw" : method === "indexed" ? "indexed" : "custom",
    value: value || datasetValue,
    boxes,
    note: `Using corrected GT from ${method}.`,
  };
}

function updateGtStatusUI(gt) {
  if (!gtStatusBadgeEl || !gtStatusNoteEl || !gtStatusChipEl) return;
  let badgeText = "Dataset";
  let chipText = "Dataset";
  let variant = null;
  if (gt && gt.reviewed === false) {
    badgeText = "Not reviewed";
    chipText = "Pending";
    variant = "warn";
  }
  if (gt?.status === "use_correction") {
    badgeText = "Corrected";
    chipText = "Corrected";
    variant = "good";
  } else if (gt?.status === "exclude") {
    badgeText = "Excluded";
    chipText = "Excluded";
    variant = "bad";
  }
  gtStatusBadgeEl.textContent = badgeText;
  gtStatusChipEl.textContent = chipText;
  setBadgeVariant(gtStatusBadgeEl, variant);
  setBadgeVariant(gtStatusChipEl, variant);
  gtStatusNoteEl.textContent = gt?.note || "Select a data point to review GT.";
  if (gt && gt.reviewed === false) {
    gtStatusNoteEl.textContent = "No decision saved yet.";
  }
  for (const input of gtDecisionInputs) {
    input.checked = Boolean(gt?.decision && input.value === gt.decision);
  }
  for (const input of gtPickInputs) {
    if (pendingDecision) {
      input.checked = input.value === pendingDecision;
    } else if (currentHasCorrection) {
      input.checked = Boolean(gt?.decision && input.value === gt.decision);
    } else {
      input.checked = false;
    }
  }
  if (gtExcludeEl) {
    if (pendingDecision) {
      gtExcludeEl.checked = pendingDecision === "exclude";
    } else if (currentHasCorrection) {
      gtExcludeEl.checked = gt?.decision === "exclude";
    } else {
      gtExcludeEl.checked = false;
    }
  }
  if (gt?.decision === "custom") {
    gtStatusNoteEl.textContent = "Using a custom correction. Selecting a decision will overwrite it.";
  }
  if (gtEmptyStateEl) {
    gtEmptyStateEl.style.display = gt?.reviewed === false ? "grid" : "none";
  }
}

function setNoteOpenState(open) {
  noteOpen = open;
  if (gtNoteWrapEl) {
    gtNoteWrapEl.classList.toggle("collapsed", !open);
  }
  if (gtNoteToggleEl) {
    gtNoteToggleEl.textContent = open ? "Hide note" : "Add note";
  }
}

function getCorrectionEntryForExample(ex) {
  if (!ex) return null;
  const cached = correctionsCache.get(ex.doc_id);
  if (!cached) return null;
  const byId = cached.byExample?.get?.(ex.id);
  if (byId) return byId;
  const labelKey = normalizeLabel(ex.question || "");
  return cached.byLabel?.get?.(labelKey) || null;
}

function formatDocLabel(docId, totalCount, reviewedCount) {
  const total = Number(totalCount || 0);
  const reviewed = Number(reviewedCount || 0);
  if (!total) return `${docId}`;
  if (reviewed >= total) return `${docId} (${total}) [reviewed]`;
  if (reviewed > 0) return `${docId} (${total}) [${reviewed}/${total} reviewed]`;
  return `${docId} (${total}) [not reviewed]`;
}

async function computeReviewStatsForDoc(docId) {
  const entry = docIndex.find((d) => d.docId === docId);
  if (!entry) return { reviewedCount: 0, totalCount: 0 };
  await loadCorrectionsForDoc(docId);
  let reviewedCount = 0;
  for (const ex of entry.examples) {
    const reviewed = Boolean(getCorrectionEntryForExample(ex));
    ex.reviewed = reviewed;
    if (reviewed) reviewedCount += 1;
  }
  const totalCount = entry.examples.length;
  reviewStatsByDoc.set(docId, { reviewedCount, totalCount });
  return { reviewedCount, totalCount };
}

function updateDocSelectLabels() {
  if (!docSelectEl) return;
  const options = Array.from(docSelectEl.options || []);
  for (const opt of options) {
    const docId = opt.value;
    const entry = docIndex.find((d) => d.docId === docId);
    if (!entry) continue;
    const stats = reviewStatsByDoc.get(docId) || { reviewedCount: 0, totalCount: entry.examples.length };
    opt.textContent = formatDocLabel(docId, entry.examples.length, stats.reviewedCount);
  }
}

function updateExampleSelectLabels(entry) {
  if (!entry || !exampleSelectEl) return;
  const options = Array.from(exampleSelectEl.options || []);
  for (const opt of options) {
    const ex = entry.examples.find((e) => e.id === opt.value);
    if (!ex) continue;
    opt.textContent = `${ex.question}${ex.reviewed ? " (reviewed)" : ""}`;
  }
}

function updateDocReviewStatus(docId) {
  const entry = docIndex.find((d) => d.docId === docId);
  if (!entry) return;
  const stats = reviewStatsByDoc.get(docId) || { reviewedCount: 0, totalCount: entry.examples.length };
  const reviewedCount = stats.reviewedCount;
  const totalCount = stats.totalCount;
  let status = "Not reviewed";
  if (totalCount && reviewedCount >= totalCount) {
    status = "Fully reviewed";
  } else if (reviewedCount > 0) {
    status = "Partially reviewed";
  }
  if (docReviewStatusEl) docReviewStatusEl.textContent = status;
  if (docReviewCountsEl) docReviewCountsEl.textContent = `${reviewedCount}/${totalCount} fields reviewed`;
}

function updateFieldReviewStatus(ex) {
  if (!fieldReviewStatusEl) return;
  if (!ex) {
    fieldReviewStatusEl.textContent = "-";
    return;
  }
  fieldReviewStatusEl.textContent = ex.reviewed ? "Reviewed" : "Not reviewed";
}

async function hydrateReviewStats() {
  if (reviewStatsLoading) return;
  reviewStatsLoading = true;
  try {
    for (const entry of docIndex) {
      await computeReviewStatsForDoc(entry.docId);
      updateDocSelectLabels();
    }
  } finally {
    reviewStatsLoading = false;
  }
}

function setGtSaving(isSaving) {
  gtSaveInFlight = isSaving;
  if (!gtApplyBtn) return;
  if (isSaving) {
    gtApplyBtn.dataset.label = gtApplyBtn.textContent || "Apply decision";
    gtApplyBtn.textContent = "Saving...";
    gtApplyBtn.disabled = true;
  } else {
    gtApplyBtn.textContent = gtApplyBtn.dataset.label || "Apply decision";
    delete gtApplyBtn.dataset.label;
  }
}

function updateGtDecisionButtons(rawData, indexedData, gtResolved) {
  const hasExample = Boolean(currentExample);
  const rawBoxes = collectBoxes(rawData);
  const indexedBoxes = collectBoxes(indexedData);
  const rawBBox = rawData?.mapped?.pages?.[0]?.bbox_abs;
  const indexedBBox = indexedData?.mapped?.pages?.[0]?.bbox_abs;
  const rawOk = Boolean(rawData?.answer) && (rawBoxes.length > 0 || Array.isArray(rawBBox));
  const indexedOk = Boolean(indexedData?.answer) && (indexedBoxes.length > 0 || Array.isArray(indexedBBox));
  for (const input of gtDecisionInputs) {
    if (input.value === "raw") {
      input.disabled = !hasExample || !rawOk;
    } else if (input.value === "indexed") {
      input.disabled = !hasExample || !indexedOk;
    } else {
      input.disabled = !hasExample;
    }
  }
  for (const input of gtPickInputs) {
    if (input.value === "raw") {
      input.disabled = !hasExample || !rawOk;
    } else if (input.value === "indexed") {
      input.disabled = !hasExample || !indexedOk;
    } else {
      input.disabled = !hasExample;
    }
  }
  const selectedFromPick = gtPickInputs.find((input) => input.checked)?.value || "";
  const selectedFromExclude = gtExcludeEl?.checked ? "exclude" : "";
  const selected = selectedFromExclude || selectedFromPick || "";
  const currentDecision = gtResolved?.decision || "";
  const noteValue = String(gtNoteEl?.value || "").trim();
  const noteChanged = noteValue !== String(currentSavedNote || "").trim();
  if (gtApplyBtn) {
    const hasSelection = Boolean(selected);
    gtApplyBtn.disabled =
      gtSaveInFlight ||
      !hasExample ||
      (!hasSelection && !noteChanged) ||
      (hasSelection && selected === currentDecision && !noteChanged);
  }
  if (gtMarkReviewedBtn) {
    gtMarkReviewedBtn.disabled = gtSaveInFlight || !hasExample;
  }
}

function buildEvalUrlParams(ex) {
  if (!ex) return "";
  const params = new URLSearchParams();
  if (currentRunName) params.set("run", currentRunName);
  if (ex.doc_id) params.set("doc", ex.doc_id);
  if (ex.id) params.set("ex", ex.id);
  return params.toString();
}

function buildCorrectionItem(ex, method, methodData, gtStatus, note) {
  const wordBoxes = dedupeBoxes(collectBoxes(methodData));
  const fallbackBox = methodData?.mapped?.pages?.[0]?.bbox_abs;
  const bbox =
    unionBoxes(wordBoxes) ||
    (Array.isArray(fallbackBox) && fallbackBox.length === 4 ? fallbackBox : null);
  const value = String(methodData?.answer || "").trim();
  return {
    item_id: ex.id,
    field_label: ex.question,
    value,
    value_type: methodData?.value_type || null,
    bbox: bbox || null,
    word_boxes: wordBoxes,
    gt_status: gtStatus,
    notes: note || null,
    links: {
      eval_example_id: ex.id,
      eval_run: currentRunName || null,
      eval_url_params: buildEvalUrlParams(ex),
      method,
    },
    source: {
      tool: "eval-viewer",
      method,
      saved_at: new Date().toISOString(),
    },
  };
}

function buildStatusItem(ex, gtStatus, note) {
  return {
    item_id: ex.id,
    field_label: ex.question,
    gt_status: gtStatus,
    notes: note || null,
    links: {
      eval_example_id: ex.id,
      eval_run: currentRunName || null,
      eval_url_params: buildEvalUrlParams(ex),
    },
    source: {
      tool: "eval-viewer",
      saved_at: new Date().toISOString(),
    },
  };
}

async function saveCorrection(docId, item) {
  if (!docId) return;
  const cache = await loadCorrectionsForDoc(docId);
  const items = Array.isArray(cache.items) ? cache.items.slice() : [];
  const exId = item?.links?.eval_example_id || item?.item_id;
  let replaced = false;
  for (let i = 0; i < items.length; i += 1) {
    const existing = items[i];
    const existingId = existing?.links?.eval_example_id || existing?.item_id;
    if (exId && existingId && String(existingId) === String(exId)) {
      items[i] = item;
      replaced = true;
      break;
    }
  }
  if (!replaced) items.push(item);
  const payload = { doc_id: docId, items };
  await postJson("/api/gt/corrections", payload);
  correctionsCache.delete(docId);
  await loadCorrectionsForDoc(docId);
}

async function refreshCurrentExample(focusTag = null) {
  const ex = currentExample || findExampleById(String(exampleSelectEl?.value || ""));
  if (!ex) return;
  await loadCorrectionsForDoc(ex.doc_id);
  renderExample(ex, { focus: false, focusTag });
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

function addRect(pageNo, bbox, color, tag, opts = {}) {
  if (!annotationManager || !Annotations) return null;
  const nums = (bbox || []).map((v) => Number(v));
  if (nums.length !== 4 || nums.some((v) => Number.isNaN(v))) return null;
  let [x0, y0, x1, y1] = nums;
  if (x0 > x1) [x0, x1] = [x1, x0];
  if (y0 > y1) [y0, y1] = [y1, y0];
  const orig = { x0, y0, x1, y1 };
  const pad = Number(opts.pad ?? 0);
  if (Number.isFinite(pad) && pad !== 0) {
    x0 -= pad;
    y0 -= pad;
    x1 += pad;
    y1 += pad;
    if (x1 - x0 < 0.5 || y1 - y0 < 0.5) {
      x0 = orig.x0;
      y0 = orig.y0;
      x1 = orig.x1;
      y1 = orig.y1;
    }
  }
  const rect = new Annotations.RectangleAnnotation();
  rect.PageNumber = Number(pageNo || 1);
  rect.X = x0;
  rect.Y = y0;
  rect.Width = Math.max(0.5, x1 - x0);
  rect.Height = Math.max(0.5, y1 - y0);
  rect.StrokeColor = color;
  rect.StrokeThickness = Number(opts.thickness ?? 2);
  if (Number.isFinite(opts.opacity)) {
    rect.Opacity = Number(opts.opacity);
  }
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
  const showIndexed = showIndexedEl ? showIndexedEl.checked : false;
  const abState = showRaw && showIndexed ? "on" : !showRaw && !showIndexed ? "off" : "partial";

  const created = [];
  if (abState === "on") {
    const merged = dedupeBoxes([...(rawBoxes || []), ...(indexedBoxes || [])]);
    for (const b of merged) {
      const ann = addRect(pageNo, b, amber, "ab", { opacity: 0.65 });
      if (ann) created.push(ann);
    }
  } else if (abState === "partial") {
    if (showRaw) {
      for (const b of rawBoxes || []) {
        const ann = addRect(pageNo, b, red, "raw", { opacity: 0.75 });
        if (ann) created.push(ann);
      }
    }
    if (showIndexed) {
      for (const b of indexedBoxes || []) {
        const ann = addRect(pageNo, b, blue, "indexed", { opacity: 0.75 });
        if (ann) created.push(ann);
      }
    }
  }
  if (showGt) {
    for (const b of gtBoxes || []) {
      const ann = addRect(pageNo, b, green, "gt", { pad: -1, thickness: 2.5 });
      if (ann) created.push(ann);
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
  const canonicalAnswer = String(ex.expected_answer || "").trim();
  const methods = ex.methods || {};
  return {
    ...ex,
    expected_words: expectedWords,
    expected_answer: canonicalAnswer,
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

function resolveFocusTag(tag) {
  const showRaw = showRawEl ? showRawEl.checked : true;
  const showIndexed = showIndexedEl ? showIndexedEl.checked : true;
  if ((tag === "raw" || tag === "indexed") && showRaw && showIndexed) {
    return "ab";
  }
  return tag;
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
  const pad = rect ? Math.max(6, Math.min(24, (rect.y1 - rect.y0) * 0.3)) : 8;
  const paddedRect = rect
    ? {
        x0: rect.x0 - pad,
        y0: rect.y0 - pad,
        x1: rect.x1 + pad,
        y1: rect.y1 + pad,
      }
    : null;
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
  try {
    annotationManager?.selectAnnotation?.(first);
  } catch {}
  const applyViewRect = () => {
    if (!paddedRect || !Core?.Math?.Rect) return;
    const viewRect = new Core.Math.Rect(
      paddedRect.x0,
      paddedRect.y0,
      Math.max(1, paddedRect.x1 - paddedRect.x0),
      Math.max(1, paddedRect.y1 - paddedRect.y0)
    );
    if (typeof documentViewer.displayPageLocation === "function") {
      const center = new Core.Math.Point(
        paddedRect.x0 + (paddedRect.x1 - paddedRect.x0) / 2,
        paddedRect.y0 + (paddedRect.y1 - paddedRect.y0) / 2
      );
      try {
        documentViewer.displayPageLocation(pageNo, center, 2);
        return;
      } catch {}
    }
    if (typeof documentViewer.setViewRect === "function") {
      try {
        if (documentViewer.setViewRect.length >= 3) {
          documentViewer.setViewRect(viewRect, pageNo, true);
        } else if (documentViewer.setViewRect.length === 2) {
          documentViewer.setViewRect(viewRect, pageNo);
        } else {
          documentViewer.setViewRect(viewRect);
        }
      } catch {}
    }
  };
  const applyDomScroll = () => {
    if (!paddedRect) return;
    try {
      const host = document.querySelector("apryse-webviewer");
      const root = host?.shadowRoot;
      if (!root) return;
      const container = root.querySelector(".DocumentContainer");
      const pageEl = root.querySelector(`#pageContainer${pageNo}`) || root.querySelector(".pageContainer");
      if (!container || !pageEl) return;

      let pageHeight = null;
      let pageWidth = null;
      try {
        const doc = documentViewer.getDocument?.();
        const info = doc?.getPageInfo?.(pageNo);
        if (info && typeof info.height === "number") pageHeight = info.height;
        if (info && typeof info.width === "number") pageWidth = info.width;
        if (!pageHeight && typeof documentViewer.getPageHeight === "function") {
          const h = documentViewer.getPageHeight(pageNo);
          if (Number.isFinite(h)) pageHeight = h;
        }
        if (!pageWidth && typeof documentViewer.getPageWidth === "function") {
          const w = documentViewer.getPageWidth(pageNo);
          if (Number.isFinite(w)) pageWidth = w;
        }
      } catch {}

      const pageRect = pageEl.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();
      const scale = pageHeight ? pageRect.height / pageHeight : 1;
      const centerY = (paddedRect.y0 + paddedRect.y1) / 2;
      const targetY = pageEl.offsetTop + centerY * scale;
      const nextTop = Math.max(0, targetY - containerRect.height / 2);
      container.scrollTop = Math.min(nextTop, container.scrollHeight - containerRect.height);

      const scaleX = pageWidth ? pageRect.width / pageWidth : scale;
      const centerX = (paddedRect.x0 + paddedRect.x1) / 2;
      const targetX = pageEl.offsetLeft + centerX * scaleX;
      const nextLeft = Math.max(0, targetX - containerRect.width / 2);
      container.scrollLeft = Math.min(nextLeft, container.scrollWidth - containerRect.width);
    } catch {}
  };
  requestAnimationFrame(() => {
    try {
      if (typeof documentViewer.jumpToAnnotation === "function") {
        documentViewer.jumpToAnnotation(first, { animate: true });
      } else if (typeof documentViewer.scrollToAnnotation === "function") {
        documentViewer.scrollToAnnotation(first, { animate: true });
      }
    } catch {}
    requestAnimationFrame(() => {
      applyViewRect();
      applyDomScroll();
      documentViewer.updateView?.();
    });
  });
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
  const resolvedTag = resolveFocusTag(tag);
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
  try {
    document.body.dataset.evalFocusTag = resolvedTag;
  } catch {}
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
        void loadExamplesForDoc(item.docId);
      });
      docListEl.appendChild(btn);
    }
  }
  docSelectEl.value = items[0].docId;
  void loadExamplesForDoc(items[0].docId);
}

async function loadExamplesForDoc(docId, selectedExampleId = null) {
  await computeReviewStatsForDoc(docId);
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
    currentExample = null;
    currentGtResolved = null;
    currentHasCorrection = false;
    updateGtStatusUI(null);
    updateGtDecisionButtons({}, {}, null);
    currentSavedNote = "";
    if (gtNoteEl) gtNoteEl.value = "";
    updateFieldReviewStatus(null);
    return;
  }
  for (const ex of entry.examples) {
    const opt = document.createElement("option");
    opt.value = ex.id;
    opt.textContent = `${ex.question}${ex.reviewed ? " (reviewed)" : ""}`;
    exampleSelectEl.appendChild(opt);
  }
  const target =
    selectedExampleId && entry.examples.find((ex) => ex.id === selectedExampleId)
      ? entry.examples.find((ex) => ex.id === selectedExampleId)
      : entry.examples[0];
  exampleSelectEl.value = target?.id || "";
  renderExample(target, { focus: true });
  updateExampleSelectLabels(entry);
  updateDocSelectLabels();
  updateDocReviewStatus(docId);
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
  void loadExamplesForDoc(targetDocId, targetExample.id);
}

function findExampleById(id) {
  for (const entry of docIndex) {
    const ex = entry.examples.find((e) => e.id === id);
    if (ex) return ex;
  }
  return null;
}

function renderExample(ex, opts = { focus: true, focusTag: null }) {
  if (!ex) return;
  const isNewExample = !currentExample || currentExample.id !== ex.id;
  currentExample = ex;
  if (isNewExample) pendingDecision = "";
  syncABMaster();
  setText(evalFieldLabelEl, ex.question);
  const rawData = ex.methods?.raw || {};
  const indexedData = ex.methods?.indexed || {};

  const correctionEntry = getCorrectionEntryForExample(ex);
  currentHasCorrection = Boolean(correctionEntry);
  const gtResolved = resolveGtForExample(ex, correctionEntry);
  currentGtResolved = gtResolved;
  gtResolved.reviewed = currentHasCorrection;
  if (!currentHasCorrection) {
    gtResolved.decision = "";
    gtResolved.note = "No decision saved yet. Choose a decision or mark reviewed.";
  }
  updateGtStatusUI(gtResolved);
  setText(evalExpectedValueEl, gtResolved.value);
  if (evalExpectedValueEl) {
    evalExpectedValueEl.disabled = gtResolved.status === "exclude";
  }
  if (showGtEl) {
    showGtEl.disabled = gtResolved.status === "exclude";
  }
  currentSavedNote = String(correctionEntry?.notes || "");
  if (gtNoteEl) {
    gtNoteEl.value = currentSavedNote;
  }
  setNoteOpenState(Boolean(currentSavedNote));
  updateFieldReviewStatus(ex);

  setText(evalAnswerRawEl, rawData?.answer || rawData?.error || "-");
  setText(evalAnswerIndexedEl, indexedData?.answer || indexedData?.error || "-");
  updateMetrics(rawData?.metrics || {}, indexedData?.metrics || {});
  updateGtDecisionButtons(rawData, indexedData, gtResolved);

  const gtBoxes = dedupeBoxes(gtResolved.boxes || []);
  const rawBoxes = dedupeBoxes(collectBoxes(rawData));
  const indexedBoxes = dedupeBoxes(collectBoxes(indexedData));
  const useMerged = showMergedEl ? showMergedEl.checked : false;
  const gtRender = useMerged ? mergeBoxesToLines(gtBoxes) : gtBoxes;
  const rawRender = useMerged ? mergeBoxesToLines(rawBoxes) : rawBoxes;
  const indexedRender = useMerged ? mergeBoxesToLines(indexedBoxes) : indexedBoxes;
  const pageNo = rawData?.mapped?.pages?.[0]?.page || indexedData?.mapped?.pages?.[0]?.page || 1;

  const docId = ex.doc_id;
  const url = `/api/eval_pdf?doc_id=${encodeURIComponent(docId)}`;
  if (!viewerInstance || !documentViewer) {
    pendingOverlay = {
      gt: gtRender,
      raw: rawRender,
      indexed: indexedRender,
      page: pageNo,
      focus: opts.focus,
      focusTag: opts.focusTag || null,
    };
    pendingDocId = docId;
    return;
  }
  if (currentDocId !== docId) {
    pendingDocId = docId;
    pendingOverlay = {
      gt: gtRender,
      raw: rawRender,
      indexed: indexedRender,
      page: pageNo,
      focus: opts.focus,
      focusTag: opts.focusTag || null,
    };
    try {
      viewerInstance.UI.loadDocument(url);
    } catch {}
  } else {
    const anns = renderOverlay(gtRender, rawRender, indexedRender, pageNo) || [];
    if (opts.focus) {
      focusOnAnnotations(anns, pageNo);
    }
    const focusTag = opts.focusTag ? resolveFocusTag(opts.focusTag) : null;
    if (focusTag) {
      const focusAnns = anns.filter((ann) => ann?.getCustomData?.("eval_tag") === focusTag);
      if (focusAnns.length) {
        try {
          document.body.dataset.evalFocusTag = focusTag;
        } catch {}
        focusOnAnnotations(focusAnns, pageNo);
        pendingFocusTag = null;
      } else {
        pendingFocusTag = focusTag;
        setTimeout(() => focusByTag(focusTag), 50);
      }
    } else if (pendingFocusTag) {
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
  if (gtExcludedCountEl) {
    gtExcludedCountEl.textContent = "Excluded in this run: -";
  }
  if (abStatusChipEl) {
    abStatusChipEl.textContent = "-";
    setBadgeVariant(abStatusChipEl, null);
  }
  if (abStatusNoteEl) {
    abStatusNoteEl.textContent = "Select a data point to see alignment.";
  }
  currentExample = null;
  currentGtResolved = null;
  currentHasCorrection = false;
  updateGtStatusUI(null);
  updateGtDecisionButtons({}, {}, null);
  currentSavedNote = "";
  if (gtNoteEl) gtNoteEl.value = "";
  if (docReviewStatusEl) docReviewStatusEl.textContent = "-";
  if (docReviewCountsEl) docReviewCountsEl.textContent = "-";
  updateFieldReviewStatus(null);
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
  const excludedCount =
    meta.excluded_count == null
      ? Number(meta.excluded ?? 0)
      : Number(meta.excluded_count ?? 0);
  if (gtExcludedCountEl) {
    gtExcludedCountEl.textContent = `Excluded in this run: ${Number.isFinite(excludedCount) ? excludedCount : "-"}`;
  }

  buildDocIndex(sanitizedExamples);
  applyDocFilter();
  void hydrateReviewStats();
  if (pendingSelection && (!pendingSelection.run || pendingSelection.run === name)) {
    const docId = pendingSelection.doc;
    const exId = pendingSelection.example;
    let handled = false;
    if (exId) {
      const ex = findExampleById(exId);
      if (ex) {
        docSelectEl.value = ex.doc_id;
        await loadExamplesForDoc(ex.doc_id, ex.id);
        handled = true;
      }
    }
    if (!handled && docId) {
      docSelectEl.value = docId;
      await loadExamplesForDoc(docId, exId || null);
    }
    pendingSelection = null;
  }
}

async function initViewer() {
  const webviewerPath = new URL("/webviewer", window.location.href).href.replace(/\/$/, "");
  const initialParams = getEvalParams();
  let initialDoc = new URL(DEFAULT_DOC, window.location.href).href;
  if (initialParams?.doc) {
    initialDoc = `${window.location.origin}/api/eval_pdf?doc_id=${encodeURIComponent(initialParams.doc)}`;
    pendingDocId = initialParams.doc;
  }
  viewerInstance = await WebViewer({ path: webviewerPath, initialDoc, fullAPI: true }, document.getElementById("wv"));
  Core = viewerInstance.Core;
  const UI = viewerInstance.UI;
  annotationManager = Core.annotationManager;
  documentViewer = Core.documentViewer;
  Annotations = Core.Annotations;

  if (documentViewer?.addEventListener) {
    documentViewer.addEventListener("documentLoaded", () => {
      if (pendingDocId) {
        currentDocId = pendingDocId;
        pendingDocId = null;
      }
      try {
        document.body.dataset.evalDocId = currentDocId || "";
      } catch {}
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
        if (pendingOverlay.focusTag) {
          const focusTag = resolveFocusTag(pendingOverlay.focusTag);
          const focusAnns = anns.filter((ann) => ann?.getCustomData?.("eval_tag") === focusTag);
          if (focusAnns.length) {
            try {
              document.body.dataset.evalFocusTag = focusTag;
            } catch {}
            focusOnAnnotations(focusAnns, pendingOverlay.page);
            pendingFocusTag = null;
          } else {
            pendingFocusTag = focusTag;
            setTimeout(() => focusByTag(focusTag), 50);
          }
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
toggleSearchEl?.addEventListener("click", () => {
  if (!browseSearchEl) return;
  const isCollapsed = browseSearchEl.classList.toggle("collapsed");
  updateSearchToggleLabel();
  if (!isCollapsed && docSearchEl) {
    docSearchEl.focus();
  }
});
docSelectEl?.addEventListener("change", () => void loadExamplesForDoc(String(docSelectEl.value || "")));
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
for (const input of gtDecisionInputs) {
  input.addEventListener("change", () => {
    const ex = currentExample || findExampleById(String(exampleSelectEl.value || ""));
    if (!ex) return;
    const correctionEntry = getCorrectionEntryForExample(ex);
    const gtResolved = resolveGtForExample(ex, correctionEntry);
    currentGtResolved = gtResolved;
    updateGtDecisionButtons(ex.methods?.raw || {}, ex.methods?.indexed || {}, gtResolved);
  });
}
for (const pick of gtPickInputs) {
  pick.addEventListener("change", () => {
    const decision = pick.checked ? pick.value : "";
    if (decision) {
      pendingDecision = decision;
      if (gtExcludeEl) gtExcludeEl.checked = false;
    } else if (pendingDecision === pick.value) {
      pendingDecision = "";
    }
    const ex = currentExample || findExampleById(String(exampleSelectEl.value || ""));
    if (!ex) return;
    const correctionEntry = getCorrectionEntryForExample(ex);
    const gtResolved = resolveGtForExample(ex, correctionEntry);
    currentGtResolved = gtResolved;
    updateGtDecisionButtons(ex.methods?.raw || {}, ex.methods?.indexed || {}, gtResolved);
  });
}
gtExcludeEl?.addEventListener("change", () => {
  if (gtExcludeEl.checked) {
    pendingDecision = "exclude";
    for (const pick of gtPickInputs) {
      pick.checked = false;
    }
  } else if (pendingDecision === "exclude") {
    pendingDecision = "";
  }
  const ex = currentExample || findExampleById(String(exampleSelectEl.value || ""));
  if (!ex) return;
  const correctionEntry = getCorrectionEntryForExample(ex);
  const gtResolved = resolveGtForExample(ex, correctionEntry);
  currentGtResolved = gtResolved;
  updateGtDecisionButtons(ex.methods?.raw || {}, ex.methods?.indexed || {}, gtResolved);
});
gtNoteEl?.addEventListener("input", () => {
  if (!noteOpen) setNoteOpenState(true);
  const ex = currentExample || findExampleById(String(exampleSelectEl.value || ""));
  if (!ex) return;
  const gtResolved = currentGtResolved || resolveGtForExample(ex, getCorrectionEntryForExample(ex));
  updateGtDecisionButtons(ex.methods?.raw || {}, ex.methods?.indexed || {}, gtResolved);
});
gtNoteToggleEl?.addEventListener("click", () => {
  setNoteOpenState(!noteOpen);
  if (noteOpen && gtNoteEl) {
    gtNoteEl.focus();
  }
});
gtApplyBtn?.addEventListener("click", async () => {
  if (!currentExample) return;
  const selectedFromPick = gtPickInputs.find((input) => input.checked)?.value || "";
  const selectedFromExclude = gtExcludeEl?.checked ? "exclude" : "";
  const selected = selectedFromExclude || selectedFromPick || "";
  const fallbackDecision = currentGtResolved?.decision || "";
  const noteValue = String(gtNoteEl?.value || "").trim();
  if (gtSaveInFlight) return;
  const currentDecision = currentGtResolved?.decision || "";
  const noteChanged = noteValue !== String(currentSavedNote || "").trim();
  const decision = selected || (noteChanged ? fallbackDecision : "");
  if (!decision) return;
  const decisionChanged = decision !== currentDecision;
  try {
    setGtSaving(true);
    if (decision === "custom" && !selected) {
      const existing = getCorrectionEntryForExample(currentExample);
      if (!existing) return;
      const updated = { ...existing, notes: noteValue };
      updated.source = {
        ...(existing.source || {}),
        tool: "eval-viewer",
        saved_at: new Date().toISOString(),
      };
      await saveCorrection(currentExample.doc_id, updated);
    } else if (decision === "dataset") {
      const item = buildStatusItem(currentExample, "use_dataset", noteValue);
      await saveCorrection(currentExample.doc_id, item);
    } else if (decision === "exclude") {
      const item = buildStatusItem(currentExample, "exclude", noteValue);
      await saveCorrection(currentExample.doc_id, item);
    } else if (decision === "raw") {
      const rawData = currentExample.methods?.raw || {};
      const item = buildCorrectionItem(currentExample, "raw", rawData, "use_correction", noteValue);
      await saveCorrection(currentExample.doc_id, item);
    } else if (decision === "indexed") {
      const indexedData = currentExample.methods?.indexed || {};
      const item = buildCorrectionItem(currentExample, "indexed", indexedData, "use_correction", noteValue);
      await saveCorrection(currentExample.doc_id, item);
    }
    pendingDecision = "";
    if (decisionChanged) {
      await refreshCurrentExample("gt");
    } else if (noteChanged) {
      currentSavedNote = noteValue;
      updateGtDecisionButtons(currentExample.methods?.raw || {}, currentExample.methods?.indexed || {}, currentGtResolved);
      if (gtStatusNoteEl) gtStatusNoteEl.textContent = "Note saved.";
    }
    await computeReviewStatsForDoc(currentExample.doc_id);
    updateDocSelectLabels();
    updateDocReviewStatus(currentExample.doc_id);
  } catch (err) {
    if (gtStatusNoteEl) gtStatusNoteEl.textContent = String(err?.message || err || "Failed to save correction.");
  } finally {
    setGtSaving(false);
  }
});

gtMarkReviewedBtn?.addEventListener("click", async () => {
  if (!currentExample || gtSaveInFlight) return;
  const noteValue = String(gtNoteEl?.value || "").trim();
  try {
    setGtSaving(true);
    const item = buildStatusItem(currentExample, "use_dataset", noteValue);
    await saveCorrection(currentExample.doc_id, item);
    pendingDecision = "";
    await refreshCurrentExample("gt");
    await computeReviewStatsForDoc(currentExample.doc_id);
    updateDocSelectLabels();
    updateDocReviewStatus(currentExample.doc_id);
  } catch (err) {
    if (gtStatusNoteEl) gtStatusNoteEl.textContent = String(err?.message || err || "Failed to save correction.");
  } finally {
    setGtSaving(false);
  }
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
    if (ex) renderExample(ex, { focus: false, focusTag: target.tag });
  });
}

updateSearchToggleLabel();

initViewer()
  .then(() => {
    pendingSelection = getEvalParams();
    return loadRuns().catch(() => setRunEmptyState());
  })
  .catch(() => {});
