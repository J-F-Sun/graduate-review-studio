const state = {
  overview: null,
  selectedPaperId: null,
  selectedPaper: null,
  activeTab: "overview",
  settingsModalOpen: false,
  settingsTab: "appearance",
  settingsDraftTheme: "paper",
  selectedIssueId: null,
  activeMappingIssueId: null,
  ruleLibraryOpen: false,
  reviewRulesModalOpen: false,
  reviewDraft: {
    paperId: null,
    mode: "快速审稿",
    ruleIds: [],
    builtinRuleIds: [],
  },
  reviewRuleDraftIds: [],
  reviewBuiltinRuleDraftIds: [],
};

const THEME_STORAGE_KEY = "graduate-review-theme";
const AVAILABLE_THEMES = new Set(["paper", "mist", "blush", "sage"]);

const exportLabels = {
  include_basic_info: "基本信息",
  include_summary: "内容概括",
  include_dimension_scores: "分项评分",
  include_chapter_reviews: "逐章评价",
  include_issue_list: "重点问题",
  include_evidence: "原文证据",
  include_polish_suggestions: "润色建议",
  include_rule_hits: "规则命中",
  include_innovation: "创新点评价",
};

const toastEl = document.getElementById("toast");
const paperForm = document.getElementById("paper-form");
const ruleForm = document.getElementById("rule-form");
const settingsForm = document.getElementById("settings-form");
const paperListEl = document.getElementById("paper-list");
const ruleListEl = document.getElementById("rule-list");
const heroStatsEl = document.getElementById("hero-stats");
const detailEmptyEl = document.getElementById("detail-empty");
const paperDetailEl = document.getElementById("paper-detail");
const paperTitleEl = document.getElementById("paper-title");
const paperMetaLineEl = document.getElementById("paper-meta-line");
const tabOverviewEl = document.getElementById("tab-overview");
const tabParsedEl = document.getElementById("tab-parsed");
const tabReviewEl = document.getElementById("tab-review");
const tabMappingEl = document.getElementById("tab-mapping");
const refreshBtn = document.getElementById("refresh-btn");
const reviewBtn = document.getElementById("review-btn");
const reparseBtn = document.getElementById("reparse-btn");
const exportMarkdownBtn = document.getElementById("export-md-btn");
const exportPdfBtn = document.getElementById("export-pdf-btn");
const exportDocxBtn = document.getElementById("export-docx-btn");
const deleteBtn = document.getElementById("delete-btn");
const homeBtn = document.getElementById("home-btn");
const settingsBtn = document.getElementById("settings-btn");
const settingsModalEl = document.getElementById("settings-modal");
const settingsTabsEl = document.getElementById("settings-tabs");
const settingsSaveBtn = document.getElementById("settings-save-btn");
const settingsThemeOptionEls = Array.from(document.querySelectorAll("[data-settings-theme-option]"));
const fileDropzoneEls = Array.from(document.querySelectorAll("[data-dropzone]"));
const ruleModalEl = document.getElementById("rule-modal");
const ruleModalTitleEl = document.getElementById("rule-modal-title");
const ruleModalMetaEl = document.getElementById("rule-modal-meta");
const ruleModalBodyEl = document.getElementById("rule-modal-body");
const reviewRulesModalEl = document.getElementById("review-rules-modal");
const reviewRulesModalMetaEl = document.getElementById("review-rules-modal-meta");
const reviewRulesModalBodyEl = document.getElementById("review-rules-modal-body");
const reviewRulesClearBtn = document.getElementById("review-rules-clear-btn");
const reviewRulesSaveBtn = document.getElementById("review-rules-save-btn");

function settingsField(name) {
  return settingsForm.querySelector(`[name="${name}"]`);
}

function showToast(message, timeout = 2600) {
  toastEl.textContent = message;
  toastEl.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toastEl.classList.add("hidden"), timeout);
}

function escapeHtml(value = "") {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function truncateText(value = "", limit = 120) {
  if (value.length <= limit) return value;
  return `${value.slice(0, Math.max(0, limit - 1))}…`;
}

function formatRuleSource(value = "") {
  const mapping = {
    text: "文本录入",
    txt: "TXT 文件",
    md: "Markdown 文件",
    docx: "Word 文件",
    pdf: "PDF 文件",
  };
  return mapping[value] || value || "未知来源";
}

function enabledRules() {
  return (state.overview?.rules || []).filter((rule) => rule.enabled);
}

function builtinRules() {
  return state.overview?.builtin_rules || [];
}

function ensureReviewDraft(paperId) {
  const availableRuleIds = new Set(enabledRules().map((rule) => rule.id));
  const availableBuiltinRuleIds = new Set(builtinRules().map((rule) => rule.id));
  if (state.reviewDraft.paperId !== paperId) {
    const metadata = state.selectedPaper?.metadata || {};
    state.reviewDraft = {
      paperId,
      mode: metadata.review_mode || "快速审稿",
      ruleIds: enabledRules().map((rule) => rule.id),
      builtinRuleIds: builtinRules().map((rule) => rule.id),
    };
    return;
  }
  state.reviewDraft.ruleIds = state.reviewDraft.ruleIds.filter((ruleId) => availableRuleIds.has(ruleId));
  state.reviewDraft.builtinRuleIds = (state.reviewDraft.builtinRuleIds || []).filter((ruleId) =>
    availableBuiltinRuleIds.has(ruleId)
  );
}

function selectedReviewRules() {
  const selectedIds = new Set(state.reviewDraft.ruleIds || []);
  return enabledRules().filter((rule) => selectedIds.has(rule.id));
}

function selectedBuiltinRules() {
  const selectedIds = new Set(state.reviewDraft.builtinRuleIds || []);
  return builtinRules().filter((rule) => selectedIds.has(rule.id));
}

function currentTheme() {
  return window.localStorage.getItem(THEME_STORAGE_KEY) || document.body.dataset.theme || "paper";
}

function applyTheme(theme) {
  const nextTheme = AVAILABLE_THEMES.has(theme) ? theme : "paper";
  document.body.dataset.theme = nextTheme;
  window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
}

function initTheme() {
  const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY) || "paper";
  applyTheme(savedTheme);
}

function formatTime(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function updateDropzoneFilename(input) {
  const dropzone = input.closest("[data-dropzone]");
  const filenameEl = dropzone?.querySelector("[data-dropzone-filename]");
  if (!filenameEl) return;
  const file = input.files?.[0];
  filenameEl.textContent = file ? file.name : "未选择文件";
}

function bindDropzones() {
  fileDropzoneEls.forEach((dropzone) => {
    const input = dropzone.querySelector('input[type="file"]');
    if (!input) return;

    updateDropzoneFilename(input);

    ["dragenter", "dragover"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.add("drag-over");
      });
    });

    ["dragleave", "dragend"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        if (event.relatedTarget && dropzone.contains(event.relatedTarget)) return;
        dropzone.classList.remove("drag-over");
      });
    });

    dropzone.addEventListener("drop", (event) => {
      event.preventDefault();
      dropzone.classList.remove("drag-over");
      const files = event.dataTransfer?.files;
      if (!files?.length) return;
      input.files = files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });

    input.addEventListener("change", () => updateDropzoneFilename(input));
  });
}

function statusClass(status) {
  if (["failed"].includes(status)) return "failed";
  if (["done"].includes(status)) return "done";
  if (["terminated"].includes(status)) return "running";
  if (["running", "queued"].includes(status)) return "running";
  return "";
}

function combinedStatus(meta) {
  if (meta.review_status === "running") return "审稿中";
  if (meta.review_status === "done") return "已完成";
  if (meta.review_status === "failed") return "审稿失败";
  if (meta.review_status === "terminated") return "审稿已中断";
  if (meta.parse_status === "running") return "解析中";
  if (meta.parse_status === "done") return "已解析";
  if (meta.parse_status === "failed") return "解析失败";
  if (meta.parse_status === "terminated") return "解析已中断";
  return "待处理";
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "请求失败");
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response;
}

async function loadOverview(preserveSelection = true) {
  state.overview = await request("/api/overview");
  const paperIds = new Set((state.overview.papers || []).map((paper) => paper.id));
  if (!paperIds.has(state.selectedPaperId)) {
    state.selectedPaperId = null;
    state.selectedPaper = null;
  }
  renderSidebar();
  renderHero();
  renderPapers();

  if (state.selectedPaperId && preserveSelection) {
    await loadPaper(state.selectedPaperId);
  } else {
    state.selectedPaperId = null;
    state.selectedPaper = null;
    renderPaperDetail();
  }
}

async function loadPaper(paperId) {
  state.selectedPaperId = paperId;
  state.selectedIssueId = null;
  state.activeMappingIssueId = null;
  state.selectedPaper = await request(`/api/papers/${paperId}`);
  ensureReviewDraft(paperId);
  renderPapers();
  renderPaperDetail();
}

function renderHero() {
  const papers = state.overview?.papers || [];
  const done = papers.filter((paper) => paper.review_status === "done").length;
  const rules = state.overview?.rules?.length || 0;
  heroStatsEl.innerHTML = `
    <article class="hero-stat">
      <small>论文任务</small>
      <strong>${papers.length}</strong>
    </article>
    <article class="hero-stat">
      <small>已完成审稿</small>
      <strong>${done}</strong>
    </article>
    <article class="hero-stat">
      <small>可用规则</small>
      <strong>${rules}</strong>
    </article>
  `;
}

function renderSidebar() {
  renderRules();
  renderSettings();
}

function renderRules() {
  const rules = state.overview?.rules || [];
  if (!rules.length) {
    ruleListEl.innerHTML = `<p class="muted">还没有已保存规则。你可以先在上方创建一组规则。</p>`;
    return;
  }
  ruleListEl.innerHTML = `
    ${rules
      .map(
        (rule) => `
          <article class="rule-card modal-rule-card">
            <div class="rule-card-head">
              <div>
                <h3>${escapeHtml(rule.name)}</h3>
                <div class="rule-card-meta">
                  <span>${escapeHtml(formatRuleSource(rule.source_format))}</span>
                  <span>${(rule.items || []).length} 条规则</span>
                  <span>${formatTime(rule.updated_at)}</span>
                </div>
              </div>
              <span class="status-pill ${rule.enabled ? "done" : ""}">${rule.enabled ? "已启用" : "未启用"}</span>
            </div>
            ${(rule.items || []).length
              ? `
                <div class="rule-modal-list">
                  ${(rule.items || [])
                    .map(
                      (item, index) => `
                        <article class="rule-modal-item">
                          <strong>${index + 1}. ${escapeHtml(item.title || `规则 ${index + 1}`)}</strong>
                          <div class="muted">${escapeHtml(item.body || "")}</div>
                        </article>
                      `
                    )
                    .join("")}
                </div>
              `
              : `<p class="rule-preview">${escapeHtml(rule.content || "暂无规则内容。")}</p>`}
            <div class="rule-card-actions">
              <div class="rule-card-actions-left">
                <button type="button" class="ghost action-button danger-button" data-delete-rule="${rule.id}">删除规则</button>
              </div>
              <label class="status-row">
                <input type="checkbox" data-rule-toggle="${rule.id}" ${rule.enabled ? "checked" : ""} />
                <span>启用此规则</span>
              </label>
            </div>
          </article>
        `
      )
      .join("")}
  `;
}

function renderSettings() {
  const settings = state.overview?.settings;
  if (!settings) return;
  settingsField("base_url").value = settings.llm.base_url || "";
  settingsField("api_key").placeholder = settings.llm.api_key ? "已配置，留空则保持不变" : "请输入 API Key";
  settingsField("text_model").value = settings.llm.text_model || "";
  settingsField("vision_model").value = settings.llm.vision_model || "";
  settingsField("temperature").value = settings.llm.temperature ?? 0.2;
  settingsField("max_tokens").value = settings.llm.max_tokens ?? 4096;
  settingsField("vision_max_tokens").value = settings.llm.vision_max_tokens ?? 1024;
  settingsField("image_analysis_limit").value = settings.llm.image_analysis_limit ?? 8;
  document.getElementById("export-toggles").innerHTML = Object.entries(exportLabels)
    .map(
      ([key, label]) => `
        <label class="toggle-chip">
          <input type="checkbox" name="${key}" ${settings.export[key] ? "checked" : ""} />
          <span>${label}</span>
        </label>
      `
    )
    .join("");
  renderSettingsModal();
}

function renderSettingsModal() {
  document.querySelectorAll("[data-settings-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.settingsPanel === state.settingsTab);
  });
  document.querySelectorAll("[data-settings-tab]").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.settingsTab === state.settingsTab);
  });
  settingsThemeOptionEls.forEach((button) => {
    button.setAttribute("aria-pressed", button.dataset.settingsThemeOption === state.settingsDraftTheme ? "true" : "false");
  });
}

function openSettingsModal() {
  state.settingsModalOpen = true;
  state.settingsDraftTheme = currentTheme();
  renderSettings();
  settingsModalEl.classList.remove("hidden");
  settingsModalEl.setAttribute("aria-hidden", "false");
}

function closeSettingsModal() {
  state.settingsModalOpen = false;
  settingsModalEl.classList.add("hidden");
  settingsModalEl.setAttribute("aria-hidden", "true");
}

function renderPapers() {
  const papers = state.overview?.papers || [];
  if (!papers.length) {
    paperListEl.innerHTML = `<p class="muted">还没有论文任务。先上传一篇论文开始使用。</p>`;
    return;
  }
  paperListEl.innerHTML = papers
    .map((paper) => {
      const active = paper.id === state.selectedPaperId ? "active" : "";
      return `
        <article class="paper-card ${active}" data-paper-card="${paper.id}">
          <div class="panel-head">
            <div>
              <h3>${escapeHtml(paper.title)}</h3>
              <small>${escapeHtml(paper.degree_type)} · ${escapeHtml(paper.review_mode)}</small>
            </div>
            <span class="status-pill ${statusClass(
              paper.review_status === "done" ? "done" : paper.review_status === "failed" || paper.parse_status === "failed" ? "failed" : paper.review_status === "running" || paper.parse_status === "running" ? "running" : paper.parse_status
            )}">${combinedStatus(paper)}</span>
          </div>
          <p>${escapeHtml(paper.status_message || "")}</p>
          <div class="mini-meta">
            <small>${formatTime(paper.created_at)}</small>
            <small>${paper.page_count ? `${paper.page_count} 页` : paper.source_type?.toUpperCase() || ""}</small>
          </div>
          <div class="mini-meta">
            <button class="ghost" type="button" data-delete-paper="${paper.id}">删除</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderPaperDetail() {
  if (!state.selectedPaper) {
    detailEmptyEl.classList.remove("hidden");
    paperDetailEl.classList.add("hidden");
    return;
  }
  detailEmptyEl.classList.add("hidden");
  paperDetailEl.classList.remove("hidden");

  const { metadata } = state.selectedPaper;
  paperTitleEl.textContent = metadata.title;
  paperMetaLineEl.textContent = `${metadata.degree_type} · ${metadata.review_mode} · ${combinedStatus(metadata)}`;
  const canExport = metadata.review_status === "done";
  exportMarkdownBtn.disabled = !canExport;
  exportPdfBtn.disabled = !canExport;
  exportDocxBtn.disabled = !canExport;

  renderTabs();
}

function renderTabs() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === state.activeTab);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.remove("active");
  });
  document.getElementById(`tab-${state.activeTab}`).classList.add("active");

  renderOverviewTab();
  renderParsedTab();
  renderReviewTab();
  renderMappingTab();
}

function renderOverviewTab() {
  const { metadata, parsed, review } = state.selectedPaper;
  ensureReviewDraft(metadata.id);
  const selectedRules = selectedReviewRules();
  const selectedBuiltin = selectedBuiltinRules();
  const sourceLink = metadata.source_relative_path ? `/files/${metadata.source_relative_path}` : "#";
  tabOverviewEl.innerHTML = `
    <div class="overview-grid">
      <article class="overview-wide">
        <h3>当前报告摘要</h3>
        ${review.generation_mode === "failed" ? `<p><strong>审稿失败：</strong>${escapeHtml(review.error_message || "模型调用失败。")}</p>` : ""}
        <p>${escapeHtml(review.summary || "还没有生成审稿报告。解析完成后，点击“开始审稿”即可生成。")}</p>
      </article>
      <article>
        <h3>任务信息</h3>
        <p>上传时间：${formatTime(metadata.created_at)}</p>
        <p>原文件：<a href="${sourceLink}" target="_blank" rel="noreferrer">查看原文件</a></p>
        <p>解析状态：${escapeHtml(metadata.parse_status)}</p>
        <p>审稿状态：${escapeHtml(metadata.review_status)}</p>
        <p>错误信息：${escapeHtml(metadata.last_error || "无")}</p>
        <p>警告信息：${escapeHtml(metadata.last_warning || "无")}</p>
      </article>
      <article>
        <h3>解析概况</h3>
        <p>章节数：${parsed.stats?.section_count ?? 0}</p>
        <p>段落数：${parsed.stats?.paragraph_count ?? 0}</p>
        <p>表格数：${parsed.stats?.table_count ?? 0}</p>
        <p>图片数：${parsed.stats?.image_count ?? 0}</p>
      </article>
      <article>
        <h3>评分概览</h3>
        <div class="score-summary">
          <div class="score-summary-total">
            <small>总评分</small>
            <strong>${review.total_score ?? "-"}</strong>
            <span class="score-result ${review.pass ? "pass" : "fail"}">${review.pass ? "合格" : "不合格"}</span>
          </div>
          <div class="score-summary-list">
            ${(review.dimension_scores || []).length
              ? review.dimension_scores
                  .map(
                    (item) => `
                      <div class="score-summary-item">
                        <span>${escapeHtml(item.name)}</span>
                        <strong>${item.score}</strong>
                      </div>
                    `
                  )
                  .join("")
              : `<p class="muted">当前还没有可展示的评分结果。</p>`}
          </div>
        </div>
      </article>
      <article>
        <h3>审稿设置</h3>
        <label>
          <span class="field-title with-help">
            <span>本次审稿模式</span>
            <details class="mode-help">
              <summary aria-label="查看审稿模式说明">?</summary>
              <div class="mode-help-card">
                <article>
                  <strong>快速审稿</strong>
                  <p>更适合先看总体质量和主要风险，优先指出关键结构问题、明显逻辑缺口和高优先级修改项，生成速度更快。</p>
                </article>
                <article>
                  <strong>深度审稿</strong>
                  <p>会尽量下钻到章节、段落、句子和图表位置，给出更细的定位、证据和润色建议，适合正式返修前使用。</p>
                </article>
              </div>
            </details>
          </span>
          <select id="detail-review-mode">
            <option value="快速审稿" ${state.reviewDraft.mode === "快速审稿" ? "selected" : ""}>快速审稿</option>
            <option value="深度审稿" ${state.reviewDraft.mode === "深度审稿" ? "selected" : ""}>深度审稿</option>
          </select>
        </label>
        <div class="review-rule-panel">
          <div class="panel-head review-rule-head">
            <div>
              <strong>本次使用规则</strong>
              <p class="muted">系统规则和自定义规则都支持人工勾选；未勾选的规则不会参与本次审稿。</p>
            </div>
            <button type="button" class="ghost" data-open-review-rules>选择规则</button>
          </div>
          <div class="rule-section-block">
            <div class="rule-section-title">系统默认规则</div>
            <div class="builtin-rule-list">
              ${selectedBuiltin.length
                ? selectedBuiltin
                    .map(
                      (rule) => `
                        <article class="builtin-rule-card">
                          <strong>${escapeHtml(rule.title)}</strong>
                          <p>${escapeHtml(rule.body)}</p>
                        </article>
                      `
                    )
                    .join("")
                : `<p class="muted">当前未选择系统默认规则。</p>`}
            </div>
          </div>
          <div class="rule-section-block">
            <div class="rule-section-title">本次使用的自定义规则</div>
          <div class="selected-rule-list">
            ${selectedRules.length
              ? selectedRules
                  .map((rule) => `<span class="selected-rule-chip">${escapeHtml(rule.name)}</span>`)
                  .join("")
              : `<p class="muted">当前未选择自定义规则。</p>`}
          </div>
          </div>
        </div>
      </article>
    </div>
  `;
  if (state.reviewRulesModalOpen) {
    openReviewRulesModal({ preserveScroll: true });
  }
}

function renderParsedTab() {
  const parsed = state.selectedPaper.parsed || {};
  const sections = parsed.sections || [];
  const paragraphs = parsed.paragraphs || [];
  const tables = parsed.tables || [];
  const images = parsed.images || [];
  const sectionMap = new Map(sections.map((section) => [section.id, section]));
  const paragraphMap = new Map(paragraphs.map((paragraph) => [paragraph.id, paragraph]));
  const tableMap = new Map(tables.map((table) => [table.id, table]));
  const imageMap = new Map(images.map((image) => [image.id, image]));
  const rootSections = sections.filter((section) => !section.parent_id);

  function renderTreeTableRows(rows = []) {
    if (!rows.length) {
      return `<p class="muted">表格未提取到有效行内容。</p>`;
    }
    return `
      <div class="tree-table-wrap">
        <table class="tree-table">
          <tbody>
            ${rows
              .map(
                (row) => `
                  <tr>
                    ${row.map((cell) => `<td>${escapeHtml(cell || "")}</td>`).join("")}
                  </tr>
                `
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderTreeContent(contentId) {
    if (paragraphMap.has(contentId)) {
      const paragraph = paragraphMap.get(contentId);
      return `
        <div class="tree-item tree-item-paragraph">
          <div class="tree-branch"></div>
          <article class="tree-card">
            <div class="tree-meta-row">
              <span class="tree-kind">${paragraph.role === "caption" ? "图表标题" : "正文段落"}</span>
              <span class="tree-location">${escapeHtml(paragraph.location_label)}</span>
            </div>
            <p class="tree-fulltext">${escapeHtml(paragraph.text)}</p>
          </article>
        </div>
      `;
    }

    if (tableMap.has(contentId)) {
      const table = tableMap.get(contentId);
      return `
        <div class="tree-item tree-item-table">
          <div class="tree-branch"></div>
          <article class="tree-card">
            <div class="tree-meta-row">
              <span class="tree-kind">表格</span>
              <span class="tree-location">${escapeHtml(table.location_label)}</span>
            </div>
            <strong>${escapeHtml(table.caption || "未命名表格")}</strong>
            ${renderTreeTableRows(table.rows || [])}
          </article>
        </div>
      `;
    }

    if (imageMap.has(contentId)) {
      const image = imageMap.get(contentId);
      return `
        <div class="tree-item tree-item-image">
          <div class="tree-branch"></div>
          <article class="tree-card">
            <div class="tree-meta-row">
              <span class="tree-kind">图片</span>
              <span class="tree-location">${escapeHtml(image.location_label)}</span>
            </div>
            <strong>${escapeHtml(image.caption || image.id)}</strong>
            <div class="tree-image-wrap">
              <img src="/files/${image.asset_relative_path}" alt="${escapeHtml(image.caption || image.id)}" />
            </div>
            <p><strong>图片内容理解：</strong>${escapeHtml(image.content_summary || "当前还没有图片内容总结。")}</p>
            ${image.nearby_text ? `<p><strong>邻近原文：</strong>${escapeHtml(image.nearby_text)}</p>` : ""}
          </article>
        </div>
      `;
    }

    return "";
  }

  function renderSectionNode(section) {
    const childSections = (section.child_ids || [])
      .map((childId) => sectionMap.get(childId))
      .filter(Boolean);
    const directContents = (section.content_ids || []).map((contentId) => renderTreeContent(contentId)).join("");
    const childMarkup = childSections.map((childSection) => renderSectionNode(childSection)).join("");
    return `
      <div class="tree-section-node">
        <div class="tree-item tree-item-section">
          <div class="tree-branch"></div>
          <article class="tree-card tree-card-section">
            <div class="tree-meta-row">
              <span class="tree-kind">章节</span>
              <span class="tree-location">${section.page_start ? `第 ${section.page_start}${section.page_end && section.page_end !== section.page_start ? `-${section.page_end}` : ""} 页` : "Word 文档结构"}</span>
            </div>
            <strong>${escapeHtml(section.title)}</strong>
            <p class="muted">层级 ${section.level}${section.number ? ` · 编号 ${escapeHtml(section.number)}` : ""}</p>
          </article>
        </div>
        <div class="tree-children">
          ${directContents || ""}
          ${childMarkup || ""}
        </div>
      </div>
    `;
  }

  tabParsedEl.innerHTML = `
    <div class="parsed-grid">
      <section class="block-cluster">
        <article class="block-card">
          <h4>解析说明</h4>
          <p>${escapeHtml((parsed.parser_notes || []).join(" ")) || "暂无解析说明。"}</p>
        </article>
        <article class="block-card">
          <h4>结构树与原文</h4>
          <p class="muted">这里会尽量按章节层级、正文段落、表格和图片的原始顺序展示完整解析结果，方便直接核对结构是否切对。</p>
          <div class="tree-view">
            ${rootSections.length ? rootSections.map((section) => renderSectionNode(section)).join("") : `<p class="muted">解析完成后会在这里显示完整结构树。</p>`}
          </div>
        </article>
      </section>
    </div>
  `;
}

function renderReviewTab() {
  const review = state.selectedPaper.review || {};
  const metadata = state.selectedPaper.metadata || {};
  if (!review || !Object.keys(review).length) {
    tabReviewEl.innerHTML = `<div class="empty-state"><div><h3>还没有审稿报告</h3><p>解析完成后，点击上方“开始审稿”即可生成报告。当前版本必须使用已配置的 LLM 接口，若配置缺失或调用失败，会直接给出错误信息。</p></div></div>`;
    return;
  }
  if (review.generation_mode === "terminated") {
    tabReviewEl.innerHTML = `
      <div class="parsed-grid">
        <article class="block-card warning-card">
          <h4>上次审稿已中断</h4>
          <p>应用在审稿过程中被关闭或重启，这次任务没有继续执行，也没有生成有效报告。</p>
          <p><strong>说明：</strong>${escapeHtml(review.error_message || metadata.last_warning || "任务已中断。")}</p>
          <p>请点击上方“开始审稿”，从当前论文重新发起一次模型审稿。</p>
        </article>
      </div>
    `;
    return;
  }
  if (review.generation_mode === "failed") {
    tabReviewEl.innerHTML = `
      <div class="parsed-grid">
        <article class="block-card warning-card">
          <h4>模型审稿失败</h4>
          <p>本次审稿没有回退到本地模式，因此当前没有生成有效报告。</p>
          <p><strong>失败原因：</strong>${escapeHtml(review.error_message || metadata.last_error || "未知错误")}</p>
          <p>建议先检查 API Key、模型名、最大输出长度以及网络连通性，再重新发起审稿。</p>
        </article>
      </div>
    `;
    return;
  }
  tabReviewEl.innerHTML = `
    <div class="parsed-grid">
      ${(review.generation_mode && review.generation_mode !== "model") ? `
        <article class="block-card warning-card">
          <h4>旧版报告提示</h4>
          <p>这份报告不是当前模型审稿流程生成的结果，建议重新发起一次审稿。</p>
        </article>
      ` : ""}
      <article class="block-card">
        <h4>总评</h4>
        <p>${escapeHtml(review.general_assessment || "")}</p>
        <p><strong>摘要：</strong>${escapeHtml(review.summary || "")}</p>
        <small>生成时间：${formatTime(review.generated_at)} · 来源：${escapeHtml(review.provider || "-")}</small>
      </article>
      <section class="score-grid">
        <article class="score-card">
          <small>总分</small>
          <strong>${review.total_score ?? "-"}</strong>
          <span>${review.pass ? "达到及格线" : "低于 6 分，不合格"}</span>
        </article>
        ${(review.dimension_scores || []).map((item) => `
          <article class="score-card">
            <small>${escapeHtml(item.name)}</small>
            <strong>${item.score}</strong>
          </article>
        `).join("")}
      </section>
      <section class="chapter-list">
        ${(review.chapter_reviews || []).length ? review.chapter_reviews.map((chapter) => `
          <article class="chapter-card">
            <h3>${escapeHtml(chapter.title)}</h3>
            <p>${escapeHtml(chapter.assessment || "")}</p>
          </article>
        `).join("") : ""}
      </section>
      <section class="issue-list">
        ${(review.issues || []).length ? review.issues.map((issue) => `
          <article class="issue-card ${state.selectedIssueId === issue.id ? "active" : ""}" data-issue-card="${issue.id}">
            <div class="panel-head">
              <div>
                <h3>${escapeHtml(issue.title)}</h3>
                <small>${escapeHtml(issue.location_label || "")}</small>
              </div>
              <span class="status-pill ${issue.severity === "严重" ? "failed" : issue.severity === "重要" ? "running" : "done"}">${escapeHtml(issue.severity || "一般")}</span>
            </div>
            <p><strong>问题类型：</strong>${escapeHtml(issue.type || "")}</p>
            ${issue.evidence ? `<p><strong>原文：</strong>${escapeHtml(issue.evidence)}</p>` : ""}
            <p><strong>问题说明：</strong>${escapeHtml(issue.analysis || "")}</p>
            <p><strong>修改建议：</strong>${escapeHtml(issue.suggestion || "")}</p>
            ${issue.polish_suggestion ? `<p><strong>润色建议：</strong>${escapeHtml(issue.polish_suggestion)}</p>` : ""}
          </article>
        `).join("") : `<p class="muted">当前报告没有返回问题清单。</p>`}
      </section>
      ${review.innovation ? `
        <article class="block-card">
          <h4>硕士论文创新点评价</h4>
          <p>${escapeHtml((review.innovation.points || []).join("；"))}</p>
          <p>${escapeHtml(review.innovation.assessment || "")}</p>
        </article>
      ` : ""}
    </div>
  `;
}

function issueTargets(issue) {
  return issue?.target_ids || { paragraph_ids: [], section_ids: [], table_ids: [], image_ids: [] };
}

function normalizeTargetIds(value) {
  return Array.isArray(value) ? value.filter(Boolean) : [];
}

function severityWeight(severity) {
  return severity === "严重" ? 0 : severity === "重要" ? 1 : 2;
}

function severityStatusClass(severity) {
  return severity === "严重" ? "failed" : severity === "重要" ? "running" : "done";
}

function buildMappingViewModel(parsed, review) {
  const sections = parsed.sections || [];
  const paragraphs = parsed.paragraphs || [];
  const issues = review.issues || [];
  const sectionMap = new Map(sections.map((section) => [section.id, section]));
  const paragraphMap = new Map(paragraphs.map((paragraph) => [paragraph.id, paragraph]));
  const paragraphsBySection = new Map();
  sections.forEach((section) => paragraphsBySection.set(section.id, []));
  paragraphs.forEach((paragraph) => {
    if (!paragraphsBySection.has(paragraph.section_id)) {
      paragraphsBySection.set(paragraph.section_id, []);
    }
    paragraphsBySection.get(paragraph.section_id).push(paragraph);
  });

  const primaryIssuesByParagraph = new Map();
  const secondaryIssuesByParagraph = new Map();
  const sectionIssues = new Map();
  const issueInfos = [];
  const issuesByNavSection = new Map();
  const unboundIssues = [];

  function pushIssue(targetMap, key, issue) {
    if (!key) return;
    if (!targetMap.has(key)) {
      targetMap.set(key, []);
    }
    targetMap.get(key).push(issue);
  }

  issues.forEach((issue) => {
    const targets = issueTargets(issue);
    const paragraphIds = normalizeTargetIds(targets.paragraph_ids);
    const sectionIds = normalizeTargetIds(targets.section_ids);
    const primaryParagraphId = paragraphIds[0] || null;
    const inferredSectionId = primaryParagraphId
      ? paragraphMap.get(primaryParagraphId)?.section_id || sectionIds[0] || null
      : sectionIds[0] || null;
    const primaryAnchorId = primaryParagraphId
      ? `paragraph:${primaryParagraphId}`
      : inferredSectionId
        ? `section:${inferredSectionId}`
        : null;
    const allAnchorIds = paragraphIds.length
      ? paragraphIds.map((paragraphId) => `paragraph:${paragraphId}`)
      : sectionIds.map((sectionId) => `section:${sectionId}`);

    const issueInfo = {
      ...issue,
      paragraphIds,
      sectionIds,
      primaryParagraphId,
      secondaryParagraphIds: paragraphIds.slice(1),
      primarySectionId: inferredSectionId,
      primaryAnchorId,
      allAnchorIds,
      navSectionId: inferredSectionId || "__unbound__",
    };

    issueInfos.push(issueInfo);

    if (primaryParagraphId) {
      pushIssue(primaryIssuesByParagraph, primaryParagraphId, issueInfo);
      issueInfo.secondaryParagraphIds.forEach((paragraphId) => {
        pushIssue(secondaryIssuesByParagraph, paragraphId, issueInfo);
      });
    } else if (inferredSectionId) {
      pushIssue(sectionIssues, inferredSectionId, issueInfo);
    } else {
      unboundIssues.push(issueInfo);
    }

    if (issueInfo.navSectionId !== "__unbound__") {
      pushIssue(issuesByNavSection, issueInfo.navSectionId, issueInfo);
    }
  });

  const sortIssues = (list) =>
    [...list].sort((left, right) => {
      const severityDiff = severityWeight(left.severity || "一般") - severityWeight(right.severity || "一般");
      if (severityDiff !== 0) return severityDiff;
      const locationDiff = (left.location_label || "").localeCompare(right.location_label || "", "zh-CN");
      if (locationDiff !== 0) return locationDiff;
      return (left.title || "").localeCompare(right.title || "", "zh-CN");
    });

  const navigationGroups = sections
    .map((section) => ({
      section,
      issues: sortIssues(issuesByNavSection.get(section.id) || []),
    }))
    .filter((group) => group.issues.length);

  if (unboundIssues.length) {
    navigationGroups.push({
      section: { id: "__unbound__", title: "未定位问题", level: 1, page_start: null, page_end: null },
      issues: sortIssues(unboundIssues),
    });
  }

  return {
    sections,
    sectionMap,
    paragraphMap,
    paragraphsBySection,
    issueInfos,
    issueInfoMap: new Map(issueInfos.map((issue) => [issue.id, issue])),
    primaryIssuesByParagraph,
    secondaryIssuesByParagraph,
    sectionIssues,
    navigationGroups,
  };
}

function currentActiveMappingState(viewModel) {
  const activeIssue = viewModel.issueInfoMap.get(state.activeMappingIssueId) || null;
  return {
    activeIssue,
    primaryAnchorId: activeIssue?.primaryAnchorId || null,
    allAnchorIds: new Set(activeIssue?.allAnchorIds || []),
  };
}

function renderMappingIssueCard(issue, variant = "inline") {
  const isActive = state.activeMappingIssueId === issue.id;
  const dataAttr = variant === "nav" ? "data-mapping-nav-issue" : "data-inline-issue";
  const extraClass = variant === "nav" ? "mapping-nav-card" : "mapping-inline-card";
  return `
    <article class="issue-card ${extraClass} ${isActive ? "active" : ""}" ${dataAttr}="${issue.id}">
      <div class="panel-head">
        <div>
          <h3>${escapeHtml(issue.title)}</h3>
          <small>${escapeHtml(issue.location_label || "")}</small>
        </div>
        <span class="status-pill ${severityStatusClass(issue.severity || "一般")}">${escapeHtml(issue.severity || "一般")}</span>
      </div>
      ${variant === "nav"
        ? `
          <p class="mapping-card-summary">${escapeHtml(truncateText(issue.analysis || issue.suggestion || "", 88))}</p>
        `
        : `
          ${issue.evidence ? `<p><strong>原文：</strong>${escapeHtml(issue.evidence)}</p>` : ""}
          <p><strong>问题说明：</strong>${escapeHtml(issue.analysis || "")}</p>
          <p><strong>修改建议：</strong>${escapeHtml(issue.suggestion || "")}</p>
          ${issue.polish_suggestion ? `<p><strong>润色建议：</strong>${escapeHtml(issue.polish_suggestion)}</p>` : ""}
        `}
    </article>
  `;
}

function renderSecondaryIssueMarker(issue) {
  const isActive = state.activeMappingIssueId === issue.id;
  return `
    <button type="button" class="mapping-related-marker ${isActive ? "active" : ""}" data-related-issue="${issue.id}">
      <span class="mapping-related-label">关联意见</span>
      <span>${escapeHtml(issue.title)}</span>
    </button>
  `;
}

function scrollToMappingIssue(issueId) {
  const review = state.selectedPaper?.review || {};
  const parsed = state.selectedPaper?.parsed || {};
  const viewModel = buildMappingViewModel(parsed, review);
  const issue = viewModel.issueInfoMap.get(issueId);
  const anchorId = issue?.primaryAnchorId;
  if (!anchorId) return;
  queueMicrotask(() => {
    const node = document.querySelector(`[data-anchor-id="${anchorId}"]`);
    node?.scrollIntoView({ block: "center", behavior: "smooth" });
  });
}

function toggleMappingIssue(issueId) {
  state.activeMappingIssueId = state.activeMappingIssueId === issueId ? null : issueId;
  renderMappingTab();
  if (state.activeMappingIssueId) {
    scrollToMappingIssue(state.activeMappingIssueId);
  }
}

function renderMappingTab() {
  const parsed = state.selectedPaper.parsed || {};
  const review = state.selectedPaper.review || {};
  const viewModel = buildMappingViewModel(parsed, review);
  const { sections, paragraphsBySection, primaryIssuesByParagraph, secondaryIssuesByParagraph, sectionIssues, navigationGroups } = viewModel;
  const activeState = currentActiveMappingState(viewModel);

  function anchorClasses(anchorId) {
    if (!activeState.primaryAnchorId || !activeState.allAnchorIds.has(anchorId)) {
      return "";
    }
    return activeState.primaryAnchorId === anchorId ? "is-primary-active" : "is-secondary-active";
  }

  function renderParagraphRow(paragraph) {
    const primaryIssues = primaryIssuesByParagraph.get(paragraph.id) || [];
    const secondaryIssues = secondaryIssuesByParagraph.get(paragraph.id) || [];
    const hasInlineComments = primaryIssues.length > 0;
    return `
      <div class="mapping-paragraph-row ${hasInlineComments ? "has-comments" : "no-comments"}">
        <article class="mapping-anchor-card mapping-paragraph-card ${anchorClasses(`paragraph:${paragraph.id}`)}" data-anchor-id="paragraph:${paragraph.id}">
          <div class="mapping-paragraph-meta">
            <div>
              <strong>${escapeHtml(paragraph.location_label)}</strong>
              <span class="mapping-role-chip">${paragraph.role === "caption" ? "图表标题" : "正文段落"}</span>
            </div>
            ${(primaryIssues.length || secondaryIssues.length) ? `<span class="mapping-count-chip">${primaryIssues.length + secondaryIssues.length} 条关联意见</span>` : ""}
          </div>
          <p class="mapping-paragraph-text">${escapeHtml(paragraph.text)}</p>
          ${secondaryIssues.length ? `
            <div class="mapping-related-list">
              ${secondaryIssues.map((issue) => renderSecondaryIssueMarker(issue)).join("")}
            </div>
          ` : ""}
        </article>
        ${hasInlineComments ? `
          <aside class="mapping-inline-comments">
            ${primaryIssues.map((issue) => renderMappingIssueCard(issue, "inline")).join("")}
          </aside>
        ` : `<div class="mapping-inline-comments empty"></div>`}
      </div>
    `;
  }

  function renderSectionBlock(section) {
    const sectionLevel = Math.max((section.level || 1) - 1, 0);
    const directParagraphs = paragraphsBySection.get(section.id) || [];
    const sectionBoundIssues = sectionIssues.get(section.id) || [];
    return `
      <section class="mapping-section" style="--section-level:${sectionLevel}">
        <div class="mapping-section-row ${sectionBoundIssues.length ? "has-comments" : "no-comments"}">
          <article class="mapping-anchor-card mapping-section-card ${anchorClasses(`section:${section.id}`)}" data-anchor-id="section:${section.id}">
            <div class="mapping-section-meta">
              <div>
                <strong>${escapeHtml(section.title)}</strong>
                <small>${section.page_start ? `第 ${section.page_start}${section.page_end && section.page_end !== section.page_start ? `-${section.page_end}` : ""} 页` : "Word 文档结构"}</small>
              </div>
              <span class="mapping-section-level">层级 ${section.level || 1}</span>
            </div>
          </article>
          ${sectionBoundIssues.length ? `
            <aside class="mapping-inline-comments">
              ${sectionBoundIssues.map((issue) => renderMappingIssueCard(issue, "inline")).join("")}
            </aside>
          ` : `<div class="mapping-inline-comments empty"></div>`}
        </div>
        <div class="mapping-section-body">
          ${directParagraphs.map((paragraph) => renderParagraphRow(paragraph)).join("") || `<p class="muted">该章节当前没有可展示的正文段落。</p>`}
        </div>
      </section>
    `;
  }

  tabMappingEl.innerHTML = `
    <div class="mapping-layout">
      <div class="mapping-main">
        <p class="mapping-tip">正文按章节和段落顺序展开，问题会尽量像批注一样贴在对应位置旁边。点击任一意见只会高亮对应位置，不会隐藏其他意见。</p>
        <div class="mapping-flow">
          ${sections.length ? sections.map((section) => renderSectionBlock(section)).join("") : `<p class="muted">解析完成后会在这里显示正文与批注对应关系。</p>`}
        </div>
      </div>
      <aside class="mapping-nav">
        <p class="mapping-tip">这里保留全部意见导航。点击一条意见，会定位并高亮对应段落；再次点击则取消高亮。</p>
        <div class="mapping-nav-groups">
          ${navigationGroups.length ? navigationGroups.map((group) => `
            <section class="mapping-nav-group">
              <div class="mapping-nav-group-head">
                <strong>${escapeHtml(group.section.title)}</strong>
                <span>${group.issues.length} 条</span>
              </div>
              <div class="mapping-nav-group-body">
                ${group.issues.map((issue) => renderMappingIssueCard(issue, "nav")).join("")}
              </div>
            </section>
          `).join("") : `<p class="muted">当前还没有可导航的审稿问题。</p>`}
        </div>
      </aside>
    </div>
  `;
}

async function handlePaperSubmit(event) {
  event.preventDefault();
  const formData = new FormData(paperForm);
  const created = await request("/api/papers", {
    method: "POST",
    body: formData,
  });
  state.selectedPaperId = created.id;
  paperForm.reset();
  paperForm.querySelectorAll('input[type="file"]').forEach((input) => updateDropzoneFilename(input));
  showToast("论文已上传。");
  await loadOverview();
}

async function handleRuleSubmit(event) {
  event.preventDefault();
  const formData = new FormData(ruleForm);
  await request("/api/rules", {
    method: "POST",
    body: formData,
  });
  ruleForm.reset();
  ruleForm.querySelectorAll('input[type="file"]').forEach((input) => updateDropzoneFilename(input));
  showToast("规则集已保存。");
  await loadOverview();
  if (state.settingsModalOpen) {
    state.settingsTab = "rules";
    openSettingsModal();
  }
}

async function handleSettingsSubmit() {
  const payload = {
    llm: {
      base_url: settingsField("base_url").value.trim(),
      api_key: settingsField("api_key").value.trim(),
      text_model: settingsField("text_model").value.trim(),
      vision_model: settingsField("vision_model").value.trim(),
      temperature: Number(settingsField("temperature").value || 0.2),
      max_tokens: Number(settingsField("max_tokens").value || 4096),
      vision_max_tokens: Number(settingsField("vision_max_tokens").value || 1024),
      image_analysis_limit: Number(settingsField("image_analysis_limit").value || 8),
    },
    export: {},
  };
  Object.keys(exportLabels).forEach((key) => {
    payload.export[key] = settingsForm.querySelector(`[name="${key}"]`)?.checked || false;
  });
  await request("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  applyTheme(state.settingsDraftTheme);
  settingsField("api_key").value = "";
  showToast("设置已保存。");
  await loadOverview();
  closeSettingsModal();
}

async function handleRuleToggle(ruleId, enabled) {
  await request(`/api/rules/${ruleId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  await loadOverview();
}

function closeRuleModal(options = {}) {
  state.ruleLibraryOpen = false;
  ruleModalEl.classList.add("hidden");
  ruleModalEl.setAttribute("aria-hidden", "true");
  if (!options.silent) {
    ruleModalBodyEl.scrollTop = 0;
  }
}

async function deleteRule(ruleId) {
  await request(`/api/rules/${ruleId}`, { method: "DELETE" });
  showToast("规则集已删除。");
  await loadOverview(false);
}

function renderRuleLibraryModal(options = {}) {
  const rules = state.overview?.rules || [];
  ruleModalTitleEl.textContent = "已有规则";
  ruleModalMetaEl.textContent = `共 ${rules.length} 个规则集，可在这里查看、启用或删除。`;
  ruleModalBodyEl.innerHTML = rules.length
    ? rules
        .map(
          (rule) => `
            <article class="rule-card modal-rule-card">
              <div class="rule-card-head">
                <div>
                  <h3>${escapeHtml(rule.name)}</h3>
                  <div class="rule-card-meta">
                    <span>${escapeHtml(formatRuleSource(rule.source_format))}</span>
                    <span>${(rule.items || []).length} 条规则</span>
                    <span>${formatTime(rule.updated_at)}</span>
                  </div>
                </div>
                <span class="status-pill ${rule.enabled ? "done" : ""}">${rule.enabled ? "已启用" : "未启用"}</span>
              </div>
              ${(rule.items || []).length
                ? `
                  <div class="rule-modal-list">
                    ${(rule.items || [])
                      .map(
                        (item, index) => `
                          <article class="rule-modal-item">
                            <strong>${index + 1}. ${escapeHtml(item.title || `规则 ${index + 1}`)}</strong>
                            <div class="muted">${escapeHtml(item.body || "")}</div>
                          </article>
                        `
                      )
                      .join("")}
                  </div>
                `
                : `<p class="rule-preview">${escapeHtml(rule.content || "暂无规则内容。")}</p>`}
              <div class="rule-card-actions">
                <div class="rule-card-actions-left">
                  <button type="button" class="ghost action-button danger-button" data-delete-rule="${rule.id}">删除规则</button>
                </div>
                <label class="status-row">
                  <input type="checkbox" data-rule-toggle="${rule.id}" ${rule.enabled ? "checked" : ""} />
                  <span>启用此规则</span>
                </label>
              </div>
            </article>
          `
        )
        .join("")
    : `<p class="muted">当前还没有规则集。</p>`;
  state.ruleLibraryOpen = true;
  ruleModalEl.classList.remove("hidden");
  ruleModalEl.setAttribute("aria-hidden", "false");
  if (!options.preserveScroll) {
    ruleModalBodyEl.scrollTop = 0;
  }
}

function openReviewRulesModal(options = {}) {
  const rules = enabledRules();
  const builtin = builtinRules();
  state.reviewRuleDraftIds = [...state.reviewDraft.ruleIds];
  state.reviewBuiltinRuleDraftIds = [...(state.reviewDraft.builtinRuleIds || [])];
  reviewRulesModalMetaEl.textContent = rules.length
    ? `可选 ${builtin.length} 条系统规则与 ${rules.length} 个已启用规则集，勾选后才会参与本次审稿。`
    : `当前没有已启用自定义规则，你仍可选择 ${builtin.length} 条系统规则参与本次审稿。`;
  reviewRulesModalBodyEl.innerHTML = `
      <section class="rule-modal-section">
        <h4>勾选要启用的系统默认规则</h4>
        <div class="rule-modal-list">
          ${builtin.length
            ? builtin
                .map(
                  (rule) => `
                    <label class="review-rule-option">
                      <input type="checkbox" data-builtin-rule-option="${rule.id}" ${
                        state.reviewBuiltinRuleDraftIds.includes(rule.id) ? "checked" : ""
                      } />
                      <div>
                        <strong>${escapeHtml(rule.title)}</strong>
                        <div class="muted">${escapeHtml(rule.body)}</div>
                      </div>
                    </label>
                  `
                )
                .join("")
            : `<p class="muted">当前没有可用的系统默认规则。</p>`}
        </div>
      </section>
      <section class="rule-modal-section">
        <h4>勾选要启用的自定义规则</h4>
        ${
          rules.length
            ? `
              <div class="rule-modal-list">
                ${rules
                  .map(
                    (rule) => `
                      <label class="review-rule-option">
                        <input type="checkbox" data-review-rule-option="${rule.id}" ${
                          state.reviewRuleDraftIds.includes(rule.id) ? "checked" : ""
                        } />
                        <div>
                          <strong>${escapeHtml(rule.name)}</strong>
                          <div class="muted">${escapeHtml(
                            truncateText((rule.items || []).slice(0, 2).map((item) => item.body).join("；") || rule.content, 120)
                          )}</div>
                        </div>
                      </label>
                    `
                  )
                  .join("")}
              </div>
            `
            : `<p class="muted">当前没有可选自定义规则。你可以先保存规则集并启用它，再回来选择。</p>`
        }
      </section>
    `;
  state.reviewRulesModalOpen = true;
  reviewRulesModalEl.classList.remove("hidden");
  reviewRulesModalEl.setAttribute("aria-hidden", "false");
  if (!options.preserveScroll) {
    reviewRulesModalBodyEl.scrollTop = 0;
  }
}

function closeReviewRulesModal() {
  state.reviewRulesModalOpen = false;
  reviewRulesModalEl.classList.add("hidden");
  reviewRulesModalEl.setAttribute("aria-hidden", "true");
}

function applyReviewRuleSelection() {
  const checkedIds = Array.from(reviewRulesModalBodyEl.querySelectorAll("[data-review-rule-option]:checked")).map(
    (input) => input.dataset.reviewRuleOption
  );
  const checkedBuiltinIds = Array.from(reviewRulesModalBodyEl.querySelectorAll("[data-builtin-rule-option]:checked")).map(
    (input) => input.dataset.builtinRuleOption
  );
  state.reviewDraft.ruleIds = checkedIds;
  state.reviewDraft.builtinRuleIds = checkedBuiltinIds;
  closeReviewRulesModal();
  renderOverviewTab();
}

function currentReviewPayload() {
  return {
    review_mode: state.reviewDraft.mode || state.selectedPaper.metadata.review_mode,
    rule_ids: state.reviewDraft.ruleIds || [],
    builtin_rule_ids: state.reviewDraft.builtinRuleIds || [],
  };
}

async function triggerReview() {
  if (!state.selectedPaperId) return;
  await request(`/api/papers/${state.selectedPaperId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(currentReviewPayload()),
  });
  showToast("审稿任务已开始。");
  await loadOverview();
}

async function triggerReparse() {
  if (!state.selectedPaperId) return;
  await request(`/api/papers/${state.selectedPaperId}/parse`, { method: "POST" });
  state.activeTab = "overview";
  showToast("重新解析任务已开始。");
  await loadOverview();
}

async function triggerExport(format) {
  if (!state.selectedPaperId) return;
  const response = await fetch(`/api/papers/${state.selectedPaperId}/export?format=${encodeURIComponent(format)}`);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "导出失败");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${state.selectedPaperId}.${format === "docx" ? "docx" : format === "pdf" ? "pdf" : "md"}`;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function deletePaper(paperId) {
  await request(`/api/papers/${paperId}`, { method: "DELETE" });
  if (state.selectedPaperId === paperId) {
    state.selectedPaperId = null;
    state.selectedPaper = null;
  }
  showToast("论文任务已删除。");
  await loadOverview(false);
}

async function goHome() {
  state.selectedPaperId = null;
  state.selectedPaper = null;
  state.activeTab = "overview";
  state.selectedIssueId = null;
  state.activeMappingIssueId = null;
  await loadOverview(false);
  showToast("已返回首页。");
}

function bindEvents() {
  paperForm.addEventListener("submit", (event) => handlePaperSubmit(event).catch((error) => showToast(error.message)));
  ruleForm.addEventListener("submit", (event) => handleRuleSubmit(event).catch((error) => showToast(error.message)));
  refreshBtn.addEventListener("click", () => loadOverview().catch((error) => showToast(error.message)));
  reviewBtn.addEventListener("click", () => triggerReview().catch((error) => showToast(error.message)));
  reparseBtn.addEventListener("click", () => triggerReparse().catch((error) => showToast(error.message)));
  exportMarkdownBtn.addEventListener("click", () => triggerExport("markdown").catch((error) => showToast(error.message)));
  exportPdfBtn.addEventListener("click", () => triggerExport("pdf").catch((error) => showToast(error.message)));
  exportDocxBtn.addEventListener("click", () => triggerExport("docx").catch((error) => showToast(error.message)));
  homeBtn.addEventListener("click", () => goHome().catch((error) => showToast(error.message)));
  settingsBtn.addEventListener("click", () => openSettingsModal());
  settingsSaveBtn.addEventListener("click", () => handleSettingsSubmit().catch((error) => showToast(error.message)));
  reviewRulesClearBtn.addEventListener("click", () => {
    reviewRulesModalBodyEl.querySelectorAll("[data-review-rule-option], [data-builtin-rule-option]").forEach((input) => {
      input.checked = false;
    });
  });
  reviewRulesSaveBtn.addEventListener("click", () => applyReviewRuleSelection());
  deleteBtn.addEventListener("click", () => {
    if (!state.selectedPaperId) return;
    if (window.confirm("确定要删除这篇论文任务及其解析/审稿结果吗？")) {
      deletePaper(state.selectedPaperId).catch((error) => showToast(error.message));
    }
  });

  document.body.addEventListener("click", (event) => {
    const tab = event.target.closest(".tab");
    if (tab) {
      state.activeTab = tab.dataset.tab;
      renderTabs();
      return;
    }

    const settingsTabButton = event.target.closest("[data-settings-tab]");
    if (settingsTabButton) {
      state.settingsTab = settingsTabButton.dataset.settingsTab;
      renderSettingsModal();
      return;
    }

    const settingsThemeOption = event.target.closest("[data-settings-theme-option]");
    if (settingsThemeOption) {
      state.settingsDraftTheme = settingsThemeOption.dataset.settingsThemeOption;
      renderSettingsModal();
      return;
    }

    const settingsCloseButton = event.target.closest("[data-close-settings-modal]");
    if (settingsCloseButton) {
      closeSettingsModal();
      return;
    }

    const ruleCloseButton = event.target.closest("[data-close-rule-modal]");
    if (ruleCloseButton) {
      closeRuleModal();
      return;
    }

    const openRuleLibraryButton = event.target.closest("[data-open-rule-library]");
    if (openRuleLibraryButton) {
      renderRuleLibraryModal();
      return;
    }

    const openReviewRulesButton = event.target.closest("[data-open-review-rules]");
    if (openReviewRulesButton) {
      openReviewRulesModal();
      return;
    }

    const closeReviewRulesButton = event.target.closest("[data-close-review-rules-modal]");
    if (closeReviewRulesButton) {
      closeReviewRulesModal();
      return;
    }

    const deleteRuleButton = event.target.closest("[data-delete-rule]");
    if (deleteRuleButton) {
      if (window.confirm("确定要删除这个规则集吗？")) {
        deleteRule(deleteRuleButton.dataset.deleteRule).catch((error) => showToast(error.message));
      }
      return;
    }

    const paperCard = event.target.closest("[data-paper-card]");
    const deletePaperButton = event.target.closest("[data-delete-paper]");
    if (deletePaperButton) {
      event.stopPropagation();
      if (window.confirm("确定要删除这篇论文任务及其解析/审稿结果吗？")) {
        deletePaper(deletePaperButton.dataset.deletePaper).catch((error) => showToast(error.message));
      }
      return;
    }
    if (paperCard) {
      loadPaper(paperCard.dataset.paperCard).catch((error) => showToast(error.message));
      return;
    }

    const reviewIssueCard = event.target.closest("[data-issue-card]");
    if (reviewIssueCard) {
      const issueId = reviewIssueCard.dataset.issueCard;
      state.selectedIssueId = issueId;
      renderReviewTab();
      return;
    }

    const mappingIssueCard = event.target.closest("[data-mapping-nav-issue], [data-inline-issue], [data-related-issue]");
    if (mappingIssueCard) {
      const issueId =
        mappingIssueCard.dataset.mappingNavIssue ||
        mappingIssueCard.dataset.inlineIssue ||
        mappingIssueCard.dataset.relatedIssue;
      toggleMappingIssue(issueId);
      return;
    }
  });

  document.body.addEventListener("change", (event) => {
    const ruleToggle = event.target.closest("[data-rule-toggle]");
    if (ruleToggle) {
      handleRuleToggle(ruleToggle.dataset.ruleToggle, ruleToggle.checked).catch((error) => showToast(error.message));
      return;
    }

    const reviewModeSelect = event.target.closest("#detail-review-mode");
    if (reviewModeSelect) {
      state.reviewDraft.mode = reviewModeSelect.value;
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !settingsModalEl.classList.contains("hidden")) {
      closeSettingsModal();
      return;
    }
    if (event.key === "Escape" && !ruleModalEl.classList.contains("hidden")) {
      closeRuleModal();
      return;
    }
    if (event.key === "Escape" && !reviewRulesModalEl.classList.contains("hidden")) {
      closeReviewRulesModal();
    }
  });
}

function startPolling() {
  setInterval(async () => {
    const papers = state.overview?.papers || [];
    const busy = papers.some(
      (paper) => ["queued", "running"].includes(paper.parse_status) || ["queued", "running"].includes(paper.review_status)
    );
    if (busy) {
      await loadOverview();
    }
  }, 5000);
}

async function main() {
  initTheme();
  state.settingsDraftTheme = currentTheme();
  bindDropzones();
  bindEvents();
  await loadOverview(false);
  startPolling();
}

main().catch((error) => showToast(error.message));
