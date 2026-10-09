// Provide static sample evidence before the learner connects a real website.
const MOCK_PAGES = [
  ["Shipping policy", "Orders usually arrive quickly. Delivery timing depends on location and carrier availability."],
  ["Returns guide", "Customers can request a return within 30 days. Items must be unused and include the order number."],
  ["Security overview", "Account sessions use encrypted transport. The security team reviews access logs every weekday."],
  ["Pricing FAQ", "The standard plan costs $24 per month and includes five team members. Annual billing reduces the total by 15%."],
  ["Support policy", "Support is available by email. Priority customers receive a response within four business hours."],
  ["Product summary", "The platform helps teams publish useful pages. It offers flexible tools and modern workflows."],
  ["Data retention", "Deleted workspace data enters a 14-day recovery window. Backups expire after 35 days."],
  ["Accessibility", "Keyboard navigation covers the primary workflow. The latest internal review was completed in March 2026."],
  ["Integration guide", "Connect the service with an API token. Send JSON requests to your workspace endpoint."],
  ["Service status", "The service performed well last quarter. Reliability remained strong for most customers."],
  ["Onboarding", "Create a workspace and invite colleagues. Most teams finish the checklist in about 20 minutes."],
  ["Privacy FAQ", "Workspace owners control member access. Export requests are processed within seven days."]
].map(([title, content], index) => ({
  id: `mock-${index + 1}`,
  title,
  content,
  url: `https://example.com/mock/${index + 1}`
}));

// Cache every element that changes while discovery or an audit runs.
const ui = {
  appShell: document.querySelector("#appShell"),
  websiteUrl: document.querySelector("#websiteUrl"),
  discoverSite: document.querySelector("#discoverSite"),
  discoveryStatus: document.querySelector("#discoveryStatus"),
  modeButtons: [...document.querySelectorAll("[data-concurrency]")],
  prediction: document.querySelector("#prediction"),
  predictionResult: document.querySelector("#predictionResult"),
  runPilot: document.querySelector("#runPilot"),
  runFull: document.querySelector("#runFull"),
  stopRun: document.querySelector("#stopRun"),
  fullscreenBtn: document.querySelector("#fullscreenBtn"),
  runStatus: document.querySelector("#runStatus"),
  activeWorkers: document.querySelector("#activeWorkers"),
  progress: document.querySelector("#progress"),
  elapsed: document.querySelector("#elapsed"),
  liveSpeed: document.querySelector("#liveSpeed"),
  throughput: document.querySelector("#throughput"),
  latency: document.querySelector("#latency"),
  cost: document.querySelector("#cost"),
  successGauge: document.querySelector("#successGauge"),
  successRate: document.querySelector("#successRate"),
  runState: document.querySelector("#runState"),
  progressBar: document.querySelector("#progressBar"),
  activityPanel: document.querySelector("#activityPanel"),
  workerRail: document.querySelector("#workerRail"),
  feed: document.querySelector("#feed"),
  reviewQueue: document.querySelector("#reviewQueue"),
  editorTitle: document.querySelector("#editor-title"),
  editorUrl: document.querySelector("#editorUrl"),
  editorScore: document.querySelector("#editorScore"),
  pageContent: document.querySelector("#pageContent"),
  saveText: document.querySelector("#saveText"),
  rescore: document.querySelector("#rescore"),
  editorStatus: document.querySelector("#editorStatus"),
  exportCsv: document.querySelector("#exportCsv"),
  exportJson: document.querySelector("#exportJson"),
  fullRunDialog: document.querySelector("#fullRunDialog"),
  dialogCandidates: document.querySelector("#dialogCandidates"),
  dialogCost: document.querySelector("#dialogCost"),
  dialogBudget: document.querySelector("#dialogBudget"),
  dialogSpeed: document.querySelector("#dialogSpeed"),
  confirmFull: document.querySelector("#confirmFull"),
  completionDialog: document.querySelector("#completionDialog"),
  completionSummary: document.querySelector("#completionSummary")
};

// Hold discovered pages, evidence, and genuine in-flight work in browser memory.
let pages = [...MOCK_PAGES];
let site = null;
let concurrency = 1;
let results = [];
let events = [];
let selectedPageId = null;
let targetCount = 12;
let startedAt = 0;
let finishedElapsed = 0;
let running = false;
let stopping = false;
let discovering = false;
let mockMode = true;
let runMode = "mock";
let statusMessage = "Mock preview ready";
let stopReason = "Completed";
let sessionSpend = 0;
let animationFrame = null;
let stats = { attempted: 12, succeeded: 12, skipped: 0, failed: 0 };
const activePages = new Map();
const controllers = new Set();

function mockResult(page, index) {
  const weaknesses = ["answer_clarity", "evidence_specificity", "source_transparency", "extractable_structure"];
  const score = 38 + ((index * 13) % 51);
  return {
    pageId: page.id,
    title: page.title,
    url: page.url,
    content: page.content,
    outcome: "succeeded",
    score,
    readiness: Math.min(4, Math.max(0, Math.round(score / 25))),
    confidence: 0.62 + ((index % 4) * 0.07),
    weakest: weaknesses[index % weaknesses.length],
    weakestConfidence: 0.67 + ((index % 3) * 0.08),
    support: Math.min(0.95, score / 100),
    cost: 0,
    latencyMs: 120 + (index * 17),
    model: "mock-data",
    requestId: `mock-${index + 1}`,
    fetchedAt: null,
    httpStatus: 200,
    source: "mock"
  };
}

function formatMoney(value) {
  return `$${Number(value || 0).toFixed(6)}`;
}

function scoreClass(score) {
  if (score >= 75) return "good";
  if (score >= 50) return "warn";
  return "bad";
}

function speedLabel() {
  if (concurrency === 24) return "Turbo x24";
  if (concurrency === 8) return "Fast x8";
  return "Sequential";
}

function currentElapsed() {
  return running || discovering ? (performance.now() - startedAt) / 1000 : finishedElapsed;
}

function successfulAuditRate() {
  return stats.attempted > 0 ? stats.succeeded / stats.attempted : 0;
}

function setBusyState(kind) {
  discovering = kind === "discovering";
  const busy = kind === "discovering" || kind === "running";
  ui.appShell.setAttribute("aria-busy", String(busy));
  ui.activityPanel.classList.toggle("is-discovering", kind === "discovering");
  ui.activityPanel.classList.toggle("is-running", kind === "running");
  ui.discoverSite.disabled = busy;
  ui.websiteUrl.disabled = busy;
  ui.runPilot.disabled = busy || !site;
  ui.runFull.disabled = busy || !site;
  ui.stopRun.disabled = kind !== "running";
  ui.modeButtons.forEach((button) => {
    button.disabled = busy;
  });
  ui.discoverSite.textContent = kind === "discovering" ? "Discovering..." : "Discover pages";
}

function updateClock() {
  renderMetrics();
  if (running || discovering) animationFrame = requestAnimationFrame(updateClock);
}

function startClock() {
  if (animationFrame !== null) cancelAnimationFrame(animationFrame);
  startedAt = performance.now();
  animationFrame = requestAnimationFrame(updateClock);
}

function stopClock() {
  finishedElapsed = currentElapsed();
  if (animationFrame !== null) cancelAnimationFrame(animationFrame);
  animationFrame = null;
}

function createResultButton(event, queue = false) {
  const button = document.createElement("button");
  const outcome = event.outcome || "succeeded";
  button.className = `${queue ? "queue-row" : "result-row"} ${outcome}`;
  button.dataset.pageId = event.pageId;

  const details = document.createElement("span");
  const title = document.createElement("strong");
  const meta = document.createElement("small");
  const score = document.createElement("span");
  title.textContent = event.title || "Untitled page";
  meta.textContent = outcome === "succeeded"
    ? `${event.url} · ${event.weakest} · ${Math.round(event.latencyMs || 0)} ms`
    : `${event.url} · ${event.error || outcome}`;
  score.textContent = outcome === "succeeded" ? Number(event.score).toFixed(1) : outcome[0].toUpperCase() + outcome.slice(1);
  score.className = `score ${outcome === "succeeded" ? scoreClass(event.score) : outcome === "skipped" ? "warn" : "bad"}`;
  details.append(title, meta);
  button.append(details, score);
  return button;
}

function renderWorkers() {
  ui.workerRail.replaceChildren();
  if (discovering) {
    const card = document.createElement("article");
    const url = document.createElement("strong");
    const state = document.createElement("small");
    card.className = "worker-card discovery-card";
    url.textContent = ui.websiteUrl.value.trim();
    state.textContent = "Reading crawl rules and sitemap files";
    card.append(url, state);
    ui.workerRail.append(card);
    ui.activeWorkers.textContent = "Discovery request active";
    return;
  }
  if (!activePages.size) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = running ? "Waiting for the next eligible page." : "Worker cards appear here when real audit requests begin.";
    ui.workerRail.append(empty);
  } else {
    activePages.forEach((page) => {
      const card = document.createElement("article");
      const url = document.createElement("strong");
      const state = document.createElement("small");
      card.className = "worker-card";
      url.textContent = page.url;
      state.textContent = "Jev is analyzing this page";
      card.append(url, state);
      ui.workerRail.append(card);
    });
  }
  ui.activeWorkers.textContent = `${activePages.size} / ${concurrency} active`;
}

function renderMetrics() {
  const elapsed = currentElapsed();
  const successful = results.filter((result) => result.outcome === "succeeded");
  const averageLatency = successful.length
    ? successful.reduce((sum, result) => sum + Number(result.latencyMs || 0), 0) / successful.length
    : 0;
  const totalCost = successful.reduce((sum, result) => sum + Number(result.cost || 0), 0);
  const candidateSpeed = !mockMode && !discovering && elapsed > 0 ? stats.attempted / elapsed : 0;
  const successfulSpeed = !mockMode && !discovering && elapsed > 0 ? stats.succeeded / elapsed : 0;
  const rate = mockMode ? 100 : successfulAuditRate() * 100;
  const progressValue = !mockMode && !discovering && targetCount > 0 ? Math.min(100, stats.attempted / targetCount * 100) : 0;

  ui.progress.textContent = mockMode
    ? `${results.length} mock`
    : discovering
      ? "Mapping site"
      : `${stats.attempted}/${targetCount} · ${stats.succeeded} succeeded · ${stats.skipped} skipped · ${stats.failed} failed`;
  ui.elapsed.textContent = `${elapsed.toFixed(1)} s`;
  ui.liveSpeed.textContent = `${candidateSpeed.toFixed(2)} pages/s`;
  ui.throughput.textContent = `${successfulSpeed.toFixed(2)} successful/s`;
  ui.latency.textContent = `${Math.round(averageLatency)} ms`;
  ui.cost.textContent = formatMoney(totalCost);
  ui.successRate.textContent = `${Math.round(rate)}%`;
  ui.successGauge.style.strokeDasharray = `${rate} 100`;
  ui.runState.textContent = discovering ? "Discovering pages" : running ? `${speedLabel()} running` : mockMode ? "Mock data" : "Ready";
  ui.runStatus.textContent = discovering ? "Discovering permitted pages" : running ? stopping ? "Stopping active requests" : "Jev is analyzing" : statusMessage;
  if (!discovering) {
    ui.progressBar.style.width = `${progressValue}%`;
    ui.progressBar.setAttribute("aria-valuenow", String(Math.round(progressValue)));
  }
  renderWorkers();
}

function renderFeed() {
  ui.feed.replaceChildren(...[...events].reverse().slice(0, 80).map((event) => createResultButton(event)));
}

function renderQueue() {
  const ranked = results
    .filter((result) => result.outcome === "succeeded")
    .sort((a, b) => a.score - b.score)
    .slice(0, 30);
  ui.reviewQueue.replaceChildren(...ranked.map((result) => createResultButton(result, true)));
}

function renderPrediction() {
  const successful = results.filter((result) => result.outcome === "succeeded");
  if (mockMode || !successful.length) return;
  const counts = successful.reduce((totals, result) => {
    totals[result.weakest] = (totals[result.weakest] || 0) + 1;
    return totals;
  }, {});
  const mostCommon = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || "none";
  const matched = mostCommon === ui.prediction.value;
  ui.predictionResult.textContent = matched
    ? `Prediction matched: ${mostCommon} was most common.`
    : `Predicted ${ui.prediction.value}. Most common was ${mostCommon}.`;
  ui.predictionResult.className = `status ${matched ? "success" : ""}`;
}

function renderAll() {
  renderMetrics();
  renderFeed();
  renderQueue();
  renderPrediction();
}

function selectPage(pageId) {
  const page = pages.find((item) => item.id === pageId);
  const result = results.find((item) => item.pageId === pageId && item.outcome === "succeeded");
  if (!page || !result) return;
  selectedPageId = pageId;
  ui.editorTitle.textContent = result.title;
  ui.editorUrl.textContent = result.url;
  ui.editorScore.textContent = `${Number(result.score).toFixed(1)} / 100`;
  ui.pageContent.value = result.content || page.content || "";
  ui.editorStatus.textContent = "Changes here stay in this browser session.";
}

async function readJson(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body.error?.message || `Request failed with HTTP ${response.status}.`);
    error.status = response.status;
    error.details = body.error?.details || {};
    throw error;
  }
  return body;
}

async function discoverSite() {
  const websiteUrl = ui.websiteUrl.value.trim();
  if (!websiteUrl) {
    ui.discoveryStatus.textContent = "Enter a public website URL first.";
    ui.discoveryStatus.className = "status error";
    return;
  }
  setBusyState("discovering");
  finishedElapsed = 0;
  startClock();
  ui.progressBar.removeAttribute("aria-valuenow");
  ui.progressBar.setAttribute("aria-valuetext", "Website discovery in progress");
  ui.discoveryStatus.textContent = "Reading crawl rules and sitemap files.";
  try {
    const response = await fetch("/api/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ websiteUrl })
    });
    const body = await readJson(response);
    site = body;
    pages = body.pages.slice(0, 600);
    targetCount = pages.length;
    mockMode = false;
    statusMessage = `${pages.length} permitted pages ready`;
    ui.discoveryStatus.textContent = body.notice || `Discovered ${pages.length} permitted pages.`;
    ui.discoveryStatus.className = "status success";
  } catch (error) {
    site = null;
    statusMessage = "Discovery failed";
    ui.discoveryStatus.textContent = error.message;
    ui.discoveryStatus.className = "status error";
  } finally {
    stopClock();
    ui.progressBar.removeAttribute("aria-valuetext");
    ui.progressBar.setAttribute("aria-valuenow", "0");
    setBusyState("idle");
    renderAll();
  }
}

async function auditPage(page) {
  const controller = new AbortController();
  const requestKey = `${page.id}-${stats.attempted + activePages.size + 1}`;
  controllers.add(controller);
  activePages.set(requestKey, page);
  renderWorkers();
  let event;
  try {
    const response = await fetch("/api/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page }),
      signal: controller.signal
    });
    const body = await readJson(response);
    event = { ...body, pageId: page.id, title: body.title || page.title, url: body.url || page.url, outcome: "succeeded" };
    stats.succeeded += 1;
    sessionSpend += Number(event.cost || 0);
  } catch (error) {
    const skipped = error.status === 422 && error.details?.reason === "thin_content";
    event = {
      pageId: page.id,
      title: page.title,
      url: error.details?.url || page.url,
      content: "",
      outcome: skipped ? "skipped" : "failed",
      error: skipped ? "Thin content did not reach Jev" : error.name === "AbortError" ? "Request stopped" : error.message,
      httpStatus: error.status || null,
      extractedChars: error.details?.extractedChars ?? null,
      cost: 0,
      latencyMs: 0,
      source: "live_html"
    };
    if (skipped) stats.skipped += 1;
    else stats.failed += 1;
  } finally {
    stats.attempted += 1;
    activePages.delete(requestKey);
    controllers.delete(controller);
  }
  results.push(event);
  events.push(event);
  renderAll();
}

function shouldAutoStop() {
  return runMode === "full" && stats.attempted >= 20 && successfulAuditRate() < 0.5;
}

async function runAudit(mode) {
  if (!site || running) return;
  runMode = mode;
  running = true;
  stopping = false;
  mockMode = false;
  stopReason = "Completed";
  results = [];
  events = [];
  stats = { attempted: 0, succeeded: 0, skipped: 0, failed: 0 };
  targetCount = mode === "pilot" ? Math.min(25, pages.length) : pages.length;
  statusMessage = mode === "pilot" ? "Pilot running" : "Full Discovery running";
  finishedElapsed = 0;
  setBusyState("running");
  startClock();
  renderAll();

  let cursor = 0;
  while (cursor < pages.length && !stopping) {
    if (mode === "pilot" && (stats.succeeded >= 5 || stats.attempted >= 25)) break;
    let batchSize = Math.min(concurrency, pages.length - cursor);
    if (mode === "pilot") {
      batchSize = Math.min(batchSize, 25 - stats.attempted, 5 - stats.succeeded);
    } else if (stats.attempted < 20) {
      batchSize = Math.min(batchSize, 20 - stats.attempted);
    }
    if (batchSize <= 0) break;
    const batch = pages.slice(cursor, cursor + batchSize);
    cursor += batchSize;
    await Promise.all(batch.map((page) => auditPage(page)));

    // Evaluate the guard only after the active batch settles, then stop before scheduling more work.
    if (shouldAutoStop()) {
      stopping = true;
      stopReason = "Stopped automatically: successful audit rate below 50%";
      statusMessage = stopReason;
    }
  }

  stopClock();
  running = false;
  stopping = false;
  if (stopReason === "Completed") {
    statusMessage = mode === "pilot"
      ? stats.succeeded >= 5 ? "Five-page pilot complete" : "Pilot settled below five successes"
      : "Full Discovery complete";
  }
  setBusyState("idle");
  renderAll();
  showCompletion();
}

function stopActiveRun() {
  if (!running) return;
  stopping = true;
  stopReason = "Stopped manually";
  statusMessage = "Stopping active requests";
  controllers.forEach((controller) => controller.abort());
  renderMetrics();
}

function addSummaryValue(label, value) {
  const wrapper = document.createElement("div");
  const term = document.createElement("dt");
  const detail = document.createElement("dd");
  term.textContent = label;
  detail.textContent = value;
  wrapper.append(term, detail);
  ui.completionSummary.append(wrapper);
}

function showCompletion() {
  ui.completionSummary.replaceChildren();
  addSummaryValue("Result", stopReason);
  addSummaryValue("Attempted", String(stats.attempted));
  addSummaryValue("Succeeded", String(stats.succeeded));
  addSummaryValue("Skipped", String(stats.skipped));
  addSummaryValue("Failed", String(stats.failed));
  addSummaryValue("Successful audit rate", `${Math.round(successfulAuditRate() * 100)}%`);
  addSummaryValue("Elapsed", `${finishedElapsed.toFixed(1)} s`);
  addSummaryValue("Cost", formatMoney(results.reduce((sum, result) => sum + Number(result.cost || 0), 0)));
  addSummaryValue("Speed", speedLabel());
  ui.completionDialog.showModal();
}

async function rescoreDraft() {
  const page = pages.find((item) => item.id === selectedPageId);
  if (!page) return;
  ui.rescore.disabled = true;
  ui.editorStatus.textContent = "Jev is re-scoring the local draft.";
  try {
    const response = await fetch("/api/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page, draftContent: ui.pageContent.value })
    });
    const updated = await readJson(response);
    const index = results.findIndex((result) => result.pageId === selectedPageId && result.outcome === "succeeded");
    if (index >= 0) results[index] = { ...updated, outcome: "succeeded" };
    ui.editorScore.textContent = `${Number(updated.score).toFixed(1)} / 100`;
    ui.editorStatus.textContent = "The local draft has a new Jev score.";
    renderQueue();
  } catch (error) {
    ui.editorStatus.textContent = error.message;
  } finally {
    ui.rescore.disabled = false;
  }
}

function exportEvidence(format) {
  const data = results.map((result) => ({
    source_url: result.url,
    outcome: result.outcome,
    fetched_at: result.fetchedAt || "",
    http_status: result.httpStatus ?? "",
    methodology: result.source || "",
    model: result.model || "",
    request_id: result.requestId || "",
    latency_ms: result.latencyMs || 0,
    confidence: result.confidence ?? "",
    support: result.support ?? "",
    cost: result.cost || 0,
    score: result.score ?? "",
    weakest_signal: result.weakest || "",
    error: result.error || ""
  }));
  let content;
  let type;
  let extension;
  if (format === "json") {
    content = JSON.stringify(data, null, 2);
    type = "application/json";
    extension = "json";
  } else {
    const headers = Object.keys(data[0] || { source_url: "" });
    const escapeCell = (value) => `"${String(value).replaceAll('"', '""')}"`;
    content = [headers.join(","), ...data.map((row) => headers.map((key) => escapeCell(row[key])).join(","))].join("\n");
    type = "text/csv";
    extension = "csv";
  }
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([content], { type }));
  link.download = `jev-geo-audit.${extension}`;
  link.click();
  URL.revokeObjectURL(link.href);
}

ui.modeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    concurrency = Number(button.dataset.concurrency);
    ui.modeButtons.forEach((item) => {
      const active = item === button;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    renderMetrics();
  });
});

ui.discoverSite.addEventListener("click", discoverSite);
ui.runPilot.addEventListener("click", () => runAudit("pilot"));
ui.runFull.addEventListener("click", () => {
  ui.dialogCandidates.textContent = String(pages.length);
  ui.dialogCost.textContent = formatMoney(pages.length / 1000 * 0.01);
  ui.dialogBudget.textContent = formatMoney(Math.max(0, 6 - sessionSpend));
  ui.dialogSpeed.textContent = speedLabel();
  ui.fullRunDialog.showModal();
});
ui.confirmFull.addEventListener("click", () => {
  ui.fullRunDialog.close();
  runAudit("full");
});
ui.stopRun.addEventListener("click", stopActiveRun);
ui.feed.addEventListener("click", (event) => selectPage(event.target.closest("[data-page-id]")?.dataset.pageId));
ui.reviewQueue.addEventListener("click", (event) => selectPage(event.target.closest("[data-page-id]")?.dataset.pageId));
ui.saveText.addEventListener("click", () => {
  ui.editorStatus.textContent = "Local draft saved for this browser session.";
});
ui.rescore.addEventListener("click", rescoreDraft);
ui.exportCsv.addEventListener("click", () => exportEvidence("csv"));
ui.exportJson.addEventListener("click", () => exportEvidence("json"));
ui.fullscreenBtn.addEventListener("click", async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen();
    else throw new Error("Full screen is not supported in this browser.");
  } catch (error) {
    statusMessage = error.message;
    renderMetrics();
  }
});
document.addEventListener("fullscreenchange", () => {
  const active = Boolean(document.fullscreenElement);
  ui.fullscreenBtn.textContent = active ? "Exit full screen" : "Enter full screen";
  ui.fullscreenBtn.setAttribute("aria-pressed", String(active));
});

results = MOCK_PAGES.map(mockResult);
events = [...results];
renderAll();
