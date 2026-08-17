const {
  ItemView,
  MarkdownRenderer,
  MarkdownView,
  Notice,
  Plugin,
  PluginSettingTab,
  requestUrl,
  Setting,
} = require("obsidian");

const VIEW_TYPE_ALEXANDRIA_LIBRARIAN = "alexandria-librarian-view";

const DEFAULT_SETTINGS = {
  apiUrl: "http://127.0.0.1:8000",
  operatorApiKey: "",
  backendVaultPath: "",
  backendAlexandriaRoot: ".",
  defaultProject: "heterarchy-alexandria",
  autoSaveTranscripts: false,
  preferredProviderId: "",
  preferredProfileId: "",
  useLangGraphWorkflow: true,
  showRelatedNotes: true,
  autoRefreshRelated: true,
  contextScope: "vault",
  sourceLimit: 12,
  noteTypeFilter: "",
};

module.exports = class AlexandriaLibrarianPlugin extends Plugin {
  async onload() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    this.registerView(
      VIEW_TYPE_ALEXANDRIA_LIBRARIAN,
      (leaf) => new AlexandriaLibrarianView(leaf, this)
    );
    this.addCommand({
      id: "ask-alexandria-librarian",
      name: "Ask Alexandria Librarian",
      callback: () => this.activateView(),
    });
    this.addRibbonIcon("messages-square", "Ask Alexandria Librarian", () => {
      this.activateView();
    });
    this.addSettingTab(new AlexandriaLibrarianSettingTab(this.app, this));
  }

  async onunload() {
    this.app.workspace.detachLeavesOfType(VIEW_TYPE_ALEXANDRIA_LIBRARIAN);
  }

  async activateView() {
    this.app.workspace.detachLeavesOfType(VIEW_TYPE_ALEXANDRIA_LIBRARIAN);
    const leaf = this.app.workspace.getRightLeaf(false);
    await leaf.setViewState({
      type: VIEW_TYPE_ALEXANDRIA_LIBRARIAN,
      active: true,
    });
    this.app.workspace.revealLeaf(leaf);
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }
};

class AlexandriaLibrarianView extends ItemView {
  constructor(leaf, plugin) {
    super(leaf);
    this.plugin = plugin;
    this.lastResponse = null;
    this.lastWorkflow = null;
    this.history = [];
    this.currentQuery = "";
    this.answerContainer = null;
    this.delegateContainer = null;
    this.historyContainer = null;
    this.sourceContainer = null;
    this.statusEl = null;
    this.relatedContainer = null;
    this.graphActionContainer = null;
    this.workflowContainer = null;
    this.oauthContainer = null;
    this.oauthStartPayload = null;
    this.oauthStatusPayload = null;
  }

  getViewType() {
    return VIEW_TYPE_ALEXANDRIA_LIBRARIAN;
  }

  getDisplayText() {
    return "Alexandria Librarian";
  }

  getIcon() {
    return "messages-square";
  }

  async onOpen() {
    this.render();
  }

  async onClose() {}

  render() {
    const container = this.containerEl.children[1];
    container.empty();
    container.addClass("alexandria-librarian-view");

    container.createEl("h2", { text: "Alexandria Librarian" });
    container.createEl("p", {
      cls: "alexandria-muted alexandria-hero-copy",
      text: "Ask the indexed Alexandria vault. Advanced controls stay tucked away until needed.",
    });

    const askCard = container.createDiv({ cls: "alexandria-ask-card" });
    askCard.createEl("h3", { text: "Ask vault" });
    const queryInput = askCard.createEl("textarea", {
      cls: "alexandria-query",
      attr: {
        rows: "5",
        placeholder: "Ask across memory, skills, prompts, plans, and notes...",
      },
    });

    const quickActions = askCard.createDiv({ cls: "alexandria-controls" });
    const askButton = quickActions.createEl("button", {
      text: "Ask vault",
      cls: "mod-cta",
    });

    const advanced = askCard.createEl("details", { cls: "alexandria-advanced" });
    advanced.createEl("summary", { text: "Advanced options" });
    const activePath = this.activePath();
    advanced.createEl("p", {
      cls: "alexandria-muted alexandria-compact-note",
      text: activePath ? `Current note: ${activePath}` : "Whole-vault mode; no active note required.",
    });

    const scopeGrid = advanced.createDiv({ cls: "alexandria-control-grid" });
    const scopeLabel = scopeGrid.createEl("label", { cls: "alexandria-field" });
    scopeLabel.createSpan({ text: "Scope" });
    const scopeSelect = scopeLabel.createEl("select");
    this.selectOption(scopeSelect, "vault", "Whole vault");
    this.selectOption(scopeSelect, "active", "Active note + vault");
    this.selectOption(scopeSelect, "selection", "Selection + vault");
    scopeSelect.value = this.contextScope();
    scopeSelect.addEventListener("change", async () => {
      this.plugin.settings.contextScope = scopeSelect.value;
      await this.plugin.saveSettings();
      this.renderScopeHint(scopeHint, scopeSelect.value);
    });

    const typeLabel = scopeGrid.createEl("label", { cls: "alexandria-field" });
    typeLabel.createSpan({ text: "Note type" });
    const typeSelect = typeLabel.createEl("select");
    this.selectOption(typeSelect, "", "All note types");
    this.selectOption(typeSelect, "context", "Context");
    this.selectOption(typeSelect, "memory_compact", "Memory compacts");
    this.selectOption(typeSelect, "skill", "Skills");
    this.selectOption(typeSelect, "prompt", "Prompts");
    this.selectOption(typeSelect, "job_plan", "Job plans");
    typeSelect.value = this.plugin.settings.noteTypeFilter || "";
    typeSelect.addEventListener("change", async () => {
      this.plugin.settings.noteTypeFilter = typeSelect.value;
      await this.plugin.saveSettings();
    });

    const limitLabel = scopeGrid.createEl("label", { cls: "alexandria-field" });
    limitLabel.createSpan({ text: "Sources" });
    const limitSelect = limitLabel.createEl("select");
    for (const value of [8, 12, 20, 30]) {
      this.selectOption(limitSelect, String(value), String(value));
    }
    limitSelect.value = String(this.sourceLimit());
    limitSelect.addEventListener("change", async () => {
      this.plugin.settings.sourceLimit = Number(limitSelect.value) || 12;
      await this.plugin.saveSettings();
    });

    const scopeHint = advanced.createDiv({ cls: "alexandria-muted" });
    this.renderScopeHint(scopeHint, scopeSelect.value);

    const controls = advanced.createDiv({ cls: "alexandria-controls" });
    const saveLabel = controls.createEl("label", { cls: "alexandria-checkbox" });
    const saveInput = saveLabel.createEl("input", { type: "checkbox" });
    saveInput.checked = this.plugin.settings.autoSaveTranscripts;
    saveLabel.createSpan({ text: "Save transcript" });

    const delegateLabel = controls.createEl("label", { cls: "alexandria-checkbox" });
    const delegateInput = delegateLabel.createEl("input", { type: "checkbox" });
    delegateInput.checked = this.oauthStatusPayload?.connected === true;
    delegateLabel.createSpan({ text: "Ask OAuth librarian" });

    const workflowLabel = controls.createEl("label", { cls: "alexandria-checkbox" });
    const workflowInput = workflowLabel.createEl("input", { type: "checkbox" });
    workflowInput.checked = this.plugin.settings.useLangGraphWorkflow;
    workflowLabel.createSpan({ text: "Approval workflow" });

    const providerInput = controls.createEl("input", {
      cls: "alexandria-inline-input",
      attr: { placeholder: "provider id/name" },
    });
    providerInput.value = this.providerReference();

    const profileInput = controls.createEl("input", {
      cls: "alexandria-inline-input",
      attr: { placeholder: "profile id/name" },
    });
    profileInput.value = this.plugin.settings.preferredProfileId || "research-critic";

    const utilityActions = advanced.createDiv({ cls: "alexandria-actions" });
    this.actionButton(utilityActions, "Refresh related", () => this.refreshRelated());
    this.actionButton(utilityActions, "Check OAuth", () => this.checkOAuthStatus());

    askButton.addEventListener("click", async () => {
      await this.ask(queryInput.value, {
        saveTranscript: saveInput.checked,
        delegateToLibrarian: delegateInput.checked,
        providerId: providerInput.value.trim(),
        profileId: profileInput.value.trim(),
        useWorkflow: workflowInput.checked,
        contextScope: scopeSelect.value,
        noteTypeFilter: typeSelect.value,
        sourceLimit: Number(limitSelect.value) || 12,
      });
    });

    this.statusEl = container.createDiv({ cls: "alexandria-status" });
    this.answerContainer = container.createDiv({ cls: "alexandria-answer" });
    this.delegateContainer = container.createDiv({ cls: "alexandria-delegate" });
    this.sourceContainer = container.createDiv({ cls: "alexandria-sources" });
    this.workflowContainer = container.createDiv({ cls: "alexandria-workflow" });
    this.graphActionContainer = container.createDiv({ cls: "alexandria-graph-actions" });
    this.postAnswerActions = container.createDiv({
      cls: "alexandria-actions alexandria-post-actions",
    });

    this.relatedContainer = container.createDiv({ cls: "alexandria-related" });
    if (this.plugin.settings.showRelatedNotes && this.activePath()) {
      this.refreshRelated();
    }

    this.historyContainer = container.createDiv({ cls: "alexandria-history" });
    this.renderHistory();

    const oauthDetails = container.createEl("details", { cls: "alexandria-advanced" });
    oauthDetails.createEl("summary", { text: "OAuth connection" });
    this.oauthContainer = oauthDetails.createDiv({ cls: "alexandria-oauth" });
    this.renderOAuthPanel();
  }

  selectOption(select, value, text) {
    const option = select.createEl("option", { text });
    option.value = value;
    return option;
  }

  contextScope() {
    const scope = this.plugin.settings.contextScope || "vault";
    return ["vault", "active", "selection"].includes(scope) ? scope : "vault";
  }

  sourceLimit() {
    const limit = Number(this.plugin.settings.sourceLimit) || 12;
    return Math.min(Math.max(limit, 1), 50);
  }

  typeFilters(noteTypeFilter) {
    return noteTypeFilter ? [noteTypeFilter] : [];
  }

  activePathForScope(scope) {
    return scope === "active" || scope === "selection" ? this.activePath() : null;
  }

  selectionForScope(scope) {
    return scope === "selection" ? this.selectionText() : null;
  }

  renderScopeHint(element, scope) {
    element.empty();
    const text =
      scope === "active"
        ? "The librarian searches the whole vault and also pins the active note as context."
        : scope === "selection"
          ? "The librarian searches the whole vault using the selected text as extra context."
          : "The librarian searches the whole indexed vault without requiring an active note.";
    element.setText(text);
  }

  actionButton(parent, text, handler) {
    const button = parent.createEl("button", { text });
    button.addEventListener("click", async () => {
      try {
        await handler();
      } catch (error) {
        this.showError(error);
      }
    });
  }

  renderPostAnswerActions() {
    if (!this.postAnswerActions) {
      return;
    }
    this.postAnswerActions.empty();
    if (!this.lastResponse?.answer_markdown) {
      return;
    }
    this.actionButton(this.postAnswerActions, "Append to current note", () => this.appendAnswer());
    this.actionButton(this.postAnswerActions, "Link sources", () => this.appendGraphLinks());
    this.actionButton(this.postAnswerActions, "Create context note", () => this.createNote("context"));
    this.actionButton(this.postAnswerActions, "Create skill draft", () => this.createNote("skill"));
    this.actionButton(this.postAnswerActions, "Create prompt", () => this.createNote("prompt"));
  }

  recordHistory(query, response, workflow) {
    const entryId =
      workflow?.thread_id ||
      response?.conversation_id ||
      `local-${Date.now().toString()}`;
    const entry = {
      id: entryId,
      query,
      response,
      workflow,
      status: workflow?.status || "answered",
      delegateStatus: response?.delegate_status || "local_only",
      transcriptPath: response?.transcript_path || null,
      timestamp: new Date().toLocaleTimeString(),
    };
    const existingIndex = this.history.findIndex((item) => item.id === entryId);
    if (existingIndex >= 0) {
      this.history.splice(existingIndex, 1);
    }
    this.history.unshift(entry);
    this.history = this.history.slice(0, 20);
    this.renderHistory();
  }

  renderHistory() {
    if (!this.historyContainer) {
      return;
    }
    this.historyContainer.empty();
    if (this.history.length === 0) {
      return;
    }
    this.historyContainer.createEl("h3", { text: "Conversation history" });
    for (const entry of this.history) {
      const row = this.historyContainer.createDiv({ cls: "alexandria-history-row" });
      const button = row.createEl("button", {
        cls: "alexandria-history-button",
        text: this.truncate(entry.query, 72),
      });
      button.addEventListener("click", async () => {
        this.lastResponse = entry.response;
        this.lastWorkflow = entry.workflow;
        await this.renderAnswer(entry.response);
        await this.renderGraphActions(entry.response, entry.workflow);
        await this.renderDelegateResult(entry.response);
        this.renderWorkflowStatus(entry.workflow, entry.response);
        this.setStatus(`Restored ${entry.timestamp}`);
      });
      this.badge(row, entry.status);
      this.badge(row, `delegate:${entry.delegateStatus}`);
      if (entry.transcriptPath) {
        this.badge(row, "saved");
      }
      row.createSpan({ cls: "alexandria-muted", text: ` ${entry.timestamp}` });
    }
  }

  truncate(value, maxLength) {
    const text = String(value || "");
    return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
  }

  badge(parent, text) {
    return parent.createSpan({
      cls: `alexandria-pill alexandria-pill-${this.badgeKind(text)}`,
      text: String(text || "unknown"),
    });
  }

  badgeKind(text) {
    const normalized = String(text || "").toLowerCase();
    if (normalized.includes("complete") || normalized.includes("saved")) {
      return "success";
    }
    if (normalized.includes("waiting") || normalized.includes("pending")) {
      return "warning";
    }
    if (normalized.includes("guidance") || normalized.includes("unavailable")) {
      return "muted";
    }
    return "default";
  }


  providerReference() {
    return this.plugin.settings.preferredProviderId || "codex-oauth";
  }

  renderOAuthPanel() {
    if (!this.oauthContainer) {
      return;
    }
    this.oauthContainer.empty();
    this.oauthContainer.createEl("h3", { text: "GPT OAuth connection" });
    this.oauthContainer.createEl("p", {
      cls: "alexandria-muted",
      text:
        "Connect the GPT OAuth provider from Obsidian. Tokens stay in the local backend, not in the vault.",
    });

    const providerRow = this.oauthContainer.createDiv({ cls: "alexandria-oauth-row" });
    providerRow.createEl("label", {
      cls: "alexandria-muted",
      text: "Provider id/name",
    });
    const providerInput = providerRow.createEl("input", {
      cls: "alexandria-inline-input alexandria-oauth-provider",
      attr: { placeholder: "codex-oauth" },
    });
    providerInput.value = this.providerReference();
    providerInput.addEventListener("change", async () => {
      this.plugin.settings.preferredProviderId = providerInput.value.trim();
      await this.plugin.saveSettings();
      this.oauthStartPayload = null;
      this.oauthStatusPayload = null;
      this.renderOAuthPanel();
    });

    const buttonRow = this.oauthContainer.createDiv({ cls: "alexandria-controls" });
    this.actionButton(buttonRow, "Check OAuth status", () => this.checkOAuthStatus());
    this.actionButton(buttonRow, "Start OAuth login", () => this.startOAuthLogin());
    this.actionButton(buttonRow, "Poll after login", () => this.pollOAuthLogin());
    this.actionButton(buttonRow, "Refresh token", () => this.refreshOAuthToken());

    this.renderOAuthPayloads();
  }

  renderOAuthPayloads() {
    if (!this.oauthContainer) {
      return;
    }
    const details = this.oauthContainer.createDiv({ cls: "alexandria-oauth-details" });
    if (this.oauthStatusPayload) {
      const status = this.oauthStatusPayload.status || "unknown";
      this.badge(details, status);
      details.createEl("p", {
        cls: "alexandria-muted",
        text: this.oauthStatusText(this.oauthStatusPayload),
      });
    } else {
      details.createEl("p", {
        cls: "alexandria-muted",
        text: "Status not checked yet.",
      });
    }

    if (!this.oauthStartPayload) {
      return;
    }
    const startCard = details.createDiv({ cls: "alexandria-action-card" });
    startCard.createEl("strong", { text: "Device login started" });
    this.badge(startCard, this.oauthStartPayload.status || "pending");
    if (this.oauthStartPayload.user_code) {
      startCard.createEl("p", {
        text: `Code: ${this.oauthStartPayload.user_code}`,
      });
    }
    if (this.oauthStartPayload.verification_uri) {
      startCard.createEl("p", {
        cls: "alexandria-muted",
        text: this.oauthStartPayload.verification_uri,
      });
    }
    if (this.oauthStartPayload.expires_at) {
      startCard.createEl("p", {
        cls: "alexandria-muted",
        text: `Expires: ${this.oauthStartPayload.expires_at}`,
      });
    }
    const linkRow = startCard.createDiv({ cls: "alexandria-controls" });
    this.actionButton(linkRow, "Open login page", () => this.openOAuthLoginPage());
    this.actionButton(linkRow, "Copy code", () => this.copyOAuthUserCode());
  }

  oauthStatusText(payload) {
    const connected = payload.connected ? "connected" : "not connected";
    const expiry = payload.expires_at ? ` · expires ${payload.expires_at}` : "";
    const refresh = payload.refresh_required ? " · refresh required" : "";
    const message = payload.message ? ` · ${payload.message}` : "";
    return `${this.providerReference()}: ${connected}${expiry}${refresh}${message}`;
  }

  async checkOAuthStatus() {
    this.setStatus("Checking OAuth status...");
    this.oauthStatusPayload = await this.getJson(
      `/settings/connections/${encodeURIComponent(this.providerReference())}/oauth/status`
    );
    this.renderOAuthPanel();
    this.setStatus(this.oauthStatusText(this.oauthStatusPayload));
  }

  async startOAuthLogin() {
    this.setStatus("Starting OAuth device login...");
    this.oauthStartPayload = await this.postJson(
      `/settings/connections/${encodeURIComponent(this.providerReference())}/oauth/start`,
      {}
    );
    this.oauthStatusPayload = null;
    this.renderOAuthPanel();
    this.openOAuthLoginPage();
    this.setStatus("OAuth started. Complete login, then click Poll after login.");
  }

  async pollOAuthLogin() {
    this.setStatus("Polling OAuth login...");
    this.oauthStatusPayload = await this.postJson(
      `/settings/connections/${encodeURIComponent(this.providerReference())}/oauth/poll`,
      {}
    );
    this.renderOAuthPanel();
    this.setStatus(this.oauthStatusText(this.oauthStatusPayload));
  }

  async refreshOAuthToken() {
    this.setStatus("Refreshing OAuth token if needed...");
    this.oauthStatusPayload = await this.postJson(
      `/settings/connections/${encodeURIComponent(this.providerReference())}/oauth/refresh`,
      {}
    );
    this.renderOAuthPanel();
    this.setStatus(this.oauthStatusText(this.oauthStatusPayload));
  }

  openOAuthLoginPage() {
    const payload = this.oauthStartPayload || {};
    const url = payload.verification_uri_complete || payload.verification_uri;
    if (!url) {
      new Notice("Start OAuth login first.");
      return;
    }
    window.open(url, "_blank");
  }

  async copyOAuthUserCode() {
    const code = this.oauthStartPayload?.user_code;
    if (!code) {
      new Notice("Start OAuth login first.");
      return;
    }
    if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
      new Notice(`OAuth code: ${code}`);
      return;
    }
    await navigator.clipboard.writeText(code);
    new Notice("OAuth user code copied.");
  }

  activeView() {
    return this.app.workspace.getActiveViewOfType(MarkdownView);
  }

  activePath() {
    return this.activeView()?.file?.path || null;
  }

  selectionText() {
    const view = this.activeView();
    if (!view) {
      return null;
    }
    const selection = view.editor.getSelection();
    return selection.trim() ? selection : null;
  }

  async ask(query, options) {
    if (!query.trim()) {
      new Notice("Ask Alexandria Librarian: enter a question first.");
      return;
    }
    this.currentQuery = query.trim();
    this.setStatus("Asking Alexandria...");
    if (options.useWorkflow) {
      await this.startWorkflow(query, options);
      return;
    }
    const response = await this.postJson("/obsidian/librarian/ask", {
      query,
      active_note_path: this.activePathForScope(options.contextScope),
      selection: this.selectionForScope(options.contextScope),
      project: this.plugin.settings.defaultProject || null,
      preferred_alexandria_types: this.typeFilters(options.noteTypeFilter),
      max_source_refs: options.sourceLimit || this.sourceLimit(),
      save_transcript: options.saveTranscript,
      delegate_to_librarian: options.delegateToLibrarian,
      provider_id: options.providerId || null,
      profile_id: options.profileId || null,
    });
    this.lastResponse = response;
    this.lastWorkflow = null;
    this.recordHistory(this.currentQuery, response, null);
    await this.renderAnswer(response);
    await this.renderGraphActions(response, null);
    await this.renderDelegateResult(response);
    this.renderWorkflowStatus(null, response);
    this.setStatus(response.transcript_path ? `Saved: ${response.transcript_path}` : "Ready");
  }

  async startWorkflow(query, options) {
    const workflow = await this.postJson("/obsidian/librarian/workflows", {
      query,
      active_note_path: this.activePathForScope(options.contextScope),
      selection: this.selectionForScope(options.contextScope),
      project: this.plugin.settings.defaultProject || null,
      preferred_alexandria_types: this.typeFilters(options.noteTypeFilter),
      max_source_refs: options.sourceLimit || this.sourceLimit(),
      save_transcript: false,
      delegate_to_librarian: options.delegateToLibrarian,
      provider_id: options.providerId || null,
      profile_id: options.profileId || null,
    });
    this.lastWorkflow = workflow;
    this.lastResponse = this.responseFromWorkflow(workflow);
    this.recordHistory(this.currentQuery, this.lastResponse, workflow);
    await this.renderAnswer(this.lastResponse);
    await this.renderGraphActions(this.lastResponse, workflow);
    await this.renderDelegateResult(this.lastResponse);
    this.renderWorkflowStatus(workflow, this.lastResponse);
    this.setStatus(`Workflow waiting: ${workflow.thread_id}`);
  }


  async refreshRelated() {
    if (!this.relatedContainer) {
      return;
    }
    this.relatedContainer.empty();
    this.relatedContainer.createEl("h3", { text: "Related notes" });
    const activePath = this.activePath();
    if (!activePath) {
      this.relatedContainer.createEl("p", {
        cls: "alexandria-muted",
        text: "Open a Markdown note to load related notes.",
      });
      return;
    }
    try {
      const response = await this.getJson(
        `/obsidian/notes/by-path/related?path=${encodeURIComponent(activePath)}`
      );
      const items = Array.isArray(response.items) ? response.items : [];
      if (items.length === 0) {
        this.relatedContainer.createEl("p", {
          cls: "alexandria-muted",
          text: "No graph edges found yet. Reindex after adding wikilinks.",
        });
        return;
      }
      const list = this.relatedContainer.createEl("ul");
      for (const item of items) {
        const note = item.note || {};
        const row = list.createEl("li");
        const link = row.createEl("a", { text: note.wikilink || note.path, href: "#" });
        link.addEventListener("click", async (event) => {
          event.preventDefault();
          await this.openSource(note.path);
        });
        row.createSpan({
          cls: "alexandria-badge",
          text: ` ${item.relation || "related"} · ${item.direction || "edge"}`,
        });
      }
    } catch (error) {
      this.relatedContainer.createEl("p", {
        cls: "alexandria-muted",
        text: `Related notes unavailable: ${error.message || error}`,
      });
    }
  }

  async renderAnswer(response) {
    this.answerContainer.empty();
    this.answerContainer.createEl("h3", { text: "Answer" });
    const markdownTarget = this.answerContainer.createDiv();
    await MarkdownRenderer.render(
      this.app,
      response.answer_markdown || "_No answer returned._",
      markdownTarget,
      this.activePath() || "",
      this
    );
    this.renderPostAnswerActions();

    this.sourceContainer.empty();
    this.sourceContainer.createEl("h3", { text: "Sources" });
    const refs = Array.isArray(response.source_refs) ? response.source_refs : [];
    if (refs.length === 0) {
      this.sourceContainer.createEl("p", {
        cls: "alexandria-muted",
        text: "No source notes returned.",
      });
      return;
    }
    const list = this.sourceContainer.createEl("ul");
    for (const ref of refs) {
      const item = list.createEl("li");
      const link = item.createEl("a", {
        text: ref.wikilink || ref.title || ref.path,
        href: "#",
      });
      link.addEventListener("click", async (event) => {
        event.preventDefault();
        await this.openSource(ref.path);
      });
    }
  }


  async renderDelegateResult(response) {
    if (!this.delegateContainer) {
      return;
    }
    this.delegateContainer.empty();
    const status = response.delegate_status || "local_only";
    const delegateMarkdown = this.delegateMarkdown(response.answer_markdown || "");
    if (status === "local_only" && !delegateMarkdown) {
      return;
    }
    this.delegateContainer.createEl("h3", { text: "GPT OAuth Librarian" });
    this.badge(this.delegateContainer, status);
    if (response.provider_id || response.profile_id) {
      this.delegateContainer.createEl("p", {
        cls: "alexandria-muted",
        text: `Provider ${response.provider_id || "auto"} · profile ${
          response.profile_id || "auto"
        }`,
      });
    }
    if (!delegateMarkdown) {
      this.delegateContainer.createEl("p", {
        cls: "alexandria-muted",
        text: "Delegate status is available, but no delegate summary was returned.",
      });
      return;
    }
    const target = this.delegateContainer.createDiv({
      cls: "alexandria-delegate-body",
    });
    await MarkdownRenderer.render(
      this.app,
      delegateMarkdown,
      target,
      this.activePath() || "",
      this
    );
  }

  delegateMarkdown(answerMarkdown) {
    const match = String(answerMarkdown).match(
      /(?:^|\n)## GPT OAuth Librarian\s*\n([\s\S]*)/u
    );
    return match ? match[1].trim() : "";
  }

  renderWorkflowStatus(workflow, response) {
    if (!this.workflowContainer) {
      return;
    }
    this.workflowContainer.empty();
    if (!workflow) {
      return;
    }
    this.workflowContainer.createEl("h3", { text: "Workflow status" });
    const header = this.workflowContainer.createDiv({
      cls: "alexandria-workflow-badges",
    });
    this.badge(header, workflow.status || "unknown");
    this.badge(header, response.delegate_status || "local_only");
    if (workflow.transcript_path || response.transcript_path) {
      this.badge(header, "saved");
    }
    this.workflowContainer.createEl("p", {
      cls: "alexandria-muted",
      text: `Thread ${workflow.thread_id}`,
    });
    const completed = Array.isArray(workflow.completed_actions)
      ? workflow.completed_actions
      : [];
    if (completed.length > 0) {
      const list = this.workflowContainer.createEl("ul");
      for (const action of completed) {
        list.createEl("li", { text: String(action) });
      }
    }
  }


  async renderGraphActions(response, workflow) {
    if (!this.graphActionContainer) {
      return;
    }
    this.graphActionContainer.empty();
    const actions = Array.isArray(response.action_preview) ? response.action_preview : [];
    if (workflow?.status === "waiting_for_approval") {
      this.graphActionContainer.createEl("h3", { text: "Proposed graph actions" });
      this.renderWorkflowApproval(workflow);
      return;
    }
    if (actions.length === 0) {
      return;
    }
    this.graphActionContainer.createEl("h3", { text: "Proposed graph actions" });
    if (response.delegate_status && response.delegate_status !== "local_only") {
      this.graphActionContainer.createEl("p", {
        cls: "alexandria-muted",
        text: `Delegate: ${response.delegate_status}`,
      });
    }
    const list = this.graphActionContainer.createEl("ul");
    for (const action of actions) {
      list.createEl("li", { text: action });
    }
  }

  renderWorkflowApproval(workflow) {
    const actions = Array.isArray(workflow.pending_actions) ? workflow.pending_actions : [];
    if (actions.length === 0) {
      this.graphActionContainer.createEl("p", {
        cls: "alexandria-muted",
        text: "No pending workflow actions.",
      });
      return;
    }
    const form = this.graphActionContainer.createDiv({ cls: "alexandria-workflow-form" });
    const selected = new Set();
    for (const action of actions) {
      const actionId = String(action.id || "");
      if (!actionId) {
        continue;
      }
      const card = form.createDiv({ cls: "alexandria-action-card" });
      const label = card.createEl("label", { cls: "alexandria-checkbox" });
      const input = label.createEl("input", { type: "checkbox" });
      if (actionId === "save_transcript" && this.plugin.settings.autoSaveTranscripts) {
        input.checked = true;
        selected.add(actionId);
      }
      if (actionId === "ask_oauth_librarian") {
        input.checked = true;
        selected.add(actionId);
      }
      input.addEventListener("change", () => {
        if (input.checked) {
          selected.add(actionId);
        } else {
          selected.delete(actionId);
        }
      });
      label.createEl("strong", { text: action.label || actionId });
      this.badge(card, action.type || "action");
      card.createEl("p", {
        cls: "alexandria-muted",
        text: this.actionDescription(actionId),
      });
    }
    const resumeButton = form.createEl("button", {
      text: "Resume approved actions",
      cls: "mod-cta",
    });
    resumeButton.addEventListener("click", async () => {
      try {
        await this.resumeWorkflow(Array.from(selected));
      } catch (error) {
        this.showError(error);
      }
    });
  }

  actionDescription(actionId) {
    if (actionId === "save_transcript") {
      return "Save the current conversation as an Obsidian librarian_chat note.";
    }
    if (actionId === "create_context_note") {
      return "Create a context note from the local librarian answer.";
    }
    if (actionId === "add_graph_links") {
      return "Apply approved Alexandria graph/source links to the active note.";
    }
    if (actionId === "ask_oauth_librarian") {
      return "Ask the configured GPT OAuth librarian; tokens remain in the backend.";
    }
    return "Approve this backend workflow action.";
  }

  async resumeWorkflow(approvedActions) {
    if (!this.lastWorkflow?.thread_id) {
      new Notice("Start a LangGraph workflow first.");
      return;
    }
    this.setStatus("Resuming LangGraph workflow...");
    const workflow = await this.postJson(
      `/obsidian/librarian/workflows/${encodeURIComponent(this.lastWorkflow.thread_id)}/resume`,
      { approved_actions: approvedActions }
    );
    this.lastWorkflow = workflow;
    this.lastResponse = this.responseFromWorkflow(workflow);
    this.recordHistory(workflow.query || this.currentQuery, this.lastResponse, workflow);
    await this.renderAnswer(this.lastResponse);
    await this.renderGraphActions(this.lastResponse, workflow);
    await this.renderDelegateResult(this.lastResponse);
    this.renderWorkflowStatus(workflow, this.lastResponse);
    this.setStatus(`Workflow ${workflow.status}: ${workflow.thread_id}`);
  }

  responseFromWorkflow(workflow) {
    const response = workflow.response || {};
    const completed = Array.isArray(workflow.completed_actions) ? workflow.completed_actions : [];
    const delegated = completed.some((action) => String(action).startsWith("ask_oauth_librarian:"));
    const delegateStatus =
      response.delegate_status ||
      (delegated ? "completed" : workflow.status === "waiting_for_approval" ? "pending" : "local_only");
    return Object.assign({}, response, {
      conversation_id: response.conversation_id || workflow.thread_id,
      transcript_path: workflow.transcript_path || response.transcript_path || null,
      delegate_status: delegateStatus,
      provider_id: response.provider_id || workflow.provider_id || null,
      profile_id: response.profile_id || workflow.profile_id || null,
    });
  }

  async openSource(path) {
    if (!path || path.includes("..")) {
      new Notice("Alexandria source path is invalid.");
      return;
    }
    const linkText = path.replace(/\.md$/u, "");
    await this.app.workspace.openLinkText(linkText, "", false);
  }

  async appendAnswer() {
    if (!this.lastResponse?.answer_markdown) {
      new Notice("Ask the librarian before appending an answer.");
      return;
    }
    const view = this.activeView();
    if (!view?.file) {
      new Notice("Open a Markdown note before appending.");
      return;
    }
    await this.app.vault.append(
      view.file,
      `\n\n## Alexandria Librarian\n\n${this.lastResponse.answer_markdown}\n`
    );
    new Notice("Alexandria answer appended to current note.");
  }


  async appendGraphLinks() {
    const refs = Array.isArray(this.lastResponse?.source_refs) ? this.lastResponse.source_refs : [];
    if (refs.length === 0) {
      new Notice("Ask the librarian before linking sources.");
      return;
    }
    const view = this.activeView();
    if (!view?.file) {
      new Notice("Open a Markdown note before linking sources.");
      return;
    }
    const current = await this.app.vault.read(view.file);
    const block = this.alexandriaLinksBlock(refs);
    const next = current.match(/<!-- ALEXANDRIA-LINKS:START -->[\s\S]*<!-- ALEXANDRIA-LINKS:END -->/u)
      ? current.replace(/<!-- ALEXANDRIA-LINKS:START -->[\s\S]*<!-- ALEXANDRIA-LINKS:END -->/u, block)
      : `${current.trimEnd()}\n\n${block}\n`;
    await this.app.vault.modify(view.file, next);
    new Notice("Alexandria source wikilinks added to current note.");
    await this.refreshRelated();
  }

  alexandriaLinksBlock(refs) {
    const lines = refs.map((ref) => `- ${ref.wikilink || `[[${String(ref.path || "").replace(/\.md$/u, "")}]]`} — cites`);
    return [
      "<!-- ALEXANDRIA-LINKS:START -->",
      "## Alexandria Links",
      "",
      "### Sources",
      ...lines,
      "<!-- ALEXANDRIA-LINKS:END -->",
    ].join("\n");
  }

  async createNote(alexandriaType) {
    if (!this.lastResponse?.answer_markdown) {
      new Notice("Ask the librarian before creating a note.");
      return;
    }
    const titles = {
      context: "Context Note",
      skill: "Skill Draft",
      prompt: "Prompt Template",
    };
    const title = titles[alexandriaType] || "Context Note";
    const response = await this.postJson("/obsidian/notes", {
      title: `Alexandria ${title}`,
      body: this.lastResponse.answer_markdown,
      alexandria_type: alexandriaType,
      tags: ["alexandria", "librarian", alexandriaType],
      project: this.plugin.settings.defaultProject || null,
      source: "obsidian-plugin",
    });
    new Notice(`Created ${response.path || response.id}`);
    if (response.path) {
      await this.openSource(response.path);
    }
  }


  async getJson(path) {
    const url = `${this.plugin.settings.apiUrl.replace(/\/$/u, "")}${path}`;
    const headers = {};
    if (this.plugin.settings.operatorApiKey) {
      headers["X-Alexandria-Operator-Key"] = this.plugin.settings.operatorApiKey;
    }
    const response = await requestUrl({ url, method: "GET", headers });
    if (response.status < 200 || response.status >= 300) {
      throw new Error(`Alexandria request failed (${response.status})`);
    }
    return response.json;
  }

  async postJson(path, payload) {
    const url = `${this.plugin.settings.apiUrl.replace(/\/$/u, "")}${path}`;
    const headers = { "Content-Type": "application/json" };
    if (this.plugin.settings.operatorApiKey) {
      headers["X-Alexandria-Operator-Key"] = this.plugin.settings.operatorApiKey;
    }
    const response = await requestUrl({
      url,
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    if (response.status < 200 || response.status >= 300) {
      throw new Error(`Alexandria request failed (${response.status})`);
    }
    return response.json;
  }

  setStatus(text) {
    if (this.statusEl) {
      this.statusEl.setText(text);
    }
  }

  showError(error) {
    const message = error instanceof Error ? error.message : String(error);
    this.setStatus(message);
    new Notice(`Alexandria Librarian: ${message}`);
  }
}

class AlexandriaLibrarianSettingTab extends PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Alexandria Librarian" });

    new Setting(containerEl)
      .setName("Alexandria API URL")
      .setDesc("Local heterarchy-alexandria backend URL.")
      .addText((text) =>
        text
          .setPlaceholder(DEFAULT_SETTINGS.apiUrl)
          .setValue(this.plugin.settings.apiUrl)
          .onChange(async (value) => {
            this.plugin.settings.apiUrl = value.trim() || DEFAULT_SETTINGS.apiUrl;
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Operator API key")
      .setDesc(
        "Required for OAuth/provider operations. Tokens still stay in the backend; this key only authorizes local admin calls."
      )
      .addText((text) =>
        text
          .setPlaceholder("Optional operator key")
          .setValue(this.plugin.settings.operatorApiKey)
          .onChange(async (value) => {
            this.plugin.settings.operatorApiKey = value.trim();
            await this.plugin.saveSettings();
          })
      );

    containerEl.createEl("h3", { text: "Backend Obsidian vault" });
    containerEl.createEl("p", {
      cls: "alexandria-muted",
      text:
        "Use this Obsidian vault as the canonical Alexandria storage. The bundled Docker Compose setup mounts the same host path into the backend container, so the current vault path can be used directly.",
    });

    new Setting(containerEl)
      .setName("Backend vault path")
      .setDesc(
        "Absolute filesystem path to the Obsidian vault used by backend /obsidian note writes."
      )
      .addText((text) =>
        text
          .setPlaceholder(this.currentVaultPath() || "/Users/me/Desktop/Alexandria")
          .setValue(this.plugin.settings.backendVaultPath || "")
          .onChange(async (value) => {
            this.plugin.settings.backendVaultPath = value.trim();
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Alexandria root in vault")
      .setDesc(
        "Use '.' when this vault root is already the Alexandria vault; use 'Alexandria' to keep notes under an Alexandria/ folder."
      )
      .addText((text) =>
        text
          .setPlaceholder(DEFAULT_SETTINGS.backendAlexandriaRoot)
          .setValue(
            this.plugin.settings.backendAlexandriaRoot ||
              DEFAULT_SETTINGS.backendAlexandriaRoot
          )
          .onChange(async (value) => {
            this.plugin.settings.backendAlexandriaRoot =
              value.trim() || DEFAULT_SETTINGS.backendAlexandriaRoot;
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Apply backend vault")
      .setDesc(
        "Persists the path in the backend, initializes folders, and reindexes notes. Requires the operator key above."
      )
      .addButton((button) =>
        button
          .setButtonText("Use current vault")
          .onClick(async () => {
            await this.useCurrentVault();
          })
      )
      .addButton((button) =>
        button
          .setButtonText("Check backend")
          .onClick(async () => {
            await this.checkBackendVault();
          })
      )
      .addButton((button) =>
        button
          .setButtonText("Apply to backend")
          .setCta()
          .onClick(async () => {
            await this.applyBackendVault();
          })
      );

    new Setting(containerEl)
      .setName("Default project")
      .setDesc("Project metadata sent with librarian asks and created notes.")
      .addText((text) =>
        text
          .setPlaceholder(DEFAULT_SETTINGS.defaultProject)
          .setValue(this.plugin.settings.defaultProject)
          .onChange(async (value) => {
            this.plugin.settings.defaultProject = value.trim();
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Preferred provider id")
      .setDesc("Optional backend provider id for delegated librarian asks. No OAuth token is stored here.")
      .addText((text) =>
        text
          .setPlaceholder("codex-oauth")
          .setValue(this.plugin.settings.preferredProviderId)
          .onChange(async (value) => {
            this.plugin.settings.preferredProviderId = value.trim();
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Preferred profile id")
      .setDesc("Optional backend librarian profile id for delegated asks.")
      .addText((text) =>
        text
          .setPlaceholder("research-critic")
          .setValue(this.plugin.settings.preferredProfileId)
          .onChange(async (value) => {
            this.plugin.settings.preferredProfileId = value.trim();
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Default librarian scope")
      .setDesc("Whole vault is the default librarian mode; active note/selection only add extra context.")
      .addDropdown((dropdown) =>
        dropdown
          .addOption("vault", "Whole vault")
          .addOption("active", "Active note + vault")
          .addOption("selection", "Selection + vault")
          .setValue(this.plugin.settings.contextScope || DEFAULT_SETTINGS.contextScope)
          .onChange(async (value) => {
            this.plugin.settings.contextScope = value;
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Default source count")
      .setDesc("Maximum source notes the librarian can cite from the vault.")
      .addDropdown((dropdown) =>
        dropdown
          .addOption("8", "8")
          .addOption("12", "12")
          .addOption("20", "20")
          .addOption("30", "30")
          .setValue(String(this.plugin.settings.sourceLimit || DEFAULT_SETTINGS.sourceLimit))
          .onChange(async (value) => {
            this.plugin.settings.sourceLimit = Number(value) || DEFAULT_SETTINGS.sourceLimit;
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Default note type filter")
      .setDesc("Optional narrow filter. Leave as all types for normal librarian use.")
      .addDropdown((dropdown) =>
        dropdown
          .addOption("", "All note types")
          .addOption("context", "Context")
          .addOption("memory_compact", "Memory compacts")
          .addOption("skill", "Skills")
          .addOption("prompt", "Prompts")
          .addOption("job_plan", "Job plans")
          .setValue(this.plugin.settings.noteTypeFilter || DEFAULT_SETTINGS.noteTypeFilter)
          .onChange(async (value) => {
            this.plugin.settings.noteTypeFilter = value;
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Use LangGraph approval workflow")
      .setDesc("Ask through backend LangGraph workflow endpoints and approve actions before writes/delegation.")
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.useLangGraphWorkflow)
          .onChange(async (value) => {
            this.plugin.settings.useLangGraphWorkflow = value;
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Show related notes")
      .setDesc("Show graph-related notes in the Alexandria side pane.")
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.showRelatedNotes)
          .onChange(async (value) => {
            this.plugin.settings.showRelatedNotes = value;
            await this.plugin.saveSettings();
          })
      );

    new Setting(containerEl)
      .setName("Auto-save transcripts")
      .setDesc("Default the chat pane to saving transcripts as Obsidian notes.")
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.autoSaveTranscripts)
          .onChange(async (value) => {
            this.plugin.settings.autoSaveTranscripts = value;
            await this.plugin.saveSettings();
          })
      );
  }

  currentVaultPath() {
    const adapter = this.app.vault.adapter;
    return adapter && typeof adapter.basePath === "string" ? adapter.basePath : "";
  }

  backendVaultPath() {
    return (this.plugin.settings.backendVaultPath || this.currentVaultPath()).trim();
  }

  backendAlexandriaRoot() {
    return (
      this.plugin.settings.backendAlexandriaRoot ||
      DEFAULT_SETTINGS.backendAlexandriaRoot
    ).trim() || DEFAULT_SETTINGS.backendAlexandriaRoot;
  }

  async useCurrentVault() {
    const vaultPath = this.currentVaultPath();
    if (!vaultPath) {
      new Notice("Alexandria: current vault path is unavailable on this device.");
      return;
    }
    this.plugin.settings.backendVaultPath = vaultPath;
    this.plugin.settings.backendAlexandriaRoot = ".";
    await this.plugin.saveSettings();
    new Notice("Alexandria: current Obsidian vault selected.");
    this.display();
  }

  async checkBackendVault() {
    try {
      const status = await this.requestJson("GET", "/obsidian/status");
      new Notice(
        `Alexandria backend vault: ${status.vault_path || "unknown"} · root ${
          status.alexandria_root || "unknown"
        }`
      );
    } catch (error) {
      this.showError(error);
    }
  }

  async applyBackendVault() {
    const vaultPath = this.backendVaultPath();
    if (!vaultPath) {
      new Notice("Alexandria: set a backend vault path first.");
      return;
    }
    try {
      const status = await this.requestJson("PUT", "/obsidian/settings/vault", {
        vault_path: vaultPath,
        alexandria_root: this.backendAlexandriaRoot(),
        initialize: true,
        reindex: true,
      });
      new Notice(
        `Alexandria backend vault applied: ${status.vault_path || vaultPath}`
      );
    } catch (error) {
      this.showError(error);
    }
  }

  async requestJson(method, path, payload) {
    const url = `${this.plugin.settings.apiUrl.replace(/\/$/u, "")}${path}`;
    const headers = {};
    if (payload !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    if (this.plugin.settings.operatorApiKey) {
      headers["X-Alexandria-Operator-Key"] = this.plugin.settings.operatorApiKey;
    }
    const response = await requestUrl({
      url,
      method,
      headers,
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
    if (response.status < 200 || response.status >= 300) {
      const detail = this.errorDetail(response);
      throw new Error(
        `Alexandria request failed (${response.status})${
          detail ? `: ${detail}` : ""
        }`
      );
    }
    return response.json;
  }

  errorDetail(response) {
    const payload = response.json || {};
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (typeof payload.message === "string") {
      return payload.message;
    }
    return "";
  }

  showError(error) {
    const message = error instanceof Error ? error.message : String(error);
    new Notice(`Alexandria Librarian: ${message}`);
  }
}
