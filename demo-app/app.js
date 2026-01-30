const DEFAULT_QUESTION = "What is the patient name?";
const DEFAULT_DOC = "./assets/Physician_Report_Scanned.pdf";

const statusEl = document.getElementById("status");
const answerEl = document.getElementById("answer");
const sourceTextEl = document.getElementById("sourceText");
const sourceMetaEl = document.getElementById("sourceMeta");
const debugEl = document.getElementById("debug");
const questionEl = document.getElementById("question");

const btnPrepare = document.getElementById("btnPrepare");
const btnAsk = document.getElementById("btnAsk");
const btnClear = document.getElementById("btnClear");

let viewerInstance = null;
let annotationManager = null;
let documentViewer = null;
let Core = null;
let Annotations = null;

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

function setDebug(obj) {
  debugEl.textContent = obj ? JSON.stringify(obj, null, 2) : "";
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
  setStatus("Preparing cache...", "");
  btnPrepare.disabled = true;
  try {
    const data = await postJson("/api/preprocess", {});
    setStatus(`Cache ready. doc_hash=${data.doc_hash}`, "ok");
    setDebug(data);
  } catch (err) {
    setStatus(`Preprocess failed: ${err.message}`, "bad");
  } finally {
    btnPrepare.disabled = false;
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

  try {
    const data = await postJson("/api/ask", { question: q });
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
  } catch (err) {
    setStatus(`Ask failed: ${err.message}`, "bad");
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

questionEl.value = DEFAULT_QUESTION;
setAnswer("-");
setSource("-", "-");
setDebug(null);

initViewer()
  .then(() => setStatus("Viewer ready.", "ok"))
  .catch((err) => setStatus(`Viewer failed: ${err.message}`, "bad"));
