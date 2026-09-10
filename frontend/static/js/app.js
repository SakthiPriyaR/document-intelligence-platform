/* Document Intelligence dashboard — vanilla JS, talks to the FastAPI
   backend under /api/v1. No build step, no frameworks. */

const API_BASE = "/api/v1";

const els = {
  form: document.getElementById("processForm"),
  documentType: document.getElementById("documentType"),
  fileInput: document.getElementById("fileInput"),
  dropzone: document.getElementById("dropzone"),
  dropzoneLabel: document.getElementById("dropzoneLabel"),
  processBtn: document.getElementById("processBtn"),
  processStatus: document.getElementById("processStatus"),
  refreshBtn: document.getElementById("refreshBtn"),
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

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

function statusPill(status) {
  const cls = status === "PASS" ? "status-pill--pass" : status === "FAILED" || status === "FAIL" ? "status-pill--fail" : "status-pill--na";
  return `<span class="status-pill ${cls}">${status}</span>`;
}

/* ---------------- Dashboard list ---------------- */

async function loadDocuments() {
  els.ledgerBody.innerHTML = `<tr class="ledger__empty-row"><td colspan="5">Loading…</td></tr>`;
  try {
    const res = await fetch(`${API_BASE}/documents`);
    if (!res.ok) throw new Error(`Failed to load documents (${res.status})`);
    const data = await res.json();
    renderLedger(data.documents || []);
  } catch (err) {
    els.ledgerBody.innerHTML = `<tr class="ledger__empty-row"><td colspan="5">Could not load documents: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderLedger(documents) {
  if (!documents.length) {
    els.ledgerBody.innerHTML = `<tr class="ledger__empty-row"><td colspan="5">No documents processed yet. Upload one above to get started.</td></tr>`;
    return;
  }
  els.ledgerBody.innerHTML = documents.map((doc) => `
    <tr data-name="${escapeAttr(doc.document_name)}">
      <td data-label="Document">${escapeHtml(doc.document_name)}</td>
      <td data-label="Type">${DOC_TYPE_LABELS[doc.document_type] || doc.document_type}</td>
      <td data-label="Status">${statusPill(doc.processing_status)}</td>
      <td data-label="Confidence" class="num">${doc.overall_confidence != null ? (doc.overall_confidence * 100).toFixed(0) + "%" : "—"}</td>
      <td data-label="Processed">${fmtDate(doc.processed_at)}</td>
    </tr>
  `).join("");

  els.ledgerBody.querySelectorAll("tr[data-name]").forEach((row) => {
    row.addEventListener("click", () => openDetail(row.getAttribute("data-name")));
  });
}

/* ---------------- Upload / process ---------------- */

els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = els.fileInput.files[0];
  if (!file) return;

  els.processBtn.disabled = true;
  setStatus("Uploading and processing — this can take a little while for scanned documents…", "busy");

  const formData = new FormData();
  formData.append("file", file);
  formData.append("document_type", els.documentType.value);

  try {
    const res = await fetch(`${API_BASE}/documents/process`, { method: "POST", body: formData });
    const body = await res.json();
    if (!res.ok) {
      throw new Error(body?.error?.message || `Request failed (${res.status})`);
    }
    if (body.processing_status === "FAILED") {
      setStatus(`Processed with status FAILED: ${body.error ? body.error.message : "see details in the ledger."}`, "error");
    } else {
      setStatus(`Done — "${body.document_name}" processed successfully.`, "ok");
    }
    els.form.reset();
    els.dropzoneLabel.textContent = "Choose a PDF, JPG or PNG — up to 3 pages";
    await loadDocuments();
    openDetailFromResponse(body);
  } catch (err) {
    setStatus(`Could not process document: ${err.message}`, "error");
  } finally {
    els.processBtn.disabled = false;
  }
});

function setStatus(message, state) {
  els.processStatus.textContent = message;
  els.processStatus.setAttribute("data-state", state);
}

els.fileInput.addEventListener("change", () => {
  const file = els.fileInput.files[0];
  els.dropzoneLabel.textContent = file ? file.name : "Choose a PDF, JPG or PNG — up to 3 pages";
});
["dragover", "dragleave", "drop"].forEach((evt) => {
  els.dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    els.dropzone.classList.toggle("is-dragover", evt === "dragover");
  });
});

els.refreshBtn.addEventListener("click", loadDocuments);

/* ---------------- Detail panel ---------------- */

async function openDetail(documentName) {
  try {
    const res = await fetch(`${API_BASE}/documents/${encodeURIComponent(documentName)}`);
    if (!res.ok) throw new Error(`Could not load document (${res.status})`);
    const body = await res.json();
    openDetailFromResponse(body);
  } catch (err) {
    setStatus(err.message, "error");
  }
}

function openDetailFromResponse(doc) {
  els.detailType.textContent = DOC_TYPE_LABELS[doc.document_type] || doc.document_type;
  els.detailTitle.textContent = doc.document_name;

  // File validation summary
  const fv = doc.file_validation || {};
  els.fileValidationSummary.className = `callout ${fv.status === "PASS" ? "callout--pass" : "callout--fail"}`;
  els.fileValidationSummary.innerHTML = `File validation: ${statusPill(fv.status)} &nbsp;·&nbsp; ${fv.file_type || "unknown type"} &nbsp;·&nbsp; ${fv.page_count ?? "?"} page(s)`
    + (fv.reason ? `<br>${escapeHtml(fv.reason)}` : "");

  // Fields grid
  const extracted = doc.extracted_data || {};
  const fieldEntries = Object.entries(extracted).filter(([key]) => key !== "line_items");
  els.fieldsGrid.innerHTML = fieldEntries.length
    ? fieldEntries.map(([key, field]) => renderFieldCard(key, field)).join("")
    : `<div class="field-card">No extracted fields available.</div>`;

  // Line items table
  const lineItems = extracted.line_items;
  els.lineItemsWrap.innerHTML = Array.isArray(lineItems) && lineItems.length ? renderLineItems(lineItems) : "";

  // Validation
  const validation = doc.validation;
  if (validation) {
    els.validationSummary.className = `callout ${validation.overall_status === "PASS" ? "callout--pass" : validation.overall_status === "FAIL" ? "callout--fail" : ""}`;
    els.validationSummary.innerHTML = `Overall validation: ${statusPill(validation.overall_status)}`
      + (validation.issues && validation.issues.length ? `<ul>${validation.issues.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>` : "");
    els.checksBody.innerHTML = (validation.checks || []).map(renderCheckRow).join("")
      || `<tr><td colspan="7">No checks were evaluated.</td></tr>`;
  } else {
    els.validationSummary.className = "callout";
    els.validationSummary.textContent = doc.error ? `Processing failed: ${doc.error.message}` : "No validation was run for this document.";
    els.checksBody.innerHTML = "";
  }

  els.rawJson.textContent = JSON.stringify(doc, null, 2);

  switchTab("fields");
  els.overlay.hidden = false;
}

function renderFieldCard(key, field) {
  const value = field && typeof field === "object" ? field.value : field;
  const evidence = field && typeof field === "object" ? field.evidence : null;
  const isMissing = value === null || value === undefined || value === "";
  return `
    <div class="field-card ${isMissing ? "is-missing" : ""}">
      <div class="field-card__label">${escapeHtml(prettifyKey(key))}</div>
      <div class="field-card__value ${isMissing ? "is-null" : ""}">${isMissing ? "Not found" : escapeHtml(String(value))}</div>
      ${evidence && evidence.source_text ? `<div class="field-card__evidence">p.${evidence.page_number ?? "?"} — “${escapeHtml(evidence.source_text)}”</div>` : ""}
    </div>`;
}

function renderLineItems(items) {
  const columns = Array.from(items.reduce((set, item) => {
    Object.keys(item || {}).forEach((k) => set.add(k));
    return set;
  }, new Set()));
  return `
    <h3>Line items</h3>
    <table class="line-items-table">
      <thead><tr>${columns.map((c) => `<th${isNumericColumn(items, c) ? ' class="num"' : ""}>${escapeHtml(prettifyKey(c))}</th>`).join("")}</tr></thead>
      <tbody>
        ${items.map((item) => `<tr>${columns.map((c) => `<td${isNumericColumn(items, c) ? ' class="num"' : ""}>${item[c] != null ? escapeHtml(String(item[c])) : "—"}</td>`).join("")}</tr>`).join("")}
      </tbody>
    </table>`;
}

function isNumericColumn(items, col) {
  return items.some((i) => typeof i[col] === "number");
}

function renderCheckRow(check) {
  return `
    <tr>
      <td>${escapeHtml(prettifyKey(check.name))}</td>
      <td>${escapeHtml(check.period || "—")}</td>
      <td>${escapeHtml(check.formula)}</td>
      <td class="num">${check.calculated_value ?? "—"}</td>
      <td class="num">${check.reported_value ?? "—"}</td>
      <td class="num">${check.variance ?? "—"}</td>
      <td>${statusPill(check.status)}</td>
    </tr>`;
}

function prettifyKey(key) {
  return key.replace(/__/g, " — ").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

els.closeDetailBtn.addEventListener("click", closeDetail);
els.overlay.addEventListener("click", (e) => { if (e.target === els.overlay) closeDetail(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDetail(); });

function closeDetail() { els.overlay.hidden = true; }

els.tabs.forEach((tab) => tab.addEventListener("click", () => switchTab(tab.dataset.tab)));

function switchTab(name) {
  els.tabs.forEach((t) => t.classList.toggle("is-active", t.dataset.tab === name));
  Object.entries(els.panes).forEach(([key, pane]) => pane.classList.toggle("is-active", key === name));
}

/* ---------------- utils ---------------- */

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function escapeAttr(str) { return escapeHtml(str); }

loadDocuments();
