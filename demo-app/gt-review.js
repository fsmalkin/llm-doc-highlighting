const VALUE_TYPES = [
  "",
  "Date",
  "Duration",
  "Name",
  "Phone",
  "Email",
  "Address",
  "Number",
  "Currency",
  "Free-text",
];

const state = {
  docId: null,
  docs: [],
  prompts: [],
  items: [],
  selectedKey: null,
  promptFilter: "",
  docFilter: "",
  showGt: false,
  showSaved: true,
  image: {
    naturalWidth: 1,
    naturalHeight: 1,
    displayWidth: 1,
    displayHeight: 1,
  },
};

const dom = {
  docSelect: document.getElementById("docSelect"),
  docSearch: document.getElementById("docSearch"),
  docMeta: document.getElementById("docMeta"),
  promptSearch: document.getElementById("promptSearch"),
  promptList: document.getElementById("promptList"),
  addCustom: document.getElementById("addCustom"),
  expectedText: document.getElementById("expectedText"),
  rawText: document.getElementById("rawText"),
  indexedText: document.getElementById("indexedText"),
  toggleGt: document.getElementById("toggleGt"),
  toggleSaved: document.getElementById("toggleSaved"),
  gtHint: document.getElementById("gtHint"),
  fieldLabel: document.getElementById("fieldLabel"),
  valueInput: document.getElementById("valueInput"),
  valueType: document.getElementById("valueType"),
  notesInput: document.getElementById("notesInput"),
  bboxInput: document.getElementById("bboxInput"),
  clearBox: document.getElementById("clearBox"),
  useExpected: document.getElementById("useExpected"),
  useRaw: document.getElementById("useRaw"),
  useIndexed: document.getElementById("useIndexed"),
  saveBtn: document.getElementById("saveBtn"),
  saveStatus: document.getElementById("saveStatus"),
  statusText: document.getElementById("statusText"),
  docImage: document.getElementById("docImage"),
  overlay: document.getElementById("overlay"),
  viewerStage: document.querySelector(".viewer-stage"),
  imageLayer: document.querySelector(".image-layer"),
};

let dragState = null;

function setStatus(text) {
  dom.statusText.textContent = text;
}

function setSaveStatus(text, isError = false) {
  dom.saveStatus.textContent = text;
  dom.saveStatus.style.color = isError ? "var(--bad)" : "var(--muted)";
}

function buildKey(item) {
  if (item.links && item.links.eval_example_id) {
    return `ex:${item.links.eval_example_id}`;
  }
  if (item.item_id) {
    return `id:${item.item_id}`;
  }
  return `label:${item.field_label || ""}`;
}

function buildItemFromPrompt(prompt) {
  const key = prompt.example_id ? `ex:${prompt.example_id}` : `label:${prompt.field_label}`;
  return {
    key,
    field_label: prompt.field_label || "",
    value: "",
    value_type: "",
    notes: "",
    bbox: null,
    prompt,
    gt_boxes: prompt.gt_boxes || [],
    links: {
      eval_example_id: prompt.example_id || "",
      eval_run: prompt.run || "",
      eval_url_params: prompt.eval_url_params || "",
    },
  };
}

function buildCustomItem() {
  const key = `custom:${Date.now()}`;
  return {
    key,
    field_label: "",
    value: "",
    value_type: "",
    notes: "",
    bbox: null,
    prompt: null,
    links: {},
  };
}

function updateValueTypeOptions() {
  dom.valueType.innerHTML = "";
  VALUE_TYPES.forEach((val) => {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = val === "" ? "(none)" : val;
    dom.valueType.appendChild(opt);
  });
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok || data.ok === false) {
    const msg = data.error || `Request failed: ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

async function loadDocs() {
  setStatus("Loading documents...");
  const data = await fetchJson("/api/gt/docs");
  state.docs = data.docs || [];
  renderDocOptions();
  const params = new URLSearchParams(window.location.search);
  const docParam = params.get("doc");
  if (docParam && state.docs.some((d) => d.doc_id === docParam)) {
    dom.docSelect.value = docParam;
  }
  if (state.docs.length > 0) {
    await loadDoc(dom.docSelect.value || state.docs[0].doc_id);
  } else {
    setStatus("No docs found. Add eval-review-2.md or dataset images.");
  }
}

async function loadDoc(docId) {
  if (!docId) return;
  state.docId = docId;
  setStatus(`Loading ${docId}...`);
  dom.docMeta.textContent = "";

  const [promptsData, correctionsData] = await Promise.all([
    fetchJson(`/api/gt/prompts?doc=${encodeURIComponent(docId)}`),
    fetchJson(`/api/gt/corrections?doc=${encodeURIComponent(docId)}`),
  ]);

  state.prompts = promptsData.prompts || [];

  const existingItems = (correctionsData.payload && correctionsData.payload.items) || [];
  const itemsByKey = new Map();
  existingItems.forEach((item) => {
    const key = buildKey(item);
    itemsByKey.set(key, {
      key,
      field_label: item.field_label || "",
      value: item.value || "",
      value_type: item.value_type || "",
      notes: item.notes || "",
      bbox: item.bbox || null,
      prompt: null,
      links: item.links || {},
      item_id: item.item_id || "",
      source: item.source || null,
    });
  });

  const mergedItems = [];
  state.prompts.forEach((prompt) => {
    const promptKey = prompt.example_id ? `ex:${prompt.example_id}` : `label:${prompt.field_label}`;
    if (itemsByKey.has(promptKey)) {
      const item = itemsByKey.get(promptKey);
      item.prompt = prompt;
      if (!item.links) {
        item.links = {};
      }
      item.links.eval_example_id = prompt.example_id || item.links.eval_example_id || "";
      item.links.eval_run = prompt.run || item.links.eval_run || "";
      item.links.eval_url_params = prompt.eval_url_params || item.links.eval_url_params || "";
      mergedItems.push(item);
    } else {
      mergedItems.push(buildItemFromPrompt(prompt));
    }
  });

  // Add any remaining existing items as custom entries.
  itemsByKey.forEach((item, key) => {
    const exists = mergedItems.some((entry) => entry.key === key);
    if (!exists) {
      mergedItems.push(item);
    }
  });

  state.items = mergedItems;
  renderPromptList();

  const promptCount = state.prompts.length;
  const savedCount = existingItems.length;
  dom.docMeta.textContent = `Prompts: ${promptCount} | Saved: ${savedCount}`;

  await loadImage(docId);

  const firstItem = state.items[0];
  if (firstItem) {
    selectItem(firstItem.key);
  }
  setStatus("Ready. Drag on the image to draw a box.");
}

function renderDocOptions() {
  const filter = state.docFilter.trim().toLowerCase();
  dom.docSelect.innerHTML = "";
  const docs = state.docs.filter((doc) => doc.doc_id.toLowerCase().includes(filter));
  docs.forEach((doc) => {
    const opt = document.createElement("option");
    opt.value = doc.doc_id;
    opt.textContent = `${doc.doc_id} (${doc.prompt_count})`;
    dom.docSelect.appendChild(opt);
  });
  if (!docs.find((doc) => doc.doc_id === dom.docSelect.value)) {
    if (docs[0]) {
      dom.docSelect.value = docs[0].doc_id;
    }
  }
}

async function loadImage(docId) {
  return new Promise((resolve, reject) => {
    dom.docImage.onload = () => {
      state.image.naturalWidth = dom.docImage.naturalWidth || 1;
      state.image.naturalHeight = dom.docImage.naturalHeight || 1;
      updateCanvasSize();
      renderOverlay();
      resolve();
    };
    dom.docImage.onerror = () => {
      setStatus("Image failed to load. Check dataset path.");
      reject(new Error("Image load failed"));
    };
    dom.docImage.src = `/api/gt/image?doc=${encodeURIComponent(docId)}`;
  });
}

function updateCanvasSize() {
  const width = dom.docImage.clientWidth || 1;
  const height = dom.docImage.clientHeight || 1;
  state.image.displayWidth = width;
  state.image.displayHeight = height;
  dom.overlay.width = width;
  dom.overlay.height = height;
  dom.overlay.style.left = "0px";
  dom.overlay.style.top = "0px";
}

function renderPromptList() {
  dom.promptList.innerHTML = "";
  const filter = state.promptFilter.trim().toLowerCase();
  state.items
    .filter((item) => {
      if (!filter) return true;
      const label = (item.field_label || "").toLowerCase();
      const expected = (item.prompt && item.prompt.expected) ? item.prompt.expected.toLowerCase() : "";
      return label.includes(filter) || expected.includes(filter);
    })
    .forEach((item) => {
    const btn = document.createElement("button");
    btn.className = "prompt-item" + (item.key === state.selectedKey ? " active" : "");
    btn.type = "button";
    const title = document.createElement("div");
    title.className = "prompt-title";
    title.textContent = item.field_label || "(untitled)";
    const meta = document.createElement("div");
    meta.className = "prompt-meta";
    if (item.prompt) {
      const expected = item.prompt.expected || "";
      meta.textContent = expected ? `Expected: ${expected}` : "Prompt item";
    } else {
      meta.textContent = "Custom correction";
    }
    const chips = document.createElement("div");
    chips.className = "prompt-chips";
    const valChip = document.createElement("span");
    valChip.className = "chip" + (item.value ? " ok" : " warn");
    valChip.textContent = item.value ? "value" : "no value";
    const boxChip = document.createElement("span");
    boxChip.className = "chip" + (item.bbox ? " ok" : " warn");
    boxChip.textContent = item.bbox ? "bbox" : "no bbox";
    const gtChip = document.createElement("span");
    const gtCount = (item.prompt && item.prompt.gt_boxes) ? item.prompt.gt_boxes.length : 0;
    gtChip.className = "chip gt";
    gtChip.textContent = gtCount ? `gt ${gtCount}` : "gt -";
    chips.appendChild(valChip);
    chips.appendChild(boxChip);
    chips.appendChild(gtChip);
    btn.appendChild(title);
    btn.appendChild(meta);
    btn.appendChild(chips);
    btn.addEventListener("click", () => selectItem(item.key));
    dom.promptList.appendChild(btn);
  });
}

function selectItem(key) {
  const item = state.items.find((entry) => entry.key === key);
  if (!item) return;
  state.selectedKey = key;
  dom.expectedText.textContent = item.prompt && item.prompt.expected ? item.prompt.expected : "-";
  dom.rawText.textContent = item.prompt && item.prompt.raw ? item.prompt.raw : "-";
  dom.indexedText.textContent = item.prompt && item.prompt.indexed ? item.prompt.indexed : "-";
  dom.fieldLabel.value = item.field_label || "";
  dom.valueInput.value = item.value || "";
  dom.valueType.value = item.value_type || "";
  dom.notesInput.value = item.notes || "";
  dom.bboxInput.value = item.bbox ? item.bbox.join(", ") : "";
  updateGtHint();
  renderPromptList();
  renderOverlay();
}

function updateSelectedItem(updates) {
  const item = state.items.find((entry) => entry.key === state.selectedKey);
  if (!item) return;
  Object.assign(item, updates);
  renderPromptList();
  renderOverlay();
}

function getScale() {
  const scaleX = state.image.naturalWidth / state.image.displayWidth;
  const scaleY = state.image.naturalHeight / state.image.displayHeight;
  return { scaleX, scaleY };
}

function renderOverlay() {
  const ctx = dom.overlay.getContext("2d");
  ctx.clearRect(0, 0, dom.overlay.width, dom.overlay.height);
  const { scaleX, scaleY } = getScale();
  if (state.showSaved) {
    state.items.forEach((item) => {
      if (!item.bbox) return;
      const [x0, y0, x1, y1] = item.bbox;
      const left = x0 / scaleX;
      const top = y0 / scaleY;
      const width = (x1 - x0) / scaleX;
      const height = (y1 - y0) / scaleY;
      ctx.lineWidth = item.key === state.selectedKey ? 3 : 2;
      ctx.strokeStyle = item.key === state.selectedKey ? "#8bd5ca" : "#7aa2f7";
      ctx.strokeRect(left, top, width, height);
    });
  } else {
    const selected = state.items.find((entry) => entry.key === state.selectedKey);
    if (selected && selected.bbox) {
      const [x0, y0, x1, y1] = selected.bbox;
      const left = x0 / scaleX;
      const top = y0 / scaleY;
      const width = (x1 - x0) / scaleX;
      const height = (y1 - y0) / scaleY;
      ctx.lineWidth = 3;
      ctx.strokeStyle = "#8bd5ca";
      ctx.strokeRect(left, top, width, height);
    }
  }

  if (state.showGt) {
    const selected = state.items.find((entry) => entry.key === state.selectedKey);
    const gtBoxes = selected && selected.prompt ? selected.prompt.gt_boxes || [] : [];
    gtBoxes.forEach((bbox) => {
      if (!bbox || bbox.length !== 4) return;
      const [x0, y0, x1, y1] = bbox;
      const left = x0 / scaleX;
      const top = y0 / scaleY;
      const width = (x1 - x0) / scaleX;
      const height = (y1 - y0) / scaleY;
      ctx.lineWidth = 2;
      ctx.strokeStyle = "#7ee787";
      ctx.strokeRect(left, top, width, height);
    });
  }

  if (dragState && dragState.preview) {
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#ffcc66";
    ctx.strokeRect(dragState.preview.x, dragState.preview.y, dragState.preview.w, dragState.preview.h);
  }
}

function onMouseDown(event) {
  if (!state.selectedKey) return;
  const rect = dom.overlay.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  dragState = { startX: x, startY: y, preview: null };
  dom.overlay.addEventListener("mousemove", onMouseMove);
  window.addEventListener("mouseup", onMouseUp);
}

function onMouseMove(event) {
  if (!dragState) return;
  const rect = dom.overlay.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const left = Math.min(dragState.startX, x);
  const top = Math.min(dragState.startY, y);
  const width = Math.abs(dragState.startX - x);
  const height = Math.abs(dragState.startY - y);
  dragState.preview = { x: left, y: top, w: width, h: height };
  renderOverlay();
}

function onMouseUp(event) {
  if (!dragState) return;
  const rect = dom.overlay.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const left = Math.min(dragState.startX, x);
  const top = Math.min(dragState.startY, y);
  const width = Math.abs(dragState.startX - x);
  const height = Math.abs(dragState.startY - y);
  dragState = null;
  dom.overlay.removeEventListener("mousemove", onMouseMove);
  window.removeEventListener("mouseup", onMouseUp);

  if (width < 4 || height < 4) {
    renderOverlay();
    return;
  }

  const { scaleX, scaleY } = getScale();
  const x0 = Math.round(left * scaleX * 100) / 100;
  const y0 = Math.round(top * scaleY * 100) / 100;
  const x1 = Math.round((left + width) * scaleX * 100) / 100;
  const y1 = Math.round((top + height) * scaleY * 100) / 100;
  updateSelectedItem({ bbox: [x0, y0, x1, y1] });
  dom.bboxInput.value = `${x0}, ${y0}, ${x1}, ${y1}`;
  renderOverlay();
}

async function saveCorrections() {
  const itemsToSave = state.items
    .filter((item) => item.value && item.bbox)
    .map((item) => {
      const payload = {
        field_label: item.field_label,
        value: item.value,
        bbox: item.bbox,
      };
      if (item.value_type) payload.value_type = item.value_type;
      if (item.notes) payload.notes = item.notes;
      if (item.item_id) payload.item_id = item.item_id;
      if (item.links && Object.keys(item.links).length > 0) payload.links = item.links;
      if (item.source) payload.source = item.source;
      return payload;
    });

  if (itemsToSave.length === 0) {
    setSaveStatus("Nothing to save. Add a value and bbox.", true);
    return;
  }

  setSaveStatus("Saving...");
  try {
    const res = await fetchJson("/api/gt/corrections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_id: state.docId, items: itemsToSave }),
    });
    setSaveStatus(`Saved ${res.item_count} items. Dropped ${res.dropped}.`);
  } catch (err) {
    setSaveStatus(err.message || "Save failed", true);
  }
}

function wireEvents() {
  dom.docSelect.addEventListener("change", (event) => {
    loadDoc(event.target.value);
  });

  dom.docSearch.addEventListener("input", (event) => {
    state.docFilter = event.target.value || "";
    renderDocOptions();
    if (dom.docSelect.value && dom.docSelect.value !== state.docId) {
      loadDoc(dom.docSelect.value);
    }
  });

  dom.promptSearch.addEventListener("input", (event) => {
    state.promptFilter = event.target.value || "";
    renderPromptList();
  });

  dom.addCustom.addEventListener("click", () => {
    const item = buildCustomItem();
    state.items.push(item);
    renderPromptList();
    selectItem(item.key);
  });

  dom.fieldLabel.addEventListener("input", (event) => {
    updateSelectedItem({ field_label: event.target.value });
  });

  dom.valueInput.addEventListener("input", (event) => {
    updateSelectedItem({ value: event.target.value });
  });

  dom.valueType.addEventListener("change", (event) => {
    updateSelectedItem({ value_type: event.target.value });
  });

  dom.notesInput.addEventListener("input", (event) => {
    updateSelectedItem({ notes: event.target.value });
  });

  dom.clearBox.addEventListener("click", () => {
    updateSelectedItem({ bbox: null });
    dom.bboxInput.value = "";
  });

  dom.useExpected.addEventListener("click", () => {
    const item = state.items.find((entry) => entry.key === state.selectedKey);
    if (item && item.prompt && item.prompt.expected) {
      updateSelectedItem({ value: item.prompt.expected });
      dom.valueInput.value = item.prompt.expected;
    }
  });

  dom.useRaw.addEventListener("click", () => {
    const item = state.items.find((entry) => entry.key === state.selectedKey);
    if (item && item.prompt && item.prompt.raw) {
      updateSelectedItem({ value: item.prompt.raw });
      dom.valueInput.value = item.prompt.raw;
    }
  });

  dom.useIndexed.addEventListener("click", () => {
    const item = state.items.find((entry) => entry.key === state.selectedKey);
    if (item && item.prompt && item.prompt.indexed) {
      updateSelectedItem({ value: item.prompt.indexed });
      dom.valueInput.value = item.prompt.indexed;
    }
  });

  dom.saveBtn.addEventListener("click", saveCorrections);

  dom.toggleGt.addEventListener("click", () => {
    state.showGt = !state.showGt;
    updateGtHint();
    renderOverlay();
  });

  dom.toggleSaved.addEventListener("click", () => {
    state.showSaved = !state.showSaved;
    updateSavedToggle();
    renderOverlay();
  });

  dom.expectedText.addEventListener("click", () => {
    state.showGt = true;
    updateGtHint();
    renderOverlay();
  });

  dom.docImage.addEventListener("load", updateCanvasSize);
  window.addEventListener("resize", () => {
    updateCanvasSize();
    renderOverlay();
  });

  dom.overlay.addEventListener("mousedown", onMouseDown);
}

function updateGtHint() {
  const selected = state.items.find((entry) => entry.key === state.selectedKey);
  const gtBoxes = selected && selected.prompt ? selected.prompt.gt_boxes || [] : [];
  if (gtBoxes.length) {
    dom.gtHint.textContent = `GT boxes: ${gtBoxes.length}`;
  } else {
    dom.gtHint.textContent = "GT boxes: none detected for this label.";
  }
  dom.toggleGt.textContent = state.showGt ? "Hide GT boxes" : "Reveal GT boxes";
  dom.toggleGt.classList.toggle("active", state.showGt);
}

function updateSavedToggle() {
  dom.toggleSaved.textContent = state.showSaved ? "Show saved boxes" : "Hide saved boxes";
  dom.toggleSaved.classList.toggle("active", state.showSaved);
}

updateValueTypeOptions();
wireEvents();
updateSavedToggle();
loadDocs().catch((err) => {
  setStatus(err.message || "Failed to load docs");
});
