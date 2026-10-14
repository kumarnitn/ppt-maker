// PPT Master Standalone Application Client

let activeJobId = null;
let pollTimer = null;
let currentPlan = null;

document.addEventListener("DOMContentLoaded", () => {
  initNavigation();
  initDropzone();
  initCreateForm();
  initModals();
  loadSystemSettings();
  loadHistory();
});

// Navigation Tabs
function initNavigation() {
  const tabs = document.querySelectorAll(".nav-btn");
  tabs.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetTab = btn.getAttribute("data-tab");
      switchTab(targetTab);
    });
  });
}

function switchTab(tabName) {
  document.querySelectorAll(".nav-btn").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-tab") === tabName);
  });
  document.querySelectorAll(".view-section").forEach(sec => {
    sec.classList.toggle("active", sec.id === `view-${tabName}`);
  });
  if (tabName === "history") loadHistory();
  if (tabName === "settings") loadSystemSettings();
}

// File Dropzone
function initDropzone() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const badge = document.getElementById("file-badge");

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      fileInput.files = e.dataTransfer.files;
      updateFileBadge(fileInput.files[0]);
    }
  });
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) {
      updateFileBadge(fileInput.files[0]);
    }
  });

  function updateFileBadge(file) {
    badge.style.display = "inline-block";
    badge.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    const projInput = document.getElementById("project_name");
    if (!projInput.value) {
      projInput.value = file.name.replace(/\.[^/.]+$/, "");
    }
  }
}

// Create Form
function initCreateForm() {
  const form = document.getElementById("create-form");
  const autoApproveCheck = document.getElementById("auto_approve");
  const autoApproveLabel = document.getElementById("auto_approve_label");
  const imgProviderSelect = document.getElementById("image_provider");
  const fluxKeyGroup = document.getElementById("flux-key-group");

  if (imgProviderSelect && fluxKeyGroup) {
    imgProviderSelect.addEventListener("change", () => {
      fluxKeyGroup.style.display = imgProviderSelect.value === "flux" ? "block" : "none";
    });
  }

  autoApproveCheck.addEventListener("change", () => {
    autoApproveLabel.textContent = autoApproveCheck.checked
      ? "Auto-Proceed (No Review Pause)"
      : "Pause for Plan Review & Approval";
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btnSubmit = document.getElementById("btn-submit");
    btnSubmit.disabled = true;
    btnSubmit.innerHTML = `<span>⏳ Submitting...</span>`;

    const formData = new FormData(form);
    const fileInput = document.getElementById("file-input");
    if (fileInput.files.length > 0) {
      formData.set("file", fileInput.files[0]);
    }
    formData.set("auto_approve", autoApproveCheck.checked ? "true" : "false");
    formData.set("enable_notes", document.getElementById("enable_notes").checked ? "true" : "false");
    const animCheck = document.getElementById("enable_animations");
    if (animCheck) {
      formData.set("enable_animations", animCheck.checked ? "true" : "false");
    }
    const transSelect = document.getElementById("transition");
    if (transSelect) {
      formData.set("transition", transSelect.value);
    }
    if (imgProviderSelect) {
      formData.set("image_provider", imgProviderSelect.value);
    }
    const fluxKeyInput = document.getElementById("flux_api_key");
    if (fluxKeyInput && fluxKeyInput.value.trim()) {
      formData.set("flux_api_key", fluxKeyInput.value.trim());
    }

    try {
      const res = await fetch("/api/jobs", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.error || "Failed to start presentation job.");
        btnSubmit.disabled = false;
        btnSubmit.innerHTML = `<span>🚀 Generate Presentation</span>`;
        return;
      }

      activeJobId = data.job_id;
      document.getElementById("nav-active-job").style.display = "inline-block";
      switchTab("active-job");
      startPolling(activeJobId);
    } catch (err) {
      alert("Network error: " + err);
    } finally {
      btnSubmit.disabled = false;
      btnSubmit.innerHTML = `<span>🚀 Generate Presentation</span>`;
    }
  });
}

// Active Job Polling
function startPolling(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollJob(jobId);
  pollTimer = setInterval(() => pollJob(jobId), 1500);
}

async function pollJob(jobId) {
  try {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) return;
    const job = await res.json();
    renderJobStatus(job);

    if (job.status === "COMPLETED" || job.status === "FAILED") {
      clearInterval(pollTimer);
    }

    if (job.status === "AWAITING_APPROVAL" && !currentPlan) {
      openPlanModal(jobId);
    }
  } catch (err) {
    console.error("Poll error:", err);
  }
}

function renderJobStatus(job) {
  document.getElementById("job-title").textContent = job.project_name || "Presentation";
  document.getElementById("job-meta").textContent = `Job ID: ${job.job_id} | Created: ${new Date(job.created_at).toLocaleTimeString()}`;

  const badge = document.getElementById("job-status-badge");
  badge.textContent = job.status;
  badge.className = `status-badge ${job.status}`;

  document.getElementById("job-phase-text").textContent = job.phase;
  document.getElementById("job-progress-num").textContent = `${job.progress_percent}%`;
  document.getElementById("job-progress-bar").style.width = `${job.progress_percent}%`;

  // Action buttons
  const actionsDiv = document.getElementById("job-actions");
  const downloadBtn = document.getElementById("btn-download-pptx");
  const reviewBtn = document.getElementById("btn-review-plan");
  const resumeBtn = document.getElementById("btn-resume-job");

  actionsDiv.style.display = "flex";
  actionsDiv.style.gap = "12px";

  if (job.status === "COMPLETED" && job.download_url) {
    downloadBtn.style.display = "inline-flex";
    downloadBtn.href = job.download_url;
  } else {
    downloadBtn.style.display = "none";
  }

  if (job.status === "AWAITING_APPROVAL") {
    reviewBtn.style.display = "inline-flex";
    reviewBtn.onclick = () => openPlanModal(job.job_id);
  } else {
    reviewBtn.style.display = "none";
  }

  if (job.status === "FAILED") {
    resumeBtn.style.display = "inline-flex";
    resumeBtn.onclick = () => resumeJob(job.job_id);
  } else {
    resumeBtn.style.display = "none";
  }

  // Logs
  const logBox = document.getElementById("job-logs");
  if (job.logs && job.logs.length > 0) {
    logBox.innerHTML = job.logs.map(l => `
      <div class="log-entry ${l.status}">
        [${l.timestamp.split("T")[1].slice(0, 8)}] <strong>${l.step_name}</strong>: ${l.message}
      </div>
    `).join("");
    logBox.scrollTop = logBox.scrollHeight;
  }

  // Slide Thumbnails
  loadSlides(job.job_id);
}

let loadedSlideCount = -1;
async function loadSlides(jobId) {
  try {
    const res = await fetch(`/api/jobs/${jobId}/slides`);
    if (!res.ok) return;
    const slides = await res.json();
    if (slides.length === loadedSlideCount) return;
    loadedSlideCount = slides.length;

    document.getElementById("slide-count-badge").textContent = slides.length;
    const grid = document.getElementById("slides-grid");

    if (slides.length === 0) {
      grid.innerHTML = `<p style="color: var(--text-sub); font-size: 13px;">Slides will appear here as they are authored and validated...</p>`;
      return;
    }

    grid.innerHTML = "";
    slides.forEach(slide => {
      const card = document.createElement("div");
      card.className = "slide-card";
      card.innerHTML = `
        <div class="slide-thumb">
          <img src="${slide.preview_url}" style="width:100%; height:100%; object-fit:contain;" alt="Slide ${slide.slide_index}">
        </div>
        <div class="slide-card-footer">
          <span>Slide ${slide.slide_index}</span>
          <span style="color:var(--accent-blue); font-size:11px;">View Fullscreen</span>
        </div>
      `;
      card.onclick = () => openFullscreenSlide(slide.preview_url, `Slide ${slide.slide_index}`);
      grid.appendChild(card);
    });
  } catch (err) {
    console.error("Slides load error:", err);
  }
}

// Plan Modal
async function openPlanModal(jobId) {
  try {
    const res = await fetch(`/api/jobs/${jobId}/plan`);
    if (!res.ok) return;
    currentPlan = await res.json();

    const listDiv = document.getElementById("plan-slides-list");
    listDiv.innerHTML = currentPlan.slides.map((s, idx) => `
      <div style="background:var(--bg-tertiary); padding:14px; border-radius:8px; border:1px solid var(--border-color);">
        <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
          <strong style="color:var(--accent-blue);">Slide ${s.index}: ${s.slide_role.toUpperCase()}</strong>
          <span style="font-size:12px; color:var(--text-muted);">${s.layout_type}</span>
        </div>
        <input type="text" id="plan-title-${idx}" value="${escapeHtml(s.title)}" style="width:100%; margin-bottom:8px; font-weight:600;">
        <textarea id="plan-message-${idx}" rows="2" style="width:100%; font-size:13px;">${escapeHtml(s.core_message)}</textarea>
      </div>
    `).join("");

    document.getElementById("plan-modal").classList.add("active");
  } catch (err) {
    console.error("Plan fetch error:", err);
  }
}

function initModals() {
  document.getElementById("modal-close-btn").onclick = () => {
    document.getElementById("plan-modal").classList.remove("active");
  };
  document.getElementById("modal-cancel-btn").onclick = () => {
    document.getElementById("plan-modal").classList.remove("active");
  };

  document.getElementById("modal-approve-btn").onclick = async () => {
    if (!activeJobId || !currentPlan) return;
    // Collect edits
    currentPlan.slides.forEach((s, idx) => {
      const titleInput = document.getElementById(`plan-title-${idx}`);
      const messageInput = document.getElementById(`plan-message-${idx}`);
      if (titleInput) s.title = titleInput.value;
      if (messageInput) s.core_message = messageInput.value;
    });

    try {
      const res = await fetch(`/api/jobs/${activeJobId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved_plan: currentPlan }),
      });
      if (res.ok) {
        document.getElementById("plan-modal").classList.remove("active");
        startPolling(activeJobId);
      } else {
        alert("Failed to submit approval.");
      }
    } catch (err) {
      alert("Error: " + err);
    }
  };

  // Preview Modal
  document.getElementById("preview-close-btn").onclick = () => {
    document.getElementById("slide-preview-modal").classList.remove("active");
  };
}

function openFullscreenSlide(url, title) {
  document.getElementById("preview-modal-title").textContent = title;
  document.getElementById("preview-modal-body").innerHTML = `
    <img src="${url}" style="width:100%; height:100%; object-fit:contain;" alt="${title}">
  `;
  document.getElementById("slide-preview-modal").classList.add("active");
}

async function resumeJob(jobId) {
  try {
    const res = await fetch(`/api/jobs/${jobId}/resume`, { method: "POST" });
    if (res.ok) {
      startPolling(jobId);
    } else {
      alert("Failed to resume job.");
    }
  } catch (err) {
    alert("Error resuming job: " + err);
  }
}

// History
async function loadHistory() {
  const tbody = document.getElementById("history-tbody");
  try {
    const res = await fetch("/api/jobs?limit=30");
    if (!res.ok) return;
    const jobs = await res.json();
    if (jobs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--text-sub);">No presentation jobs yet.</td></tr>`;
      return;
    }

    tbody.innerHTML = jobs.map(j => `
      <tr>
        <td><strong>${escapeHtml(j.project_name)}</strong><br><span style="font-size:11px; color:var(--text-sub);">${j.job_id}</span></td>
        <td><span class="status-badge ${j.status}">${j.status}</span></td>
        <td>${j.current_slide} / ${j.total_slides}</td>
        <td>${new Date(j.created_at).toLocaleDateString()} ${new Date(j.created_at).toLocaleTimeString().slice(0,5)}</td>
        <td>
          <button class="btn-secondary" style="padding:4px 10px; font-size:12px;" onclick="viewPastJob('${j.job_id}')">View</button>
          ${j.download_url ? `<a href="${j.download_url}" class="btn-primary" style="padding:4px 10px; font-size:12px; text-decoration:none; margin-left:6px;">Download</a>` : ''}
          ${j.status === 'FAILED' ? `<button class="btn-secondary" style="padding:4px 10px; font-size:12px; margin-left:6px;" onclick="resumeJob('${j.job_id}')">Resume</button>` : ''}
        </td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" style="color:var(--danger);">Failed to load history: ${err}</td></tr>`;
  }
}

function viewPastJob(jobId) {
  activeJobId = jobId;
  document.getElementById("nav-active-job").style.display = "inline-block";
  switchTab("active-job");
  startPolling(jobId);
}

// System Settings
async function loadSystemSettings() {
  const container = document.getElementById("settings-content");
  try {
    const res = await fetch("/api/config");
    if (!res.ok) return;
    const data = await res.json();
    const cfg = data.config;

    container.innerHTML = `
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
        <div style="background:var(--bg-tertiary); padding:16px; border-radius:8px;">
          <h4 style="margin-bottom:10px; color:var(--accent-blue);">AI Provider</h4>
          <p><strong>Configured Provider:</strong> ${cfg.ai_provider}</p>
          <p><strong>Azure Deployment:</strong> ${cfg.azure_openai_deployment || 'N/A'}</p>
          <p><strong>Azure Endpoint:</strong> ${cfg.azure_openai_endpoint || 'N/A'}</p>
          <p><strong>OpenAI Model:</strong> ${cfg.openai_model || 'N/A'}</p>
          <p><strong>Provider Ready:</strong> ${data.provider_ready ? '<span style="color:var(--success);">✅ Verified</span>' : '<span style="color:var(--danger);">⚠️ Credentials Required (Fallback to Mock)</span>'}</p>
        </div>
        <div style="background:var(--bg-tertiary); padding:16px; border-radius:8px;">
          <h4 style="margin-bottom:10px; color:var(--accent-blue);">Engine Settings</h4>
          <p><strong>Max Retries per Slide:</strong> ${cfg.max_retries_per_slide}</p>
          <p><strong>Projects Root:</strong> <code>${cfg.projects_dir}</code></p>
          <p><strong>Host / Port:</strong> ${cfg.host}:${cfg.port}</p>
          <p><strong>Active Image Provider:</strong> ${cfg.image_provider}</p>
          <p><strong>⚡ Flux 2 Pro Status:</strong> ${cfg.flux_ready ? '<span style="color:var(--success);">✅ Ready (' + (cfg.flux_model || 'flux-2-pro') + ')</span>' : '<span style="color:var(--text-muted);">Optional (Set FLUX_API_KEY in .env)</span>'}</p>
          <p><strong>🍌 Nano Banana Status:</strong> ${cfg.nano_banana_ready ? '<span style="color:var(--success);">✅ Ready (' + (cfg.nano_banana_model || 'gemini-nano-banana-2.1') + ')</span>' : '<span style="color:var(--text-muted);">Optional (Set GEMINI_API_KEY in .env)</span>'}</p>
        </div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<p style="color:var(--danger);">Error loading configuration: ${err}</p>`;
  }
}

function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
