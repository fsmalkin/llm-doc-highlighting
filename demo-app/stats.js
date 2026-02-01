const statsRunSelectEl = document.getElementById("statsRunSelect");
const statsRunMetaEl = document.getElementById("statsRunMeta");
const openEvalLinkEl = document.getElementById("openEvalLink");

const metaDatasetEl = document.getElementById("metaDataset");
const metaSplitEl = document.getElementById("metaSplit");
const metaSamplesEl = document.getElementById("metaSamples");
const metaExcludedEl = document.getElementById("metaExcluded");
const metaEffectiveEl = document.getElementById("metaEffective");
const metaPromptEl = document.getElementById("metaPrompt");
const metaValueTypeEl = document.getElementById("metaValueType");
const metaModelEl = document.getElementById("metaModel");

const rawSpanValidEl = document.getElementById("rawSpanValid");
const rawMappingEl = document.getElementById("rawMapping");
const rawIoUEl = document.getElementById("rawIoU");
const rawPrecisionEl = document.getElementById("rawPrecision");
const rawRecallEl = document.getElementById("rawRecall");
const rawPass2El = document.getElementById("rawPass2");
const rawLatencyEl = document.getElementById("rawLatency");

const idxSpanValidEl = document.getElementById("idxSpanValid");
const idxMappingEl = document.getElementById("idxMapping");
const idxIoUEl = document.getElementById("idxIoU");
const idxPrecisionEl = document.getElementById("idxPrecision");
const idxRecallEl = document.getElementById("idxRecall");
const idxPass2El = document.getElementById("idxPass2");
const idxLatencyEl = document.getElementById("idxLatency");

async function getJson(url) {
  const res = await fetch(url, { method: "GET" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    const msg = data.error || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

function setText(el, value) {
  if (!el) return;
  el.textContent = value == null || value === "" ? "-" : String(value);
}

function fmtPercent(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return `${(num * 100).toFixed(1)}%`;
}

function fmtFloat(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return num.toFixed(2);
}

function fmtLatency(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return `${num.toFixed(2)}s`;
}

function computeSummary(examples, method) {
  const rows = (examples || [])
    .map((ex) => ex.methods?.[method]?.metrics || {})
    .filter((row) => !row?.excluded);
  if (!rows.length) return {};
  const avg = (key) => {
    const vals = rows.map((r) => Number(r[key])).filter((v) => Number.isFinite(v));
    if (!vals.length) return 0;
    return vals.reduce((sum, v) => sum + v, 0) / vals.length;
  };
  return {
    span_valid_rate: avg("span_valid"),
    mapping_success_rate: avg("mapping_success"),
    avg_word_iou: avg("word_iou"),
    avg_precision: avg("precision"),
    avg_recall: avg("recall"),
    pass2_rate: avg("used_pass2"),
    avg_latency_sec: avg("latency_sec"),
  };
}

function renderSummary(summary, prefix) {
  if (prefix === "raw") {
    setText(rawSpanValidEl, fmtPercent(summary?.span_valid_rate));
    setText(rawMappingEl, fmtPercent(summary?.mapping_success_rate));
    setText(rawIoUEl, fmtFloat(summary?.avg_word_iou));
    setText(rawPrecisionEl, fmtFloat(summary?.avg_precision));
    setText(rawRecallEl, fmtFloat(summary?.avg_recall));
    setText(rawPass2El, fmtPercent(summary?.pass2_rate));
    setText(rawLatencyEl, fmtLatency(summary?.avg_latency_sec));
  } else {
    setText(idxSpanValidEl, fmtPercent(summary?.span_valid_rate));
    setText(idxMappingEl, fmtPercent(summary?.mapping_success_rate));
    setText(idxIoUEl, fmtFloat(summary?.avg_word_iou));
    setText(idxPrecisionEl, fmtFloat(summary?.avg_precision));
    setText(idxRecallEl, fmtFloat(summary?.avg_recall));
    setText(idxPass2El, fmtPercent(summary?.pass2_rate));
    setText(idxLatencyEl, fmtLatency(summary?.avg_latency_sec));
  }
}

async function loadRuns() {
  const data = await getJson("/api/eval_runs");
  const runs = data?.runs || [];
  statsRunSelectEl.innerHTML = "";
  if (!runs.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No runs found";
    statsRunSelectEl.appendChild(opt);
    if (openEvalLinkEl) {
      openEvalLinkEl.href = "/eval.html";
    }
    return;
  }
  for (const name of runs) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    statsRunSelectEl.appendChild(opt);
  }
  statsRunSelectEl.value = runs[0];
  await loadRun(runs[0]);
}

async function loadRun(name) {
  if (!name) return;
  const data = await getJson(`/api/eval_run?name=${encodeURIComponent(name)}`);
  const meta = data?.meta || {};
  setText(statsRunMetaEl, `dataset ${meta.dataset} | split ${meta.split} | samples ${meta.sample_size}`);
  if (openEvalLinkEl) {
    openEvalLinkEl.href = `/eval.html?run=${encodeURIComponent(name)}`;
  }
  setText(metaDatasetEl, meta.dataset);
  setText(metaSplitEl, meta.split);
  const examples = data?.examples || [];
  const excludedFromExamples = examples.filter((ex) => ex.gt_status === "exclude").length;
  const excluded =
    meta.excluded_count == null
      ? Number(meta.excluded ?? excludedFromExamples)
      : Number(meta.excluded_count ?? excludedFromExamples);
  const sampleSize = Number(meta.sample_size ?? examples.length);
  const effective = Number(meta.effective_samples ?? Math.max(0, sampleSize - (Number.isFinite(excluded) ? excluded : 0)));
  setText(metaSamplesEl, sampleSize);
  setText(metaExcludedEl, Number.isFinite(excluded) ? excluded : "-");
  setText(metaEffectiveEl, Number.isFinite(effective) ? effective : "-");
  setText(metaPromptEl, meta.prompt_mode);
  setText(metaValueTypeEl, meta.value_type);
  setText(metaModelEl, meta.model);

  const summary = data?.summary || {};
  const rawSummary = summary.raw || computeSummary(examples, "raw");
  const idxSummary = summary.indexed || computeSummary(examples, "indexed");

  renderSummary(rawSummary, "raw");
  renderSummary(idxSummary, "indexed");
}

statsRunSelectEl?.addEventListener("change", () => loadRun(String(statsRunSelectEl.value || "")));

loadRuns().catch(() => {});
