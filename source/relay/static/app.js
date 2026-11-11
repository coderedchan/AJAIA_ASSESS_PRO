import { Editor, StarterKit, Underline, Placeholder } from "./vendor/tiptap.bundle.js";

const app = document.getElementById("app");
const identity = document.getElementById("identity");
const state = { user: null, users: [], cleanup: null };

const STATUS_LABEL = { draft: "Draft", awaiting: "Awaiting response", returned: "Returned" };
const UPLOAD_HINT = "Import .txt, .md, or .docx files up to 2 MB. Imported content must fit the 1 MB document limit.";

// ------------------------------------------------------------------ helpers

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

async function api(path, { method = "GET", json, form } = {}) {
  const opts = { method, headers: {} };
  if (json !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(json);
  } else if (form) {
    opts.body = form;
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    const err = new Error("The server could not be reached. Check your connection and try again.");
    err.status = 0;
    throw err;
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `The request failed (${res.status}).`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

let toastTimer;
function toast(message, bad = false) {
  const node = document.getElementById("toast");
  node.textContent = message;
  node.classList.toggle("bad", bad);
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.hidden = true), bad ? 6000 : 3000);
}

function initials(name) {
  return name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
}

function when(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function clock(iso) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

// ------------------------------------------------------------------ routing

async function navigate(path, { replace = false } = {}) {
  if (state.cleanup) {
    const ok = await state.cleanup();
    if (ok === false) return;
  }
  history[replace ? "replaceState" : "pushState"]({}, "", path);
  route();
}

document.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-link]");
  if (!link || event.metaKey || event.ctrlKey || event.shiftKey) return;
  event.preventDefault();
  navigate(link.getAttribute("href"));
});
window.addEventListener("popstate", () => route());

async function route() {
  if (state.cleanup) {
    await state.cleanup();
    state.cleanup = null;
  }
  renderIdentity();
  if (!state.user) return renderSignIn();
  const match = location.pathname.match(/^\/d\/([\w-]+)$/);
  if (match) return renderDocument(match[1]);
  return renderDashboard();
}

// ------------------------------------------------------------------ identity (mocked sign-in)

function renderIdentity() {
  identity.replaceChildren();
  if (!state.user) return;
  const select = el(
    "select",
    { class: "field", "aria-label": "Signed in as", onchange: (e) => signIn(e.target.value) },
    state.users.map((u) => el("option", { value: u.id, selected: u.id === state.user.id }, u.name)),
  );
  identity.append(el("span", { class: "who-label" }, "Signed in as"), select);
}

async function signIn(userId) {
  if (state.cleanup) {
    const ok = await state.cleanup();
    if (ok === false) return renderIdentity();
    state.cleanup = null;
  }
  try {
    const data = await api("/api/session", { method: "POST", json: { user_id: userId } });
    state.user = data.user;
    route();
  } catch (err) {
    toast(err.message, true);
  }
}

function renderSignIn() {
  document.title = "Sign in · Relay Docs";
  app.replaceChildren(
    el("div", { class: "page narrow" },
      el("h1", { class: "page-title" }, "Choose a demo account"),
      el("p", { class: "lede" },
        "Choose an account to try the app. You can switch accounts from the top bar."),
      el("div", { class: "people" },
        state.users.map((u) =>
          el("button", { class: "person", onclick: () => signIn(u.id) },
            el("span", { class: "avatar", "aria-hidden": "true" }, initials(u.name)),
            el("span", {}, el("strong", {}, u.name), el("span", {}, `${u.title}, ${u.email}`)),
          ),
        ),
      ),
    ),
  );
}

// ------------------------------------------------------------------ dashboard

async function renderDashboard() {
  document.title = "Documents · Relay Docs";
  app.replaceChildren(el("div", { class: "page" }, el("p", { class: "empty" }, "Loading documents…")));
  let data;
  try {
    data = await api("/api/documents");
  } catch (err) {
    if (err.status === 401) return signedOut();
    app.replaceChildren(el("div", { class: "page" }, el("p", { class: "error-text" }, err.message)));
    return;
  }

  const fileInput = el("input", {
    type: "file", accept: ".txt,.md,.docx", hidden: true, id: "import-file",
    onchange: (e) => importFile(e.target.files[0], e.target),
  });

  app.replaceChildren(
    el("div", { class: "page" },
      el("h1", { class: "page-title" }, "Documents"),
      el("div", { class: "toolbar-row" },
        el("button", { class: "btn btn-ink", onclick: createDocument }, "New document"),
        el("button", { class: "btn", onclick: () => fileInput.click() }, "Import a file"),
        fileInput,
      ),
      el("p", { class: "hint" }, UPLOAD_HINT),

      el("section", { class: "section", "aria-labelledby": "next-h" },
        el("div", { class: "section-head" },
          el("h2", { id: "next-h" }, "Needs your attention"),
          el("span", { class: "count" }, String(data.actions.length)),
        ),
        data.actions.length
          ? el("div", { class: "actions-list" }, data.actions.map(actionCard))
          : el("p", { class: "empty" }, "No requests to review right now."),
      ),

      docSection("owned-h", "My documents", data.owned, "You have not created a document yet. Start a new one or import a file."),
      docSection("shared-h", "Shared with you", data.shared, "No one has shared a document with you yet."),
    ),
  );
}

function actionCard(a) {
  let kicker, text;
  if (a.kind === "respond") {
    kicker = "Review requested";
    text = [`${a.from_name} asked you to: `, el("q", {}, a.instruction)];
  } else if (a.kind === "review") {
    kicker = "Returned to you";
    text = a.note
      ? [`${a.from_name} returned it with a note: `, el("q", {}, a.note)]
      : [`${a.from_name} finished the request `, el("q", {}, a.instruction), " and returned it."];
  } else {
    kicker = "Not sent";
    text = [`Draft request for ${a.handoff_contributor}`, a.instruction ? [": ", el("q", {}, a.instruction)] : ".", ""];
  }
  return el("a", { class: "action", href: `/d/${a.id}`, "data-link": true },
    el("div", { class: "action-kicker" }, kicker),
    el("div", { class: "action-title" }, a.title),
    el("p", { class: "action-text" }, text, el("span", { class: "tag" }, ` · ${when(a.since)}`)),
  );
}

function docSection(id, title, docs, emptyText) {
  return el("section", { class: "section", "aria-labelledby": id },
    el("div", { class: "section-head" },
      el("h2", { id }, title),
      el("span", { class: "count" }, String(docs.length)),
    ),
    docs.length ? docs.map(docRow) : el("p", { class: "empty" }, emptyText),
  );
}

function docRow(d) {
  const owned = d.owner_name === state.user.name;
  let pill = null;
  if (d.handoff_status === "awaiting") {
    const who = d.handoff_contributor === state.user.name ? "you" : d.handoff_contributor;
    pill = el("span", { class: "pill pill-accent" }, `Awaiting ${who}`);
  }
  else if (d.handoff_status === "returned") pill = el("span", { class: "pill pill-accent" }, "Returned");
  else if (d.handoff_status === "draft" && d.handoff_contributor) pill = el("span", { class: "pill" }, "Unsent request");
  return el("a", { class: "doc-row", href: `/d/${d.id}`, "data-link": true },
    el("span", { class: "doc-title" }, d.title),
    el("p", { class: "doc-excerpt" }, d.excerpt || "This document is empty."),
    el("span", { class: "doc-meta" },
      owned ? "" : `By ${d.owner_name} · `,
      `Edited by ${d.updated_by_name}, ${when(d.updated_at)}`),
    el("span", { class: "doc-side" }, pill, el("span", { class: "tag" }, owned ? "Yours" : "Shared with you")),
  );
}

async function createDocument() {
  try {
    const doc = await api("/api/documents", { method: "POST", json: {} });
    navigate(`/d/${doc.id}`);
  } catch (err) {
    toast(err.message, true);
  }
}

async function importFile(file, input) {
  if (!file) return;
  input.value = "";
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (![".txt", ".md", ".docx"].includes(ext)) return toast("Only .txt, .md, and .docx files can be imported.", true);
  if (file.size > 2 * 1024 * 1024) return toast("Files can be up to 2 MB.", true);
  const form = new FormData();
  form.append("file", file);
  toast(`Importing ${file.name}…`);
  try {
    const doc = await api("/api/documents/import", { method: "POST", form });
    toast(`Imported ${file.name} as a new document.`);
    navigate(`/d/${doc.id}`);
  } catch (err) {
    toast(err.message, true);
  }
}

function signedOut() {
  state.user = null;
  route();
}

// ------------------------------------------------------------------ document page

async function renderDocument(id) {
  app.replaceChildren(el("div", { class: "page narrow" }, el("p", { class: "empty" }, "Opening document…")));
  let doc;
  try {
    doc = await api(`/api/documents/${id}`);
  } catch (err) {
    if (err.status === 401) return signedOut();
    document.title = "Not available · Relay Docs";
    app.replaceChildren(
      el("div", { class: "page narrow" },
        el("h1", { class: "page-title" }, "This document is not available"),
        el("p", { class: "lede" },
          err.status === 404
            ? `This link is unavailable for ${state.user.name}. Ask the person who shared it to check your access.`
            : err.message),
        el("a", { class: "btn", href: "/", "data-link": true }, "Back to documents"),
      ),
    );
    return;
  }
  new DocumentView(doc).mount();
}

class DocumentView {
  constructor(doc) {
    this.doc = doc;
    this.dirtyContent = false;
    this.dirtyTitle = false;
    this.saving = false;
    this.queued = false;
    this.timer = null;
    this.shareOpen = false;
    // Text typed into the handoff card, kept outside the DOM so that re-rendering the
    // card (after a focus refresh, for example) never clears it.
    this.formDraft = null;   // { contributor_id, instruction } while the owner edits the draft form
    this.noteDraft = "";     // return note the contributor is writing
    this.busy = false;
  }

  isOwner() {
    return this.doc.owner_id === state.user.id;
  }

  mount() {
    document.title = `${this.doc.title} · Relay Docs`;
    this.saveState = el("span", { class: "save-state", role: "status" }, `Saved ${when(this.doc.updated_at)}`);
    this.shareSlot = el("div", { class: "share-wrap" });
    this.banner = el("div", { class: "banner", hidden: true });
    this.handoffSlot = el("section", { class: "handoff", "aria-label": "Review request" });
    this.facts = el("p", { class: "doc-facts" });
    this.titleInput = el("input", {
      class: "title-input", value: this.doc.title, maxlength: "120", "aria-label": "Document title",
      placeholder: "Untitled document",
      oninput: () => { this.dirtyTitle = true; this.schedule(); },
      onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); this.editor.commands.focus("start"); } },
      onblur: () => {
        if (!this.titleInput.value.trim()) {
          this.titleInput.value = this.doc.title;
          this.dirtyTitle = false;
          toast("The title cannot be empty, so the previous title was kept.", true);
        }
      },
    });
    const editorHost = el("div", { class: "prose" });
    this.tools = el("div", { class: "tools", role: "toolbar", "aria-label": "Formatting" });

    app.replaceChildren(
      el("div", { class: "doc-bar" },
        el("a", { class: "btn btn-quiet", href: "/", "data-link": true }, "← Documents"),
        el("div", { class: "toolbar-row" }, this.saveState, this.shareSlot),
      ),
      this.banner,
      this.handoffSlot,
      el("div", { class: "narrow" }, this.titleInput, this.facts, this.tools, editorHost),
    );

    this.editor = new Editor({
      element: editorHost,
      extensions: [
        StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
        Underline,
        Placeholder.configure({ placeholder: "Start writing…" }),
      ],
      content: this.doc.content_html,
      onUpdate: () => { this.dirtyContent = true; this.schedule(); },
      onTransaction: () => this.syncTools(),
    });

    this.renderTools();
    this.renderFacts();
    this.renderShare();
    this.renderHandoff();

    this.onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") { e.preventDefault(); this.save(); }
    };
    this.onUnload = (e) => {
      if (this.dirtyContent || this.dirtyTitle || this.saving) { e.preventDefault(); e.returnValue = ""; }
    };
    this.onFocus = () => this.refresh();
    document.addEventListener("keydown", this.onKey);
    window.addEventListener("beforeunload", this.onUnload);
    window.addEventListener("focus", this.onFocus);
    this.closeShare = (e) => {
      if (this.shareOpen && !this.shareSlot.contains(e.target)) { this.shareOpen = false; this.renderShare(); }
    };
    document.addEventListener("mousedown", this.closeShare);

    state.cleanup = async () => {
      if (!(await this.flush())) {
        toast("Your latest changes are not saved yet. Resolve the save problem before leaving.", true);
        return false;
      }
      document.removeEventListener("keydown", this.onKey);
      window.removeEventListener("beforeunload", this.onUnload);
      window.removeEventListener("focus", this.onFocus);
      document.removeEventListener("mousedown", this.closeShare);
      this.editor.destroy();
      return true;
    };
  }

  // ---------------------------------------------------------- toolbar

  renderTools() {
    const e = () => this.editor.chain().focus();
    const spec = [
      ["B", "Bold", () => e().toggleBold().run(), () => this.editor.isActive("bold"), "font-weight:700"],
      ["I", "Italic", () => e().toggleItalic().run(), () => this.editor.isActive("italic"), "font-style:italic"],
      ["U", "Underline", () => e().toggleUnderline().run(), () => this.editor.isActive("underline"), "text-decoration:underline"],
      "|",
      ["Text", "Normal text", () => e().setParagraph().run(), () => this.editor.isActive("paragraph")],
      ["H1", "Heading 1", () => e().toggleHeading({ level: 1 }).run(), () => this.editor.isActive("heading", { level: 1 })],
      ["H2", "Heading 2", () => e().toggleHeading({ level: 2 }).run(), () => this.editor.isActive("heading", { level: 2 })],
      "|",
      ["• List", "Bulleted list", () => e().toggleBulletList().run(), () => this.editor.isActive("bulletList")],
      ["1. List", "Numbered list", () => e().toggleOrderedList().run(), () => this.editor.isActive("orderedList")],
      "|",
      ["Undo", "Undo", () => e().undo().run()],
      ["Redo", "Redo", () => e().redo().run()],
    ];
    this.toolButtons = [];
    for (const item of spec) {
      if (item === "|") { this.tools.append(el("span", { class: "tool-sep", "aria-hidden": "true" })); continue; }
      const [label, name, run, active, style] = item;
      const button = el("button", {
        class: "tool", type: "button", title: name, "aria-label": name, style,
        onmousedown: (ev) => ev.preventDefault(),
        onclick: run,
      }, label);
      if (active) this.toolButtons.push([button, active]);
      this.tools.append(button);
    }
    this.syncTools();
  }

  syncTools() {
    for (const [button, active] of this.toolButtons || []) button.setAttribute("aria-pressed", String(active()));
  }

  renderFacts() {
    const names = this.doc.shared_with.map((u) => u.name);
    const ownerText = this.isOwner() ? "Created by you" : `Created by ${this.doc.owner.name}`;
    const sharedText = names.length ? `Shared with ${names.join(", ")}` : "Not shared";
    const source = this.doc.source_filename ? ` · Imported from ${this.doc.source_filename}` : "";
    this.facts.textContent = `${ownerText} · ${sharedText}${source}`;
  }

  // ---------------------------------------------------------- saving

  schedule() {
    this.setSave("Unsaved changes");
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.save(), 900);
  }

  setSave(text, bad = false, action = null) {
    this.saveState.replaceChildren(text);
    this.saveState.classList.toggle("bad", bad);
    if (action) this.saveState.append(" ", el("button", { class: "btn btn-quiet", onclick: action[1] }, action[0]));
  }

  async save(force = false) {
    clearTimeout(this.timer);
    if (this.saving) { this.queued = true; return this.pending; }
    if (!this.dirtyContent && !this.dirtyTitle) return;
    if (this.dirtyTitle && !this.titleInput.value.trim()) {
      this.dirtyTitle = false;
      if (!this.dirtyContent) return;
    }
    const payload = { base_version: this.doc.version };
    const sentTitle = this.dirtyTitle;
    const sentContent = this.dirtyContent;
    if (sentTitle) payload.title = this.titleInput.value;
    if (sentContent) payload.content_html = this.editor.getHTML();
    if (force) payload.force = true;
    this.dirtyTitle = this.dirtyContent = false;
    this.saving = true;
    this.setSave("Saving…");
    this.pending = (async () => {
      try {
        const saved = await api(`/api/documents/${this.doc.id}`, { method: "PATCH", json: payload });
        this.doc.version = saved.version;
        this.doc.title = saved.title;
        this.doc.updated_at = saved.updated_at;
        document.title = `${saved.title} · Relay Docs`;
        this.banner.hidden = true;
        this.setSave(`Saved at ${clock(saved.updated_at)}`);
      } catch (err) {
        this.dirtyTitle ||= sentTitle;
        this.dirtyContent ||= sentContent;
        if (err.status === 409 && err.data?.latest) this.showConflict(err.data.latest);
        else if (err.status === 401) signedOut();
        else this.setSave(`Not saved. ${err.message}`, true, ["Retry", () => this.save()]);
      } finally {
        this.saving = false;
      }
      if (this.queued) { this.queued = false; await this.save(); }
    })();
    return this.pending;
  }

  hasUnsaved() {
    return this.dirtyContent || this.dirtyTitle;
  }

  /** Save anything pending and wait for in-flight saves. Resolves to true only when
   * every local change is stored on the server. */
  async flush() {
    clearTimeout(this.timer);
    if (this.pending) await this.pending;
    if (this.hasUnsaved()) await this.save();
    if (this.pending) await this.pending;
    return !this.hasUnsaved() && !this.saving;
  }

  showConflict(latest) {
    this.setSave("Not saved: newer version exists", true);
    this.banner.replaceChildren(
      el("span", {}, `${latest.updated_by_name} saved a newer version while you were editing. Your changes are still in the editor.`),
      el("span", { class: "toolbar-row" },
        el("button", { class: "btn", onclick: () => this.loadLatest(latest) }, "Load their version"),
        el("button", { class: "btn btn-ink", onclick: () => this.save(true) }, "Keep my version"),
      ),
    );
    this.banner.hidden = false;
  }

  loadLatest(latest) {
    this.dirtyContent = this.dirtyTitle = false;
    this.applyRemote(latest);
    this.banner.hidden = true;
    this.setSave(`Loaded the version saved by ${latest.updated_by_name}`);
  }

  applyRemote(latest) {
    const contentChanged = latest.version !== this.doc.version;
    const metaChanged =
      JSON.stringify([latest.handoff, latest.shared_with]) !==
      JSON.stringify([this.doc.handoff, this.doc.shared_with]);
    Object.assign(this.doc, latest);
    if (contentChanged) {
      this.editor.commands.setContent(latest.content_html, false);
      this.titleInput.value = latest.title;
    }
    this.renderFacts();
    if (metaChanged) {
      this.renderShare();
      this.renderHandoff();
    }
  }

  async refresh() {
    if (this.dirtyContent || this.dirtyTitle || this.saving) return;
    try {
      const latest = await api(`/api/documents/${this.doc.id}`);
      if (this.dirtyContent || this.dirtyTitle || this.saving) return;
      this.applyRemote(latest);
    } catch (err) {
      if (err.status === 404) route();
    }
  }

  async reloadMeta() {
    const latest = await api(`/api/documents/${this.doc.id}`);
    this.doc.shared_with = latest.shared_with;
    this.doc.handoff = latest.handoff;
    this.renderFacts();
    this.renderShare();
    this.renderHandoff();
  }

  // ---------------------------------------------------------- sharing

  renderShare() {
    const toggle = el("button", {
      class: "btn", "aria-expanded": String(this.shareOpen),
      onclick: () => { this.shareOpen = !this.shareOpen; this.renderShare(); },
    }, this.isOwner() ? "Share" : "People");
    this.shareSlot.replaceChildren(toggle);
    if (!this.shareOpen) return;

    const owner = this.doc.owner;
    const list = el("ul", { class: "access-list" },
      el("li", {},
        el("span", { class: "avatar", "aria-hidden": "true" }, initials(owner.name)),
        el("span", { class: "who" }, owner.name), el("span", { class: "role" }, "Owner")),
      this.doc.shared_with.map((u) =>
        el("li", {},
          el("span", { class: "avatar", "aria-hidden": "true" }, initials(u.name)),
          el("span", { class: "who" }, u.name),
          this.isOwner()
            ? el("button", { class: "btn btn-danger-quiet", onclick: () => this.unshare(u) }, "Remove")
            : el("span", { class: "role" }, "Can edit")),
      ),
    );
    const panel = el("div", { class: "share-panel", role: "dialog", "aria-label": "People with access" },
      el("h3", {}, "People with access"),
      el("p", { class: "hint" },
        this.isOwner()
          ? "People added here can edit. You manage access."
          : `${owner.name} manages access.`),
      list,
    );
    if (this.isOwner()) {
      const taken = new Set([owner.id, ...this.doc.shared_with.map((u) => u.id)]);
      const options = state.users.filter((u) => !taken.has(u.id));
      if (options.length) {
        const select = el("select", { class: "field", "aria-label": "Person to share with" },
          options.map((u) => el("option", { value: u.id }, `${u.name} (${u.email})`)));
        panel.append(
          el("label", { class: "label" }, "Add a person"),
          el("div", { class: "add-person" }, select,
            el("button", { class: "btn btn-ink", onclick: () => this.share(select.value) }, "Share")),
        );
      } else {
        panel.append(el("p", { class: "hint" }, "Everyone in the workspace already has access."));
      }
    }
    this.shareSlot.append(panel);
  }

  async share(userId) {
    try {
      await api(`/api/documents/${this.doc.id}/access`, { method: "POST", json: { user_id: userId } });
      const person = state.users.find((u) => u.id === userId);
      toast(`Shared with ${person.name}. They can now open and edit this document.`);
      await this.reloadMeta();
    } catch (err) {
      toast(err.message, true);
    }
  }

  async unshare(user) {
    try {
      await api(`/api/documents/${this.doc.id}/access/${user.id}`, { method: "DELETE" });
      const waiting = this.doc.handoff.status === "awaiting" && this.doc.handoff.contributor_id === user.id;
      toast(waiting
        ? `${user.name} removed. The review request is back in Draft.`
        : `${user.name} no longer has access.`);
      await this.reloadMeta();
    } catch (err) {
      toast(err.message, true);
    }
  }

  // ---------------------------------------------------------- handoff card

  renderHandoff() {
    const h = this.doc.handoff;
    const me = state.user.id;
    const owner = this.doc.owner;
    const isOwner = this.isOwner();
    const isContributor = h.contributor_id === me;
    const card = this.handoffSlot;
    const accentPill = h.status !== "draft";

    const head = el("div", { class: "handoff-head" },
      el("h2", {}, "Review request"),
      el("span", { class: `pill ${accentPill ? "pill-accent" : ""}` }, STATUS_LABEL[h.status]),
    );

    const senderFact = el("div", { class: "fact" },
      el("div", { class: "label" }, "From"),
      el("div", { class: "value" }, isOwner ? `${owner.name} (you)` : owner.name));

    const body = [];
    const buttons = [];
    let message = null;

    const editable = isOwner && h.status === "draft";
    if (editable) {
      body.push(this.handoffForm(buttons));
    } else {
      body.push(el("div", { class: "handoff-grid" },
        senderFact,
        el("div", { class: "fact" },
          el("div", { class: "label" }, "Sent to"),
          el("div", { class: "value" }, h.contributor_name ? (isContributor ? `${h.contributor_name} (you)` : h.contributor_name) : "Not chosen")),
        el("div", { class: "fact" },
          el("div", { class: "label" }, "Updated"),
          el("div", { class: "value" }, h.updated_at ? when(h.updated_at) : "Not started")),
        el("div", { class: "fact wide" },
          el("div", { class: "label" }, "What needs checking?"),
          el("div", { class: "value" }, h.instruction ? el("q", {}, h.instruction) : "None yet")),
      ));

      if (h.status === "awaiting" && isOwner) {
        message = `Waiting for ${h.contributor_name}.`;
        buttons.push(el("button", { class: "btn btn-quiet", onclick: () => this.handoffAction("withdraw") }, "Cancel request"));
      } else if (h.status === "awaiting" && isContributor) {
        const note = el("textarea", {
          class: "field", rows: "2", maxlength: "500", id: "return-note",
          placeholder: "For example: Dates confirmed with the Leeds and York managers. Week 3 moved to week 4.",
          oninput: (e) => { this.noteDraft = e.target.value; },
        });
        note.value = this.noteDraft;
        body.push(el("div", { style: "margin-top:16px" },
          el("label", { class: "label", for: "return-note" }, `Note for ${owner.name} (optional)`), note));
        message = `Make your changes, then send it back to ${owner.name}.`;
        buttons.push(el("button", {
          class: "btn btn-accent",
          onclick: () => this.handoffAction("return", { note: note.value }),
        }, `Send back to ${owner.name}`));
      } else if (h.status === "awaiting") {
        message = `Waiting for ${h.contributor_name}.`;
      } else if (h.status === "returned" && isOwner) {
        message = h.return_note
          ? [`${h.contributor_name} returned the document with a note: `, el("q", {}, h.return_note)]
          : `${h.contributor_name} sent this back for you to review.`;
        buttons.push(el("button", { class: "btn btn-accent", onclick: () => this.handoffAction("close") }, "Finish review"));
      } else if (h.status === "returned") {
        message = isContributor
          ? `You returned this document to ${owner.name}.`
          : `${h.contributor_name} returned this document to ${owner.name}.`;
        if (isContributor && h.return_note) message = [message, " Your note: ", el("q", {}, h.return_note)];
      } else {
        message = `No review requested yet. ${owner.name} can send one.`;
      }
    }

    const history = h.events.length
      ? el("details", { class: "history" },
          el("summary", {}, "Recent activity"),
          el("ol", {}, h.events.map((e) => el("li", {}, describeEvent(e), ` · ${when(e.created_at)}`))))
      : null;

    // replaceChildren() would print a null argument as the text "null", so drop empty parts.
    card.replaceChildren(...[
      head,
      ...body,
      message ? el("p", { class: "handoff-message" }, message) : null,
      el("div", { class: "handoff-foot" },
        buttons.length ? el("div", { class: "toolbar-row" }, buttons) : null,
      ),
      history,
    ].filter(Boolean));
  }

  handoffForm(buttons) {
    const h = this.doc.handoff;
    const people = this.doc.shared_with;
    if (!people.length) {
      buttons.push(el("button", {
        class: "btn", onclick: (e) => { e.stopPropagation(); this.shareOpen = true; this.renderShare(); },
      }, "Share document"));
      return el("div", {},
        el("p", { class: "handoff-message" }, "Add someone in Share, then send them a review request."));
    }
    const draft = this.formDraft || { contributor_id: h.contributor_id, instruction: h.instruction || "" };
    const select = el("select", { class: "field", id: "handoff-to" },
      el("option", { value: "" }, "Choose a person"),
      people.map((u) => el("option", { value: u.id, selected: u.id === draft.contributor_id }, u.name)));
    const instruction = el("input", {
      class: "field", id: "handoff-instruction", maxlength: "200",
      placeholder: "For example: Review the pricing paragraph.",
    });
    instruction.value = draft.instruction;
    const remember = () => { this.formDraft = { contributor_id: select.value || null, instruction: instruction.value }; };
    select.addEventListener("change", remember);
    instruction.addEventListener("input", remember);
    const send = el("button", { class: "btn btn-accent" }, "Send request");
    const label = () => {
      const person = people.find((u) => u.id === select.value);
      send.textContent = person ? `Send to ${person.name}` : "Send request";
    };
    select.addEventListener("change", label);
    label();
    const values = () => ({ contributor_id: select.value || null, instruction: instruction.value });
    send.addEventListener("click", () => this.handoffAction("send", values()));
    buttons.push(
      el("button", { class: "btn", onclick: () => this.saveDraft(values()) }, "Save draft"),
      send,
    );
    return el("div", {},
      el("div", { class: "handoff-form" },
        el("div", {}, el("label", { class: "label", for: "handoff-to" }, "Send to"), select),
        el("div", {}, el("label", { class: "label", for: "handoff-instruction" }, "What needs checking?"), instruction),
      ),
    );
  }

  async saveDraft(values) {
    try {
      this.doc.handoff = { ...(await api(`/api/documents/${this.doc.id}/handoff`, { method: "PUT", json: values })) };
      this.formDraft = null;
      this.renderHandoff();
      toast("Request saved as a draft.");
    } catch (err) {
      toast(err.message, true);
    }
  }

  async handoffAction(action, payload = {}) {
    const messages = {
      send: () => `Sent to ${this.doc.handoff.contributor_name}.`,
      withdraw: () => "Request cancelled. Saved as a draft.",
      return: () => `Sent back to ${this.doc.owner.name}.`,
      close: () => "Review finished.",
    };
    if (this.busy) return;
    this.busy = true;
    try {
      // A handoff tells the other person the document is ready, so it must not go
      // out while edits are still unsaved. If saving fails, nothing changes.
      if (!(await this.flush())) {
        toast("Save your latest edits before sending this request. " +
              "Resolve the save message next to the Share button, then try again.", true);
        return;
      }
      this.doc.handoff = await api(`/api/documents/${this.doc.id}/handoff/${action}`, { method: "POST", json: payload });
      if (action === "send") this.formDraft = null;
      if (action === "return") this.noteDraft = "";
      this.renderHandoff();
      toast(messages[action]());
    } catch (err) {
      toast(err.message, true);
      if (err.status === 409 || err.status === 403) this.reloadMeta().catch(() => {});
    } finally {
      this.busy = false;
    }
  }
}

function describeEvent(e) {
  switch (e.action) {
    case "shared": return `${e.actor_name} shared the document with ${e.detail}.`;
    case "unshared": return `${e.actor_name} removed access for ${e.detail}.`;
    case "sent": return `${e.actor_name} sent a review request ${e.detail}`;
    case "withdrawn": return e.detail ? `${e.actor_name} cancelled the request because ${e.detail}.` : `${e.actor_name} cancelled the request.`;
    case "returned": return e.detail ? `${e.actor_name} returned it with a note: “${e.detail}”` : `${e.actor_name} sent it back.`;
    case "closed": return `${e.actor_name} finished the review.`;
    default: return `${e.actor_name}: ${e.action}`;
  }
}

// ------------------------------------------------------------------ start

(async function start() {
  try {
    const data = await api("/api/session");
    state.user = data.user;
    state.users = data.users;
  } catch (err) {
    app.replaceChildren(el("div", { class: "page" }, el("p", { class: "error-text" }, err.message)));
    return;
  }
  route();
})();
