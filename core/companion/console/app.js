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
  if (tab === "device") loadWifi().catch((e) => text($("wifi-status"), e.message));
}
for (const b of document.querySelectorAll("#tabs button")) b.addEventListener("click", () => show(b.dataset.tab));

// ----- live events
let source = null;
function listen() {
  if (source) source.close();
  source = new EventSource("/api/events");
  source.onmessage = (m) => onEvent(JSON.parse(m.data));
  api("GET", "/api/status").then((s) => { setStatus(s); syncTimezone(s); }).catch(() => {});
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
  else if (e.kind === "searching") addLog("Searching:", e.query);
  else if (e.kind === "memory" || e.kind === "replied") api("GET", "/api/status").then(setStatus).catch(() => {});
  else if (e.kind === "character") { refreshCharacters(); api("GET", "/api/status").then(setStatus).catch(() => {}); }
  else if (e.kind === "button") text($("btn-listen"), e.did === "listen on" ? "Stop listening" : "Start listening");
}

function setStatus(s) {
  text($("home-state"), s.state);
  text($("btn-listen"), s.listening ? "Stop listening" : "Start listening");
  if (s.providers) showSteps(s);
  if (s.timezone !== undefined) text($("tz-device"), s.timezone || "not set");
}

// What a new owner still has to do, with links to where it is done.
function showSteps(s) {
  const keyFor = { openai: "openai", anthropic: "anthropic", groq: "groq", openrouter: "openrouter",
                   gemini: "openai_compatible", custom: "openai_compatible", elevenlabs: "elevenlabs" };
  const hasKey = (p) => !p || p === "local" || !keyFor[p] || s.keys[keyFor[p]];
  const steps = [
    ["Choose a language model and add its key", s.providers.llm && hasKey(s.providers.llm), "services"],
    ["Choose a voice and add its key", s.providers.tts && hasKey(s.providers.tts), "services"],
    ["Add a character", s.characters > 0, "characters"],
    ["Press the button on the device (or Start listening) and say hello", s.characters > 0 && s.providers.llm && s.providers.tts, "home"],
  ];
  const list = $("start-steps");
  list.replaceChildren();
  for (const [label, done, tab] of steps) {
    const li = document.createElement("li");
    if (done) li.className = "done";
    const a = document.createElement("a"); text(a, label);
    a.addEventListener("click", () => show(tab));
    li.append(a);
    list.append(li);
  }
  $("start").hidden = steps.every(([, done]) => done);
}

// On first setup, give the device this phone's time zone, so alarms ring at the right time.
async function syncTimezone(s) {
  const phone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  text($("tz-phone"), phone);
  let asked = false;
  try { asked = localStorage.getItem("tz-set") === "1"; } catch (e) {}
  $("btn-tz").hidden = !s.can_set_timezone;
  if (!asked && phone && s.can_set_timezone && s.timezone !== phone) {
    try { const r = await api("POST", "/api/timezone", { zone: phone }); text($("tz-device"), r.timezone); } catch (e) {}
    try { localStorage.setItem("tz-set", "1"); } catch (e) {}
  }
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
  for (const q of PERSONA_QUESTIONS) $("pf-" + q).value = (data.form && data.form[q]) || "";
  if (!$("pf-name").value) $("pf-name").value = c.name;
  $("char-edit").hidden = false;
  loadFeelings(c.id);
  $("char-edit").scrollIntoView();
}

// Which of a character's own expressions shows each feeling (Live2D-format models that have some).
async function loadFeelings(cid) {
  const data = await api("GET", "/api/characters/" + cid + "/emotions");
  const list = $("feelings-list");
  list.replaceChildren();
  $("edit-feelings").hidden = !data.expressions.length;
  text($("feelings-msg"), "");
  for (const emotion of data.emotions) {
    const label = document.createElement("label");
    label.append(emotion.charAt(0).toUpperCase() + emotion.slice(1) + " ");
    const select = document.createElement("select");
    select.dataset.emotion = emotion;
    const none = document.createElement("option");
    none.value = "";
    none.textContent = "(movement only)";
    select.append(none);
    for (const name of data.expressions) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      select.append(option);
    }
    select.value = data.map[emotion] || "";
    label.append(select);
    list.append(label);
  }
}

$("btn-save-feelings").addEventListener("click", async () => {
  const map = {};
  for (const select of $("feelings-list").querySelectorAll("select")) map[select.dataset.emotion] = select.value;
  try {
    await api("PUT", "/api/characters/" + state.editing + "/emotions", { map });
    text($("feelings-msg"), "Saved.");
  } catch (err) { text($("feelings-msg"), err.message); }
});

const PERSONA_QUESTIONS = ["name", "personality", "story", "relationship", "likes", "dislikes", "speaking", "never", "greeting"];

$("btn-write-persona").addEventListener("click", async () => {
  const form = {};
  for (const q of PERSONA_QUESTIONS) form[q] = $("pf-" + q).value;
  try {
    const r = await api("PUT", "/api/characters/" + state.editing + "/persona", { form });
    $("edit-persona").value = r.persona;
    text($("edit-msg"), "Written and saved. Check it below; you can still edit it freely.");
  } catch (err) { text($("edit-msg"), err.message); }
});

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
  showEpisodes(m);
  const list = $("mem-history");
  list.replaceChildren();
  for (const t of m.history.slice().reverse()) {
    const li = document.createElement("li");
    text(li, "You: " + t.user + "  —  " + t.reply + (t.interrupted ? " (interrupted)" : ""));
    list.append(li);
  }
}

function showEpisodes(m) {
  const list = $("mem-episodes");
  list.replaceChildren();
  text($("mem-episode-count"), m.episode_count === 0 ? "None yet." :
    m.episode_count > m.episodes.length ? "The newest " + m.episodes.length + " of " + m.episode_count + "." : "");
  for (const e of m.episodes) {
    const li = document.createElement("li");
    const when = document.createElement("span");
    when.className = "who";
    text(when, e.when);
    const words = document.createElement("span");
    text(words, e.summary);
    const edit = button("Change", async () => {
      const box = document.createElement("textarea");
      box.rows = 3;
      box.maxLength = 600;
      box.value = e.summary;
      const save = button("Save", () => api("PUT", episodePath(e), { summary: box.value }).then(loadMemory)
        .catch((err) => alert(err.message)));
      li.replaceChildren(when, box, save, button("Cancel", loadMemory));
      box.focus();
    });
    const forget = button("Forget", () => confirm("Forget this conversation's summary?") &&
      api("DELETE", episodePath(e)).then(loadMemory).catch((err) => alert(err.message)), "danger");
    li.append(when, words, " ", edit, " ", forget);
    list.append(li);
  }
}

function episodePath(e) { return "/api/memory/" + state.active + "/episodes/" + e.id; }

function button(label, onClick, className) {
  const b = document.createElement("button");
  text(b, label);
  b.className = "small" + (className ? " " + className : "");
  b.addEventListener("click", onClick);
  return b;
}

$("btn-save-notes").addEventListener("click", () => api("PUT", "/api/memory/" + state.active, { notes: $("mem-notes").value }).then(loadMemory));
$("btn-clear-memory").addEventListener("click", () => confirm("Forget the whole conversation, all notes and all summaries for this character?") &&
  api("DELETE", "/api/memory/" + state.active).then(loadMemory));

// ----- services and keys
const FIELDS = { llm: ["provider", "model", "base_url", "effort", "max_tokens"], stt: ["provider", "model", "base_url"],
                 tts: ["provider", "model", "voice", "base_url"] };
// For each service: which saved key it uses, where to get one, and a typical model.
const SERVICES = {
  openai: { key: "openai", hint: "Get a key at platform.openai.com → API keys.", llm: "e.g. gpt-4.1-mini", stt: "e.g. gpt-4o-mini-transcribe", tts: "e.g. gpt-4o-mini-tts" },
  anthropic: { key: "anthropic", hint: "Get a key at console.anthropic.com → API keys.", llm: "claude-opus-5-5 (or claude-haiku-5-5: faster, cheaper)" },
  groq: { key: "groq", hint: "Get a free key at console.groq.com → API keys.", llm: "press List models", stt: "whisper-large-v3-turbo" },
  openrouter: { key: "openrouter", hint: "Get a key at openrouter.ai → Keys.", llm: "press List models" },
  gemini: { key: "openai_compatible", hint: "Get a key at aistudio.google.com → Get API key (has a free tier).", llm: "e.g. gemini-3.5-flash-lite" },
  custom: { key: "openai_compatible", hint: "The key for the service at the address below, if it needs one.", llm: "", stt: "", tts: "" },
  elevenlabs: { key: "elevenlabs", hint: "Get a key at elevenlabs.io → Developers → API keys.", tts: "eleven_flash_v2_5" },
  local: { key: "", hint: "Runs on the device: no key and no cost." },
};
let keyStatus = {};

async function loadSettings() {
  const s = state.settings = await api("GET", "/api/settings");
  for (const [group, names] of Object.entries(FIELDS)) {
    for (const n of names) { const el = $(group + "-" + n); if (el) el.value = s[group][n] ?? ""; }
  }
  if (!$("llm-effort").value) $("llm-effort").value = "low";
  $("dev-volume").value = s.volume;
  $("dev-mode").value = s.listening.mode;
  $("dev-end_silence").value = s.listening.end_silence;
  $("dev-voice_interrupt").checked = !!s.listening.voice_interrupt;
  $("dev-memory").checked = !!s.conversation.memory;
  $("dev-search").checked = s.conversation.web_search !== false;
  $("dev-gestures").checked = s.conversation.gestures !== false;
  $("dev-random-gestures").checked = s.conversation.random_gestures !== false;
  $("dev-format").value = s.character_format || "live2d";
  renderKeys(await api("GET", "/api/keys"));
}

// Show only what the chosen service needs: its key, its address, its options.
function shapeGroup(group) {
  const provider = $(group + "-provider").value;
  const info = SERVICES[provider] || {};
  const box = document.querySelector('fieldset[data-group="' + group + '"]');
  for (const el of box.querySelectorAll(".for-custom")) el.hidden = provider !== "custom";
  for (const el of box.querySelectorAll(".for-anthropic")) el.hidden = provider !== "anthropic";
  for (const el of box.querySelectorAll(".for-elevenlabs")) el.hidden = provider !== "elevenlabs";
  for (const el of box.querySelectorAll(".for-cloud")) el.hidden = provider === "local";
  for (const el of box.querySelectorAll(".for-local")) el.hidden = provider !== "local";
  for (const el of box.querySelectorAll(".for-voicelist")) el.hidden = provider !== "local" && provider !== "elevenlabs";
  const model = $(group + "-model");
  if (model && info[group] !== undefined) model.placeholder = info[group];
  const keybox = box.querySelector(".keybox");
  keybox.replaceChildren();
  keybox.hidden = !provider;
  if (!provider) return;
  const hint = document.createElement("span"); hint.className = "hint"; text(hint, info.hint || "");
  keybox.append(hint);
  if (!info.key) return;
  const saved = !!keyStatus[info.key];
  const status = document.createElement("span"); status.className = saved ? "ok" : "";
  text(status, saved ? "Key saved ✓ " : "No key yet. ");
  const input = document.createElement("input"); input.type = "password"; input.autocomplete = "off";
  input.placeholder = saved ? "paste a new key to replace it" : "paste the key here";
  input.className = "key-input";
  const save = document.createElement("button"); save.type = "button"; text(save, "Save key");
  save.addEventListener("click", async () => {
    try { keyStatus = await api("PUT", "/api/keys/" + info.key, { value: input.value.trim() }); refreshKeys(); }
    catch (err) { text(status, err.message + " "); }
  });
  keybox.append(status, input, save);
}

function refreshKeys() {
  for (const g of Object.keys(FIELDS)) shapeGroup(g);
  renderKeys(keyStatus);
}

for (const g of Object.keys(FIELDS)) $(g + "-provider").addEventListener("change", () => shapeGroup(g));

function renderKeys(status) {
  keyStatus = status;
  const box = $("keys");
  box.replaceChildren();
  for (const [name, set] of Object.entries(status)) {
    const row = document.createElement("div"); row.className = "key";
    const label = document.createElement("span"); text(label, (KEY_NAMES[name] || name) + (set ? " (set)" : ""));
    const input = document.createElement("input"); input.type = "password"; input.autocomplete = "off";
    input.placeholder = set ? "replace key" : "paste key";
    const save = document.createElement("button"); text(save, "Save");
    save.addEventListener("click", async () => { keyStatus = await api("PUT", "/api/keys/" + name, { value: input.value }); refreshKeys(); });
    row.append(label, input, save);
    if (set) {
      const clear = document.createElement("button"); clear.className = "danger"; text(clear, "Remove");
      clear.addEventListener("click", async () => { keyStatus = await api("PUT", "/api/keys/" + name, { value: "" }); refreshKeys(); });
      row.append(clear);
    }
    box.append(row);
  }
  for (const g of Object.keys(FIELDS)) shapeGroup(g);
}

async function saveServices() {
  const changes = {};
  for (const [group, names] of Object.entries(FIELDS)) {
    changes[group] = {};
    for (const n of names) {
      const el = $(group + "-" + n);
      if (el) changes[group][n] = el.type === "number" ? Number(el.value) : el.value.trim();
    }
  }
  await api("PUT", "/api/settings", changes);
}

for (const b of document.querySelectorAll("[data-test]")) {
  b.addEventListener("click", async () => {
    const out = $("test-" + b.dataset.test);
    text(out, "Saving and testing…");
    try {
      await saveServices();
      const r = await api("POST", "/api/test/" + b.dataset.test);
      text(out, (r.ok ? "Working: " : "Not working yet: ") + r.message);
      api("GET", "/api/status").then(setStatus).catch(() => {});
    } catch (err) { text(out, "Not working yet: " + err.message); }
  });
}

$("btn-models").addEventListener("click", async () => {
  try { await saveServices(); } catch (err) { return text($("test-llm"), err.message); }
  const r = await api("GET", "/api/models");
  const list = $("llm-models");
  list.replaceChildren();
  for (const m of r.models) { const o = document.createElement("option"); o.value = m; list.append(o); }
  text($("test-llm"), r.ok ? r.models.length + " models found: click the Model box to choose" : "Could not list models: " + r.message);
});

$("btn-voices").addEventListener("click", async () => {
  try { await saveServices(); } catch (err) { return text($("test-tts"), err.message); }
  const r = await api("GET", "/api/voices");
  const list = $("tts-voices");
  list.replaceChildren();
  for (const v of r.voices) { const o = document.createElement("option"); o.value = v.id; o.label = v.name; list.append(o); }
  text($("test-tts"), r.ok ? r.voices.length + " voices found: click the Voice box to choose" : "Could not list voices: " + r.message);
});

// ----- device
$("btn-save-device").addEventListener("click", async () => {
  try {
    await api("PUT", "/api/settings", {
      volume: Number($("dev-volume").value),
      listening: { mode: $("dev-mode").value, end_silence: Number($("dev-end_silence").value),
                   voice_interrupt: $("dev-voice_interrupt").checked },
      conversation: { memory: $("dev-memory").checked, web_search: $("dev-search").checked,
                      gestures: $("dev-gestures").checked, random_gestures: $("dev-random-gestures").checked },
      character_format: $("dev-format").value,
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

// ----- Wi-Fi
async function loadWifi() {
  const w = await api("GET", "/api/wifi");
  if (!w.available) { text($("wifi-status"), "Wi-Fi is managed outside this page on this machine."); $("wifi-form").hidden = true; return; }
  text($("wifi-status"), w.error ? "Problem: " + w.error : w.connected ? "Connected" + (w.address ? " as " + w.address : "") + "." :
       w.hotspot ? "Not on a network yet: you are connected through the device's own setup hotspot." : "Not connected.");
  const sel = $("wifi-ssid");
  sel.replaceChildren();
  for (const n of w.networks || []) {
    const o = document.createElement("option"); o.value = n.ssid;
    text(o, n.ssid + " (" + n.signal + "%" + (n.secure ? ", secured" : ", open") + ")"); sel.append(o);
  }
}
$("btn-wifi-scan").addEventListener("click", () => loadWifi().catch((e) => text($("wifi-msg"), e.message)));
$("wifi-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  text($("wifi-msg"), "Joining… if this page stops answering, reconnect your phone to your home Wi-Fi and find the device's new address on its screen.");
  try { await api("POST", "/api/wifi", { ssid: $("wifi-ssid").value, password: $("wifi-password").value }); text($("wifi-msg"), "Joined."); }
  catch (err) { text($("wifi-msg"), err.message); }
  $("wifi-password").value = "";
});

$("btn-tz").addEventListener("click", async () => {
  try { const r = await api("POST", "/api/timezone", { zone: Intl.DateTimeFormat().resolvedOptions().timeZone });
        text($("tz-device"), r.timezone); text($("tz-msg"), "Set."); }
  catch (err) { text($("tz-msg"), err.message); }
});

$("reset-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!confirm("Remove everything from this device? This cannot be undone.")) return;
  try {
    await api("POST", "/api/reset", { password: $("reset-password").value, confirm: $("reset-confirm").value.trim() });
    text($("reset-msg"), "Resetting. The device restarts; this page will ask for a new password.");
  } catch (err) { text($("reset-msg"), err.message); }
  $("reset-password").value = "";
});

$("btn-logout").addEventListener("click", async () => { await api("POST", "/api/logout"); if (source) source.close(); showLogin(false); });

start().catch((err) => { document.body.prepend(Object.assign(document.createElement("p"), { className: "error", textContent: err.message })); });
