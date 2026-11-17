// The device's web console. Plain JavaScript; talks to /api on this device only.
"use strict";

const $ = (id) => document.getElementById(id);
const KEY_NAMES = {
  openai: "OpenAI", anthropic: "Anthropic", groq: "Groq", openrouter: "OpenRouter",
  openai_compatible: "Gemini / other", elevenlabs: "ElevenLabs", deepgram: "Deepgram", search: "Web search",
};
let state = { active: "", characters: [], settings: null, editing: "" };

async function api(method, path, body, raw) {
  const opts = { method, headers: { "X-Companion": "1" }, credentials: "same-origin" };
  if (raw !== undefined) { opts.body = raw; }
  else if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  if (r.status === 401 && path !== "/api/login") { showLogin(false); throw new Error("please log in"); }
  const type = r.headers.get("Content-Type") || "";
  const data = type.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(typeof data === "string" ? data : JSON.stringify(data));
  return data;
}

function text(el, value) { el.textContent = value == null ? "" : String(value); }

// ----- login
async function start() {
  const hello = await api("GET", "/api/hello");
  if (hello.needs_setup) return showLogin(true);
  if (!hello.logged_in) return showLogin(false);
  enter();
}

function showLogin(setup) {
  for (const s of document.querySelectorAll(".tab")) s.hidden = true;
  $("tabs").hidden = true;
  $("login").hidden = false;
  text($("login-title"), setup ? "Set a password" : "Log in");
  text($("login-help"), setup ? "Choose a password for this device's settings page (8 or more characters). Anyone on your home network who knows it can change the device." : "");
  $("login-form").dataset.setup = setup ? "1" : "";
  $("login-password").autocomplete = setup ? "new-password" : "current-password";
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const setup = $("login-form").dataset.setup === "1";
  try {
    await api("POST", setup ? "/api/setup" : "/api/login", { password: $("login-password").value });
    $("login-password").value = "";
    text($("login-error"), "");
    enter();
  } catch (err) { text($("login-error"), err.message); }
});

function enter() {
  $("login").hidden = true;
  $("tabs").hidden = false;
  show("home");
  refreshCharacters();
  loadSettings();
  listen();
}

// ----- tabs
function show(tab) {
  for (const s of document.querySelectorAll(".tab")) s.hidden = s.id !== tab;
  for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("on", b.dataset.tab === tab);
  if (tab === "memory") loadMemory();
}
for (const b of document.querySelectorAll("#tabs button")) b.addEventListener("click", () => show(b.dataset.tab));

// ----- live events
let source = null;
function listen() {
  if (source) source.close();
  source = new EventSource("/api/events");
  source.onmessage = (m) => onEvent(JSON.parse(m.data));
  api("GET", "/api/status").then(setStatus).catch(() => {});
}

function addLog(who, words, cls) {
  const li = document.createElement("li");
  if (cls) li.className = cls;
  const w = document.createElement("span"); w.className = "who"; text(w, who);
  li.append(w, document.createTextNode(words));
  $("log").prepend(li);
  while ($("log").children.length > 100) $("log").lastChild.remove();
}

function onEvent(e) {
  if (e.kind === "state") text($("home-state"), e.state);
  else if (e.kind === "heard") addLog("You:", e.text);
  else if (e.kind === "replied" && e.text) addLog("Character:", e.text + (e.interrupted ? " (interrupted)" : ""));
  else if (e.kind === "error" || e.kind === "stage_error") addLog("Problem:", e.message, "error");
  else if (e.kind === "timer") addLog("Timer:", e.label + (e.did ? " " + e.did : " set"));
  else if (e.kind === "character") refreshCharacters();
  else if (e.kind === "button") text($("btn-listen"), e.did === "listen on" ? "Stop listening" : "Start listening");
}

function setStatus(s) {
  text($("home-state"), s.state);
  text($("btn-listen"), s.listening ? "Stop listening" : "Start listening");
}

$("btn-listen").addEventListener("click", () => api("POST", "/api/button").then(setStatus).catch((e) => addLog("Problem:", e.message, "error")));
$("btn-interrupt").addEventListener("click", () => api("POST", "/api/interrupt").catch(() => {}));
$("say-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const words = $("say-text").value.trim();
  if (!words) return;
  $("say-text").value = "";
  try { await api("POST", "/api/say", { text: words }); } catch (err) { addLog("Problem:", err.message, "error"); }
});

// ----- characters
async function refreshCharacters() {
  const data = await api("GET", "/api/characters");
  state.active = data.active;
  state.characters = data.characters;
  const list = $("char-list");
  list.replaceChildren();
  for (const c of data.characters) {
    const li = document.createElement("li");
    if (c.id === data.active) li.className = "active";
    if (c.preview) { const img = document.createElement("img"); img.src = "/api/characters/" + c.id + "/preview"; img.alt = ""; li.append(img); }
    const name = document.createElement("div"); text(name, c.name); li.append(name);
    const cannot = Object.entries(c.capabilities || {}).filter(([, v]) => !v).map(([k]) => k.replace("_", " "));
    if (cannot.length) { const n = document.createElement("small"); text(n, "cannot: " + cannot.join(", ")); li.append(n); }
    const actions = [["Use", () => api("POST", "/api/characters/" + c.id + "/activate").then(refreshCharacters)],
                     ["Edit", () => editCharacter(c)],
                     ["Save copy", () => { location.href = "/api/characters/" + c.id + "/export"; }],
                     ["Remove", () => confirm("Remove " + c.name + "? Its memories stay until you clear them.") &&
                                       api("DELETE", "/api/characters/" + c.id).then(refreshCharacters)]];
    for (const [label, fn] of actions) {
      const b = document.createElement("button"); text(b, label);
      b.addEventListener("click", () => Promise.resolve(fn()).catch((e) => text($("char-error"), e.message)));
      li.append(b);
    }
    list.append(li);
  }
  const active = data.characters.find((c) => c.id === data.active);
  text($("home-name"), active ? active.name : "No character yet");
  text($("mem-name"), active ? active.name : "");
  $("home-preview").hidden = !(active && active.preview);
  if (active && active.preview) $("home-preview").src = "/api/characters/" + active.id + "/preview?" + Date.now();
}

$("char-file").addEventListener("change", async () => {
  const file = $("char-file").files[0];
  if (!file) return;
  text($("char-error"), "Checking and installing…");
  try {
    const q = $("char-replace").checked ? "?replace=1" : "";
    await api("POST", "/api/characters" + q, undefined, file);
    text($("char-error"), "");
    refreshCharacters();
  } catch (err) { text($("char-error"), err.message); }
  $("char-file").value = "";
});

async function editCharacter(c) {
  const data = await api("GET", "/api/characters/" + c.id + "/persona");
  state.editing = c.id;
  text($("edit-name"), c.name);
  $("edit-persona").value = data.persona;
  $("edit-voice").value = (data.device && data.device.voice) || "";
  $("char-edit").hidden = false;
  $("char-edit").scrollIntoView();
}

$("btn-save-persona").addEventListener("click", async () => {
  try {
    await api("PUT", "/api/characters/" + state.editing + "/persona", { persona: $("edit-persona").value, voice: $("edit-voice").value });
    text($("edit-msg"), "Saved.");
  } catch (err) { text($("edit-msg"), err.message); }
});

$("btn-clone").addEventListener("click", async () => {
  const file = $("voice-file").files[0];
  if (!file) return text($("edit-msg"), "Choose a WAV recording first.");
  text($("edit-msg"), "Cloning…");
  try {
    const r = await api("POST", "/api/characters/" + state.editing + "/voice", undefined, file);
    $("edit-voice").value = r.voice;
    text($("edit-msg"), "Done: this character now speaks with the cloned voice.");
  } catch (err) { text($("edit-msg"), err.message); }
});

// ----- memory
async function loadMemory() {
  if (!state.active) return;
  const m = await api("GET", "/api/memory/" + state.active);
  $("mem-notes").value = m.notes;
  const list = $("mem-history");
  list.replaceChildren();
  for (const t of m.history.slice().reverse()) {
    const li = document.createElement("li");
    text(li, "You: " + t.user + "  —  " + t.reply + (t.interrupted ? " (interrupted)" : ""));
    list.append(li);
  }
}
$("btn-save-notes").addEventListener("click", () => api("PUT", "/api/memory/" + state.active, { notes: $("mem-notes").value }).then(loadMemory));
$("btn-clear-memory").addEventListener("click", () => confirm("Forget the whole conversation and all notes for this character?") &&
  api("DELETE", "/api/memory/" + state.active).then(loadMemory));

// ----- services and keys
const FIELDS = { llm: ["provider", "model", "base_url", "effort", "max_tokens"], stt: ["provider", "model", "base_url"],
                 tts: ["provider", "model", "voice", "base_url"] };

async function loadSettings() {
  const s = state.settings = await api("GET", "/api/settings");
  for (const [group, names] of Object.entries(FIELDS)) {
    for (const n of names) { const el = $(group + "-" + n); if (el) el.value = s[group][n] ?? ""; }
  }
  $("dev-volume").value = s.volume;
  $("dev-mode").value = s.listening.mode;
  $("dev-end_silence").value = s.listening.end_silence;
  $("dev-memory").checked = !!s.conversation.memory;
  renderKeys(await api("GET", "/api/keys"));
}

function renderKeys(status) {
  const box = $("keys");
  box.replaceChildren();
  for (const [name, set] of Object.entries(status)) {
    const row = document.createElement("div"); row.className = "key";
    const label = document.createElement("span"); text(label, (KEY_NAMES[name] || name) + (set ? " (set)" : ""));
    const input = document.createElement("input"); input.type = "password"; input.autocomplete = "off";
    input.placeholder = set ? "replace key" : "paste key";
    const save = document.createElement("button"); text(save, "Save");
    save.addEventListener("click", async () => { await api("PUT", "/api/keys/" + name, { value: input.value }).then(renderKeys); });
    row.append(label, input, save);
    if (set) {
      const clear = document.createElement("button"); clear.className = "danger"; text(clear, "Remove");
      clear.addEventListener("click", () => api("PUT", "/api/keys/" + name, { value: "" }).then(renderKeys));
      row.append(clear);
    }
    box.append(row);
  }
}

$("btn-save-services").addEventListener("click", async () => {
  const changes = {};
  for (const [group, names] of Object.entries(FIELDS)) {
    changes[group] = {};
    for (const n of names) {
      const el = $(group + "-" + n);
      if (el) changes[group][n] = el.type === "number" ? Number(el.value) : el.value.trim();
    }
  }
  try { await api("PUT", "/api/settings", changes); text($("services-msg"), "Saved."); }
  catch (err) { text($("services-msg"), err.message); }
});

for (const b of document.querySelectorAll("[data-test]")) {
  b.addEventListener("click", async () => {
    const out = $("test-" + b.dataset.test);
    text(out, "Testing…");
    try { const r = await api("POST", "/api/test/" + b.dataset.test); text(out, (r.ok ? "OK: " : "Failed: ") + r.message); }
    catch (err) { text(out, "Failed: " + err.message); }
  });
}

$("btn-models").addEventListener("click", async () => {
  const r = await api("GET", "/api/models");
  const list = $("llm-models");
  list.replaceChildren();
  for (const m of r.models) { const o = document.createElement("option"); o.value = m; list.append(o); }
  text($("test-llm"), r.ok ? r.models.length + " models found" : "Failed: " + r.message);
});

// ----- device
$("btn-save-device").addEventListener("click", async () => {
  try {
    await api("PUT", "/api/settings", {
      volume: Number($("dev-volume").value),
      listening: { mode: $("dev-mode").value, end_silence: Number($("dev-end_silence").value) },
      conversation: { memory: $("dev-memory").checked },
    });
    text($("device-msg"), "Saved.");
  } catch (err) { text($("device-msg"), err.message); }
});

$("pw-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await api("POST", "/api/password", { old: $("pw-old").value, new: $("pw-new").value }); text($("pw-msg"), "Changed."); }
  catch (err) { text($("pw-msg"), err.message); }
  $("pw-old").value = ""; $("pw-new").value = "";
});

$("btn-logout").addEventListener("click", async () => { await api("POST", "/api/logout"); if (source) source.close(); showLogin(false); });

start().catch((err) => { document.body.prepend(Object.assign(document.createElement("p"), { className: "error", textContent: err.message })); });
