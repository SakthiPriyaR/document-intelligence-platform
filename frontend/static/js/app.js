/* Ledger dashboard UI. The backend API contract is unchanged. */

const API_BASE = "/api/v1";
const MAX_FILE_SIZE = 15 * 1024 * 1024;
const ALLOWED_EXTENSIONS = ["pdf", "jpg", "jpeg", "png"];

const els = {
  form: document.getElementById("processForm"),
  documentType: document.getElementById("documentType"),
  fileInput: document.getElementById("fileInput"),
  dropzone: document.getElementById("dropzone"),
  dropzoneLabel: document.getElementById("dropzoneLabel"),
  dropzoneHint: document.getElementById("dropzoneHint"),
  processBtn: document.getElementById("processBtn"),
  processStatus: document.getElementById("processStatus"),
  apiStatus: document.getElementById("apiStatus"),
  apiStatusText: document.getElementById("apiStatusText"),
  refreshBtn: document.getElementById("refreshBtn"),
  refreshIcon: document.getElementById("refreshIcon"),
  refreshText: document.getElementById("refreshText"),
  lastUpdated: document.getElementById("lastUpdated"),
  ledgerBody: document.getElementById("ledgerBody"),
  overlay: document.getElementById("detailOverlay"),
  closeDetailBtn: document.getElementById("closeDetailBtn"),
  detailType: document.getElementById("detailType"),
  detailTitle: document.querySelector(".detail__title"),
  fileValidationSummary: document.getElementById("fileValidationSummary"),
  fieldsGrid: document.getElementById("fieldsGrid"),
  lineItemsWrap: document.getElementById("lineItemsWrap"),
  validationSummary: document.getElementById("validationSummary"),
  checksBody: document.getElementById("checksBody"),
  rawJson: document.getElementById("rawJson"),
  stats: document.getElementById("dashboardStats"),
  searchInput: document.getElementById("searchInput"),
  statusFilter: document.getElementById("statusFilter"),
  typeFilter: document.getElementById("typeFilter"),
  workflowSteps: document.querySelectorAll(".workflow__step"),
  tabs: document.querySelectorAll(".detail__tab"),
  panes: {
    fields: document.getElementById("tabFields"),
    validation: document.getElementById("tabValidation"),
    json: document.getElementById("tabJson"),
  },
};

const DOC_TYPE_LABELS = {
  invoice: "Invoice",
  balance_sheet: "Balance sheet",
  profit_and_loss: "Profit & loss",
  cash_flow_statement: "Cash flow statement",
};
const WORKFLOW_ORDER = ["validate", "extract", "reconcile", "store"];
let allDocuments = [];
let activeDocumentName = null;
let detailPollTimer = null;
let detailPollToken = 0;

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

function formatBytes(bytes) {
  if (!bytes) return "0 KB";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function statusPill(status) {
  const normalized = status || "UNKNOWN";
  const cls = normalized === "PASS"
    ? "status-pill--pass"
    : normalized === "FAILED" || normalized === "FAIL"
    ? "status-pill--fail"
    : "status-pill--na";
  const label = normalized === "PROCESSING" ? "PROCESSING" : normalized;
  return `<span class="status-pill ${cls}">${escapeHtml(label)}</span>`;
}

function setApiStatus(state, message) {
  els.apiStatus.classList.remove("is-checking", "is-online", "is-offline");
  els.apiStatus.classList.add(state);
  els.apiStatusText.textContent = message;
}

async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    setApiStatus("is-online", "API connected");
  } catch {
    setApiStatus("is-offline", "API unavailable");
  }
}

/* ---------------- Dashboard list ---------------- */

async function loadDocuments({ silent = false } = {}) {
  if (!silent) {
    els.ledgerBody.innerHTML = `<tr class="ledger__empty-row"><td colspan="6">Loading your document ledger...</td></tr>`;
  }
  try {
    const res = await fetch(`${API_BASE}/documents`, { cache: "no-store" });
    if (!res.ok) throw new Error(`Failed to load documents (${res.status})`);
    const data = await res.json();
    allDocuments = data.documents || [];
    renderStats(allDocuments);
    renderTypeFilter(allDocuments);
    renderLedger(filteredDocuments());
    els.lastUpdated.textContent = `Synced ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  } catch (err) {
    if (!silent || !allDocuments.length) {
      els.ledgerBody.innerHTML = `<tr class="ledger__empty-row"><td colspan="6">Could not load documents: ${escapeHtml(err.message)}</td></tr>`;
    }
  }
}

function renderLedger(documents) {
  if (!documents.length) {
    els.ledgerBody.innerHTML = `<tr class="ledger__empty-row"><td colspan="6">No documents match these filters.</td></tr>`;
    return;
  }
  els.ledgerBody.innerHTML = documents.map((doc) => `
    <tr data-name="${escapeAttr(doc.document_name)}" tabindex="0" role="button" aria-label="Open ${escapeAttr(doc.document_name)}">
      <td data-label="Document">${escapeHtml(doc.document_name)}</td>
      <td data-label="Type">${escapeHtml(DOC_TYPE_LABELS[doc.document_type] || doc.document_type)}</td>
      <td data-label="Status">${statusPill(doc.processing_status)}</td>
      <td data-label="Confidence" class="num">${doc.overall_confidence != null ? `${(doc.overall_confidence * 100).toFixed(0)}%` : "—"}</td>
      <td data-label="Processed">${fmtDate(doc.processed_at || doc.created_at)}</td>
      <td class="table-action"><span class="row-arrow" aria-hidden="true">&rarr;</span></td>
    </tr>
  `).join("");

  els.ledgerBody.querySelectorAll("tr[data-name]").forEach((row) => {
    const open = () => openDetail(row.getAttribute("data-name"));
    row.addEventListener("click", open);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    });
  });
}

function filteredDocuments() {
  const query = (els.searchInput.value || "").toLowerCase().trim();
  return allDocuments.filter((doc) =>
    (!query || (doc.document_name || "").toLowerCase().includes(query)) &&
    (!els.statusFilter.value || doc.processing_status === els.statusFilter.value) &&
    (!els.typeFilter.value || doc.document_type === els.typeFilter.value)
  );
}

function renderStats(documents) {
  const processed = documents.length;
  const passed = documents.filter((d) => d.processing_status === "PASS").length;
  const failed = documents.filter((d) => ["FAILED", "FAIL"].includes(d.processing_status)).length;
  const confidences = documents.map((d) => d.overall_confidence).filter((v) => v != null);
  const average = confidences.length
    ? `${(confidences.reduce((a, b) => a + b, 0) / confidences.length * 100).toFixed(0)}%`
    : "—";
  const cards = [
    ["Processed", processed, "documents", ""],
    ["Passed", passed, "validation-ready", "stat-card--pass"],
    ["Needs attention", failed, "failed records", "stat-card--fail"],
    ["Avg confidence", average, confidences.length ? "across scored fields" : "not reported", ""],
  ];
  els.stats.innerHTML = cards.map(([label, value, note, cls]) => `
    <div class="stat-card ${cls}"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>
  `).join("");
}

function renderTypeFilter(documents) {
  const selected = els.typeFilter.value;
  const types = [...new Set(documents.map((d) => d.document_type).filter(Boolean))];
  els.typeFilter.innerHTML = `<option value="">All document types</option>`
    + types.map((type) => `<option value="${escapeAttr(type)}">${escapeHtml(DOC_TYPE_LABELS[type] || type)}</option>`).join("");
  els.typeFilter.value = types.includes(selected) ? selected : "";
}

/* ---------------- Upload / process ---------------- */

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = els.fileInput.files[0];
  if (!file) {
    setStatus("Choose a PDF, JPG or PNG before processing.", "error");
    return;
  }
  const extension = file.name.split(".").pop().toLowerCase();
  if (!ALLOWED_EXTENSIONS.includes(extension)) {
    setStatus("Only PDF, JPG, JPEG and PNG files are supported.", "error");
    return;
  }
  if (file.size > MAX_FILE_SIZE) {
    setStatus("This file is larger than the 15 MB limit.", "error");
    return;
  }

  els.processBtn.disabled = true;
  els.processBtn.classList.add("is-processing");
  els.processBtn.querySelector("span:first-child").textContent = "Processing";
  const startedAt = Date.now();
  setWorkflowStage("validate");
  const progressTimer = setInterval(() => {
    const seconds = Math.floor((Date.now() - startedAt) / 1000);
    const stage = seconds < 5 ? "validate" : seconds < 35 ? "extract" : "reconcile";
    setWorkflowStage(stage);
    const label = stage === "validate" ? "Validating file" : stage === "extract" ? "Extracting fields" : "Reconciling totals";
    setStatus(`${label} · ${seconds}s elapsed.`, "busy");
  }, 1000);

  const formData = new FormData();
  formData.append("file", file);
  formData.append("document_type", els.documentType.value);

  try {
    const res = await fetch(`${API_BASE}/documents/process`, { method: "POST", body: formData });
    const responseText = await res.text();
    let body = {};
    try { body = responseText ? JSON.parse(responseText) : {}; } catch { /* handled by the message below */ }
    if (!res.ok) throw new Error(body?.error?.message || `Request failed (${res.status || "empty response"})`);
    if (!responseText) throw new Error("The server returned an empty response. Please retry after the service wakes up.");

    activeDocumentName = body.document_name;
    els.form.reset();
    resetFilePicker();
    await loadDocuments({ silent: true });
    openDetailFromResponse(body, { fromUpload: true });
  } catch (err) {
    setStatus(`Could not process document: ${err.message}`, "error");
    setWorkflowStage("idle");
  } finally {
    clearInterval(progressTimer);
    els.processBtn.disabled = false;
    els.processBtn.classList.remove("is-processing");
    els.processBtn.querySelector("span:first-child").textContent = "Process document";
  }
});

function setStatus(message, state) {
  els.processStatus.textContent = message;
  els.processStatus.setAttribute("data-state", state);
}

function updateFilePicker(file) {
  if (!file) { resetFilePicker(); return; }
  els.dropzone.classList.add("has-file");
  els.dropzoneLabel.textContent = file.name;
  els.dropzoneHint.textContent = `${formatBytes(file.size)} · ready to process`;
}

function resetFilePicker() {
  els.fileInput.value = "";
  els.dropzone.classList.remove("has-file");
  els.dropzoneLabel.textContent = "Drop your document here";
  els.dropzoneHint.textContent = "or browse from your computer";
}

els.fileInput.addEventListener("change", () => updateFilePicker(els.fileInput.files[0]));
els.dropzone.addEventListener("dragover", (event) => { event.preventDefault(); els.dropzone.classList.add("is-dragover"); });
els.dropzone.addEventListener("dragleave", () => els.dropzone.classList.remove("is-dragover"));
els.dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  els.dropzone.classList.remove("is-dragover");
  const file = event.dataTransfer.files[0];
  if (!file) return;
  try {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    els.fileInput.files = transfer.files;
  } catch { /* Browsers without DataTransfer assignment still allow browsing. */ }
  updateFilePicker(file);
});

function setWorkflowStage(stage) {
  const index = WORKFLOW_ORDER.indexOf(stage);
  els.workflowSteps.forEach((step, stepIndex) => {
    step.classList.toggle("is-active", index >= 0 && stepIndex === index);
    step.classList.toggle("is-done", index >= 0 && stepIndex < index);
  });
}

async function refreshDocuments() {
  els.refreshBtn.disabled = true;
  els.refreshBtn.classList.add("is-refreshing");
  els.refreshText.textContent = "Syncing";
  await loadDocuments({ silent: true });
  els.refreshBtn.disabled = false;
  els.refreshBtn.classList.remove("is-refreshing");
  els.refreshText.textContent = "Refresh";
}

els.refreshBtn.addEventListener("click", refreshDocuments);
[els.searchInput, els.statusFilter, els.typeFilter].forEach((control) => control.addEventListener("input", () => renderLedger(filteredDocuments())));

/* ---------------- Detail drawer ---------------- */

async function openDetail(documentName, retryCount = 0) {
  activeDocumentName = documentName;
  try {
    const res = await fetch(`${API_BASE}/documents/${encodeURIComponent(documentName)}`, { cache: "no-store" });
    if (!res.ok) {
      if ([404, 429, 502, 503, 504].includes(res.status) && retryCount < 15) {
        scheduleDetailPoll(documentName, retryCount + 1, 2500);
        return;
      }
      throw new Error(`Could not load document (${res.status})`);
    }
    openDetailFromResponse(await res.json());
  } catch (err) {
    setStatus(err.message, "error");
  }
}

function scheduleDetailPoll(documentName, retryCount = 0, delay = 2500) {
  clearTimeout(detailPollTimer);
  const token = ++detailPollToken;
  detailPollTimer = setTimeout(() => {
    if (token === detailPollToken && activeDocumentName === documentName) openDetail(documentName, retryCount);
  }, delay);
}

function openDetailFromResponse(doc, { fromUpload = false } = {}) {
  const wasOpen = !els.overlay.hidden;
  const currentTab = [...els.tabs].find((tab) => tab.classList.contains("is-active"))?.dataset.tab || "fields";
  const isProcessing = doc.processing_status === "PROCESSING";
  const isFailed = doc.processing_status === "FAILED";
  const isPassed = doc.processing_status === "PASS";

  activeDocumentName = doc.document_name;
  els.detailType.textContent = DOC_TYPE_LABELS[doc.document_type] || doc.document_type;
  els.detailTitle.textContent = doc.document_name;

  const fv = doc.file_validation || {};
  els.fileValidationSummary.className = `callout ${fv.status === "PASS" ? "callout--pass" : "callout--fail"}`;
  els.fileValidationSummary.innerHTML = `File validation: ${statusPill(fv.status)} <span class="callout__separator">·</span> ${escapeHtml(fv.file_type || "unknown type")} <span class="callout__separator">·</span> ${fv.page_count ?? "?"} page(s)`
    + (fv.reason ? `<br>${escapeHtml(fv.reason)}` : "");

  const extracted = doc.extracted_data || {};
  const fieldEntries = Object.entries(extracted).filter(([key]) => key !== "line_items");
  els.fieldsGrid.innerHTML = isProcessing
    ? `<div class="field-card processing-state"><div class="field-card__value">Extraction is in progress...</div><div class="field-card__evidence">Fields and financial checks will appear automatically.</div></div>`
    : isFailed
    ? `<div class="field-card is-missing"><div class="field-card__value">Processing failed</div><div class="field-card__evidence">${escapeHtml(doc.error?.message || "The document could not be extracted.")}</div></div>`
    : fieldEntries.length
    ? fieldEntries.map(([key, field]) => renderFieldCard(key, field)).join("")
    : `<div class="field-card">No extracted fields available.</div>`;

  const lineItems = extracted.line_items;
  els.lineItemsWrap.innerHTML = Array.isArray(lineItems) && lineItems.length ? renderLineItems(lineItems) : "";

  const validation = doc.validation;
  if (validation) {
    const statusClass = validation.overall_status === "PASS" ? "callout--pass" : validation.overall_status === "FAIL" ? "callout--fail" : "callout--na";
    els.validationSummary.className = `callout ${statusClass}`;
    els.validationSummary.innerHTML = `Overall validation: ${statusPill(validation.overall_status)}`
      + (validation.issues && validation.issues.length ? `<ul>${validation.issues.map((issue) => `<li>${escapeHtml(issue)}</li>`).join("")}</ul>` : "");
    els.checksBody.innerHTML = (validation.checks || []).map(renderCheckRow).join("")
      || `<tr><td colspan="7">No checks were evaluated.</td></tr>`;
  } else {
    els.validationSummary.className = "callout";
    els.validationSummary.textContent = doc.error ? `Processing failed: ${doc.error.message}` : "No validation was run for this document.";
    els.checksBody.innerHTML = "";
  }

  els.rawJson.textContent = JSON.stringify(doc, null, 2);
  els.overlay.hidden = false;
  switchTab(wasOpen ? currentTab : "fields");

  if (isProcessing) {
    setWorkflowStage("extract");
    if (fromUpload) setStatus(`Queued — processing "${doc.document_name}" in the background.`, "busy");
    scheduleDetailPoll(doc.document_name);
  } else {
    clearTimeout(detailPollTimer);
    setWorkflowStage(isPassed ? "store" : "idle");
    if (activeDocumentName === doc.document_name) {
      if (isPassed) setStatus(`Done — "${doc.document_name}" processed successfully.`, "ok");
      if (isFailed) setStatus(`Processing failed: ${doc.error?.message || "see the detail panel."}`, "error");
    }
    loadDocuments({ silent: true });
  }
}

function renderFieldCard(key, field) {
  const value = field && typeof field === "object" ? field.value : field;
  const evidence = field && typeof field === "object" ? field.evidence : null;
  const confidence = field && typeof field === "object" ? field.confidence : null;
  const isMissing = value === null || value === undefined || value === "";
  const isLowConfidence = !isMissing && confidence != null && Number(confidence) < 0.6;
  const displayValue = value && typeof value === "object" ? JSON.stringify(value) : value;
  return `
    <div class="field-card ${isMissing ? "is-missing" : ""} ${isLowConfidence ? "is-low-confidence" : ""}">
      <div class="field-card__label">${escapeHtml(prettifyKey(key))}</div>
      <div class="field-card__value ${isMissing ? "is-null" : ""}">${isMissing ? "Not found" : escapeHtml(String(displayValue))}</div>
      ${isLowConfidence ? `<div class="field-card__confidence">Low confidence: ${(Number(confidence) * 100).toFixed(0)}%</div>` : ""}
      ${evidence && evidence.source_text ? `<div class="field-card__evidence">p.${evidence.page_number ?? "?"} — “${escapeHtml(evidence.source_text)}”</div>` : ""}
    </div>`;
}

function renderLineItems(items) {
  const columns = Array.from(items.reduce((set, item) => {
    Object.keys(item || {}).forEach((key) => set.add(key));
    return set;
  }, new Set()));
  return `
    <h3>Line items</h3>
    <div class="line-items-shell"><table class="line-items-table">
      <thead><tr>${columns.map((column) => `<th${isNumericColumn(items, column) ? ' class="num"' : ""}>${escapeHtml(prettifyKey(column))}</th>`).join("")}</tr></thead>
      <tbody>${items.map((item) => `<tr>${columns.map((column) => `<td${isNumericColumn(items, column) ? ' class="num"' : ""}>${item[column] != null ? escapeHtml(String(item[column])) : "—"}</td>`).join("")}</tr>`).join("")}</tbody>
    </table></div>`;
}

function isNumericColumn(items, column) { return items.some((item) => typeof item[column] === "number"); }

function renderCheckRow(check) {
  return `
    <tr>
      <td>${escapeHtml(prettifyKey(check.name || "Check"))}</td>
      <td>${escapeHtml(check.period || "—")}</td>
      <td>${escapeHtml(check.formula || "—")}</td>
      <td class="num">${check.calculated_value ?? "—"}</td>
      <td class="num">${check.reported_value ?? "—"}</td>
      <td class="num">${check.variance ?? "—"}</td>
      <td>${statusPill(check.status)}</td>
    </tr>`;
}

function prettifyKey(key) { return String(key).replace(/__/g, " — ").replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase()); }

els.closeDetailBtn.addEventListener("click", closeDetail);
els.overlay.addEventListener("click", (event) => { if (event.target === els.overlay) closeDetail(); });
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDetail(); });
function closeDetail() { clearTimeout(detailPollTimer); detailPollToken += 1; els.overlay.hidden = true; }

els.tabs.forEach((tab) => tab.addEventListener("click", () => switchTab(tab.dataset.tab)));
function switchTab(name) {
  els.tabs.forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  Object.entries(els.panes).forEach(([key, pane]) => pane.classList.toggle("is-active", key === name));
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}
function escapeAttr(value) { return escapeHtml(value); }

setWorkflowStage("idle");
loadDocuments();
checkHealth();
