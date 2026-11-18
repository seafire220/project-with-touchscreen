// Character Studio's page. Plain JavaScript; talks only to the studio on this computer.
"use strict";

const $ = (id) => document.getElementById(id);
const QUESTIONS = ["name", "personality", "story", "relationship", "likes", "dislikes", "speaking", "never", "greeting"];
const ABILITIES = { blink: "blinks", speak: "talks", head_turn: "turns its head", hair_sway: "hair sways",
  arm_left: "left arm moves", arm_right: "right arm moves", legs: "legs" };
let picture = null;          // the chosen file
let current = "";            // the character shown
let shown = "";              // what the shown character looked like last time (to redraw only on change)
let timer = null;

function text(el, value) { el.textContent = value == null ? "" : String(value); }

async function api(method, path, body, raw) {
  const opts = { method, headers: { "X-Studio": "1" } };
  if (raw !== undefined) opts.body = raw;
  else if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  const type = r.headers.get("Content-Type") || "";
  const data = type.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(typeof data === "string" ? data : JSON.stringify(data));
  return data;
}

// ----- picking a picture
function choose(file) {
  if (!file) return;
  picture = file;
  $("drop-preview").src = URL.createObjectURL(file);
  $("drop-preview").hidden = false;
  text($("drop-text"), file.name);
  if (!$("name").value) $("name").value = file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").slice(0, 60);
  ready();
}
function ready() { $("btn-make").disabled = !(picture && $("name").value.trim()); }
$("drop").addEventListener("click", () => $("file").click());
$("drop").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") $("file").click(); });
$("file").addEventListener("change", () => choose($("file").files[0]));
$("drop").addEventListener("dragover", (e) => { e.preventDefault(); $("drop").classList.add("over"); });
$("drop").addEventListener("dragleave", () => $("drop").classList.remove("over"));
$("drop").addEventListener("drop", (e) => {
  e.preventDefault();
  $("drop").classList.remove("over");
  choose(e.dataTransfer.files[0]);
});
$("name").addEventListener("input", ready);

$("btn-make").addEventListener("click", async () => {
  text($("new-msg"), "");
  $("btn-make").disabled = true;
  try {
    const q = "?name=" + encodeURIComponent($("name").value.trim()) + "&file=" + encodeURIComponent(picture.name);
    const job = await api("POST", "/api/jobs" + q, undefined, picture);
    current = job.id;
    shown = "";
    refresh();
  } catch (err) { text($("new-msg"), err.message); }
  ready();
});

// ----- the model
$("btn-setup").addEventListener("click", async () => {
  try { await api("POST", "/api/setup"); } catch (err) { text($("setup-missing"), err.message); }
  refresh();
});

function showSetup(status) {
  const f = status.finder, s = status.setup;
  $("setup").hidden = f.ready && s.state !== "running";
  $("new").hidden = !f.ready;
  if (f.ready) return;
  const torch = f.missing.includes("PyTorch");
  $("setup-torch").hidden = !torch;
  $("btn-setup").hidden = s.state === "running" || !(f.missing.includes("model code") || f.missing.includes("model weights"));
  text($("setup-missing"), s.state === "failed" ? s.message : "Missing: " + f.missing.join(", ") + ".");
  $("setup-progress").hidden = s.state !== "running";
  if (s.state === "running") {
    $("setup-bar").max = s.total || 1;
    $("setup-bar").value = s.done || 0;
    text($("setup-text"), s.message + (s.total ? " (" + Math.round(100 * s.done / s.total) + "%)" : ""));
  }
}

// ----- the character being made
function showJob(job) {
  $("job").hidden = false;
  text($("job-title"), job.name);
  const steps = $("job-steps");
  steps.replaceChildren();
  job.steps.forEach((s, i) => {
    const li = document.createElement("li");
    text(li, s);
    if (job.state === "working" && i === job.steps.length - 1) li.className = "now";
    steps.append(li);
  });
  if (job.state === "waiting") { const li = document.createElement("li"); text(li, "Waiting for the character before it"); steps.append(li); }
  text($("job-error"), job.state === "failed" ? "It could not be made: " + job.error : "");
  const key = job.id + job.state + job.has_preview + job.has_package;
  if (key !== shown) {
    shown = key;
    if (job.has_preview) $("job-preview").src = "/api/jobs/" + job.id + "/preview.gif?" + Date.now();
    else if (job.has_package) $("job-preview").src = "/api/jobs/" + job.id + "/still.png?" + Date.now();
    else $("job-preview").removeAttribute("src");
    text($("job-picture-note"), job.has_preview ? "A preview drawn on this computer; on the device it moves more smoothly." :
      job.state === "working" ? "The preview appears here when it is ready." : "");
    $("job-result").hidden = !job.capabilities;
    $("job-after").hidden = !job.has_package;
    if (job.capabilities) {
      const can = $("job-can");
      can.replaceChildren();
      for (const [k, label] of Object.entries(ABILITIES)) {
        if (!(k in job.capabilities)) continue;
        const span = document.createElement("span");
        text(span, label);
        if (!job.capabilities[k]) span.className = "no";
        can.append(span);
      }
      const notes = $("job-notes");
      notes.replaceChildren();
      for (const w of job.warnings || []) { const li = document.createElement("li"); text(li, w); notes.append(li); }
      const arms = (job.arms || []).concat(job.still_arms || []);
      $("job-arms").hidden = arms.length === 0;
      for (const side of ["l", "r"]) {
        const box = $("arm-" + side);
        box.parentElement.hidden = !arms.includes(side);
        box.checked = !(job.still_arms || []).includes(side);
      }
    }
    if (job.has_package) {
      for (const q of QUESTIONS) $("pf-" + q).value = (job.form && job.form[q]) || "";
      $("download").href = "/api/jobs/" + job.id + "/package";
    }
  }
  $("btn-remake").disabled = job.state === "working";
}

$("btn-remake").addEventListener("click", async () => {
  const still = ["l", "r"].filter((s) => !$("arm-" + s).parentElement.hidden && !$("arm-" + s).checked);
  try { await api("POST", "/api/jobs/" + current + "/remake", { still_arms: still }); shown = ""; refresh(); }
  catch (err) { text($("job-error"), err.message); }
});

$("btn-persona").addEventListener("click", async () => {
  const form = {};
  for (const q of QUESTIONS) form[q] = $("pf-" + q).value;
  try {
    const job = await api("PUT", "/api/jobs/" + current + "/persona", { form });
    text($("persona-msg"), "Saved.");
    text($("job-title"), job.name);
  } catch (err) { text($("persona-msg"), err.message); }
});

$("btn-send").addEventListener("click", async () => {
  text($("send-msg"), "Sending…");
  $("btn-send").disabled = true;
  try {
    await api("POST", "/api/jobs/" + current + "/send", { address: $("address").value.trim() || "companion.local", password: $("password").value });
    text($("send-msg"), "Done: the character is on the device.");
  } catch (err) { text($("send-msg"), err.message); }
  $("password").value = "";
  $("btn-send").disabled = false;
});

// ----- everything made in this session
function showHistory(jobs) {
  $("history").hidden = jobs.length < 2;
  const list = $("jobs");
  list.replaceChildren();
  for (const job of jobs) {
    const li = document.createElement("li");
    text(li, job.name + (job.state === "working" ? " (being made)" : job.state === "failed" ? " (failed)" : ""));
    if (job.id === current) li.className = "on";
    li.addEventListener("click", () => { current = job.id; shown = ""; refresh(); });
    list.append(li);
  }
}

async function refresh() {
  clearTimeout(timer);
  let status;
  try { status = await api("GET", "/api/status"); }
  catch (err) { timer = setTimeout(refresh, 3000); return; }
  showSetup(status);
  if (!current && status.jobs.length) current = status.jobs[0].id;
  const job = status.jobs.find((j) => j.id === current);
  if (job) showJob(job);
  showHistory(status.jobs);
  const busy = status.setup.state === "running" || status.jobs.some((j) => j.state === "working" || j.state === "waiting");
  timer = setTimeout(refresh, busy ? 1200 : 5000);
}

api("GET", "/api/device").then((d) => { $("address").value = d.address; }).catch(() => {});
refresh();
