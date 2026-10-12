"use strict";

const items = [];
let nextId = 1;
const MAX_UPLOAD_MB = Number(document.body.dataset.maxUploadMb) || 0;

const DURATIONS = [0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
const RESOLUTIONS = [480, 720, 1080];
const settings = { transition: "none", aspect: "auto", fit: "contain" };

const $ = (id) => document.getElementById(id);
const grid = $("grid");
const fileInput = $("file-input");
const dropzone = $("dropzone");
const errorEl = $("error");

const fmtSeconds = (s) => {
  if (s < 60) return `${s.toLocaleString("fr-FR", { maximumFractionDigits: 2 })} s`;
  const m = Math.floor(s / 60);
  const r = Math.round(s - m * 60);
  return `${m} min ${String(r).padStart(2, "0")} s`;
};
const fmtBytes = (b) => (b >= 1024 ** 3 ? `${(b / 1024 ** 3).toFixed(1)} Go` : b >= 1024 ** 2 ? `${(b / 1024 ** 2).toFixed(1)} Mo` : `${Math.max(1, Math.round(b / 1024))} Ko`);
const plural = (n, word) => `${n} ${word}${n > 1 ? "s" : ""}`;
const isImage = (f) => f.type.startsWith("image/") || /\.(jpe?g|png|webp|gif|bmp|tiff?|heic|heif)$/i.test(f.name);

function showError(msg) {
  errorEl.textContent = msg;
  errorEl.hidden = !msg;
}

const durationInput = $("duration");
const trInput = $("transition-duration");
const resInput = $("resolution");
const qualityInput = $("quality");

const duration = () => DURATIONS[Number(durationInput.value)];
const transitionDuration = () => (settings.transition === "none" ? 0 : Number(trInput.value));
const resolution = () => RESOLUTIONS[Number(resInput.value)];
const crf = () => 32 - Number(qualityInput.value);

function qualityLabel(c) {
  if (c <= 20) return "Haute";
  if (c <= 25) return "Équilibrée";
  return "Légère";
}

document.querySelectorAll(".segmented").forEach((group) => {
  group.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-value]");
    if (!btn) return;
    group.querySelectorAll("button").forEach((b) => b.setAttribute("aria-checked", String(b === btn)));
    settings[group.dataset.name] = btn.dataset.value;
    refresh();
  });
});
[durationInput, trInput, resInput, qualityInput, $("background")].forEach((el) => el.addEventListener("input", refresh));

let firstPhotoRatio = null;
function videoSize() {
  const map = { "16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1, "4:3": 4 / 3 };
  const ratio = settings.aspect === "auto" ? firstPhotoRatio : map[settings.aspect];
  if (!ratio) return null;
  const s = resolution();
  let w = ratio >= 1 ? s * ratio : s;
  let h = ratio >= 1 ? s : s / ratio;
  const scale = Math.min(1, 1920 / Math.max(w, h));
  const even = (x) => Math.max(2, Math.round((x * scale) / 2) * 2);
  return [even(w), even(h)];
}

function totalSeconds() {
  const n = items.length;
  if (!n) return 0;
  return n * duration() + (n - 1) * transitionDuration();
}

function refresh() {
  const n = items.length;
  $("duration-out").textContent = fmtSeconds(duration());
  $("transition-duration-out").textContent = fmtSeconds(Number(trInput.value));
  $("transition-field").classList.toggle("disabled", settings.transition === "none");
  trInput.disabled = settings.transition === "none";
  $("background-field").classList.toggle("disabled", settings.fit === "cover");
  $("background").disabled = settings.fit === "cover";
  $("resolution-out").textContent = `${resolution()}p`;
  $("quality-out").textContent = qualityLabel(crf());

  $("count").textContent = n;
  $("tools").hidden = n === 0;
  $("reorder-hint").hidden = n < 2;

  const size = videoSize();
  const bytes = items.reduce((t, it) => t + it.file.size, 0);
  const tooBig = MAX_UPLOAD_MB > 0 && bytes > MAX_UPLOAD_MB * 1024 * 1024;
  $("sum-duration").textContent = n ? fmtSeconds(totalSeconds()) : "–";
  $("sum-size").textContent = n && size ? `${size[0]}×${size[1]}` : "–";
  $("sum-upload").textContent = n ? fmtBytes(bytes) : "–";
  $("sum-upload").classList.toggle("warn", tooBig);

  const summary = n ? `${plural(n, "photo")} · ${fmtSeconds(totalSeconds())}` : "Aucune photo";
  $("summary-top").textContent = summary;
  $("summary-bottom").textContent = summary;

  const busy = generating;
  const blocked = !n || tooBig || busy;
  $("generate").disabled = blocked;
  $("generate-mobile").disabled = blocked;
  if (tooBig && !busy) showError(`Les photos font ${fmtBytes(bytes)} : la limite d'envoi est de ${MAX_UPLOAD_MB} Mo. Retire des photos.`);
  else if (errorEl.dataset.kind === "size") showError("");
  errorEl.dataset.kind = tooBig ? "size" : "";

  updatePreviewFrame();
}

function addFiles(fileList) {
  const files = Array.from(fileList).filter(isImage);
  const skipped = fileList.length - files.length;
  for (const file of files) {
    items.push({ id: nextId++, file, url: URL.createObjectURL(file) });
  }
  if (skipped) showError(`${plural(skipped, "fichier")} ignoré${skipped > 1 ? "s" : ""} (pas une image).`);
  if (items.length && firstPhotoRatio === null) measureFirstPhoto();
  render();
}

function measureFirstPhoto() {
  if (!items.length) { firstPhotoRatio = null; return; }
  const img = new Image();
  const id = items[0].id;
  img.onload = () => {
    if (items[0] && items[0].id === id) { firstPhotoRatio = img.naturalWidth / img.naturalHeight; refresh(); }
  };
  img.src = items[0].url;
}

fileInput.addEventListener("change", () => {
  addFiles(fileInput.files);
  fileInput.value = "";
});

let dragDepth = 0;
const hasFiles = (e) => Array.from(e.dataTransfer?.types || []).includes("Files");
window.addEventListener("dragenter", (e) => { if (hasFiles(e)) { dragDepth++; dropzone.classList.add("over"); } });
window.addEventListener("dragleave", (e) => { if (hasFiles(e) && --dragDepth <= 0) { dragDepth = 0; dropzone.classList.remove("over"); } });
window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener("drop", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  dropzone.classList.remove("over");
  addFiles(e.dataTransfer.files);
});

function move(from, to) {
  if (to < 0 || to >= items.length || from === to) return;
  const [it] = items.splice(from, 1);
  items.splice(to, 0, it);
  afterReorder();
}

function removeAt(i) {
  const [it] = items.splice(i, 1);
  URL.revokeObjectURL(it.url);
  afterReorder();
}

function afterReorder() {

  firstPhotoRatio = null;
  measureFirstPhoto();
  render();
}

$("sort-name").addEventListener("click", () => {
  items.sort((a, b) => a.file.name.localeCompare(b.file.name, "fr", { numeric: true }));
  afterReorder();
});
$("sort-date").addEventListener("click", () => {
  items.sort((a, b) => a.file.lastModified - b.file.lastModified);
  afterReorder();
});
$("reverse").addEventListener("click", () => { items.reverse(); afterReorder(); });
$("clear").addEventListener("click", () => {
  if (!confirm(`Retirer les ${items.length} photos ?`)) return;
  items.splice(0).forEach((it) => URL.revokeObjectURL(it.url));
  afterReorder();
});

function render() {
  grid.replaceChildren(...items.map((it, i) => {
    const li = document.createElement("li");
    li.className = "tile";
    li.dataset.id = it.id;
    li.innerHTML = `
      <img alt="" loading="lazy" decoding="async">
      <span class="num">${i + 1}</span>
      <button type="button" class="remove" data-act="remove" aria-label="Retirer la photo ${i + 1}" title="Retirer">✕</button>
      <div class="moves">
        <button type="button" data-act="left" aria-label="Avancer la photo ${i + 1}" title="Plus tôt" ${i === 0 ? "disabled" : ""}>◀</button>
        <button type="button" data-act="right" aria-label="Reculer la photo ${i + 1}" title="Plus tard" ${i === items.length - 1 ? "disabled" : ""}>▶</button>
      </div>`;
    li.querySelector("img").src = it.url;
    li.title = it.file.name;
    return li;
  }));
  refresh();
  restartPreview();
}

grid.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const i = indexOfTile(btn.closest(".tile"));
  if (btn.dataset.act === "remove") removeAt(i);
  else if (btn.dataset.act === "left") move(i, i - 1);
  else move(i, i + 1);
});

const indexOfTile = (tile) => items.findIndex((it) => String(it.id) === tile.dataset.id);

let drag = null;

grid.addEventListener("pointerdown", (e) => {
  const tile = e.target.closest(".tile");
  if (!tile || e.target.closest("button") || (e.pointerType === "mouse" && e.button !== 0)) return;
  drag = { tile, pointerId: e.pointerId, type: e.pointerType, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, active: false, timer: null };
  if (e.pointerType !== "mouse") {
    drag.timer = setTimeout(() => startDrag(), 300);
  }
});

window.addEventListener("pointermove", (e) => {
  if (!drag || e.pointerId !== drag.pointerId) return;
  drag.x = e.clientX;
  drag.y = e.clientY;
  if (!drag.active) {
    const moved = Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0);
    if (drag.type === "mouse" && moved > 6) startDrag();
    else if (drag.type !== "mouse" && moved > 10) cancelDrag();
    return;
  }
  e.preventDefault();
  moveGhost();
  updatePlaceholder();
  autoScroll();
});

window.addEventListener("touchmove", (e) => { if (drag && drag.active) e.preventDefault(); }, { passive: false });
window.addEventListener("pointerup", endDrag);
window.addEventListener("pointercancel", (e) => { if (drag && !drag.active) cancelDrag(); else endDrag(e); });
grid.addEventListener("contextmenu", (e) => { if (drag) e.preventDefault(); });

function startDrag() {
  if (!drag || drag.active) return;
  drag.active = true;
  const rect = drag.tile.getBoundingClientRect();
  drag.offX = drag.x0 - rect.left;
  drag.offY = drag.y0 - rect.top;
  const ghost = document.createElement("div");
  ghost.className = "drag-ghost";
  ghost.style.width = `${rect.width}px`;
  ghost.style.height = `${rect.height}px`;
  ghost.innerHTML = `<img alt="" src="${drag.tile.querySelector("img").src}">`;
  document.body.appendChild(ghost);
  drag.ghost = ghost;
  drag.tile.classList.add("placeholder");
  document.body.classList.add("dragging");
  if (navigator.vibrate && drag.type !== "mouse") navigator.vibrate(15);
  moveGhost();
}

function moveGhost() {
  drag.ghost.style.left = `${drag.x - drag.offX}px`;
  drag.ghost.style.top = `${drag.y - drag.offY}px`;
}

function updatePlaceholder() {
  const target = document.elementFromPoint(drag.x, drag.y)?.closest(".tile");
  if (!target || target === drag.tile || !grid.contains(target)) return;
  const tiles = Array.from(grid.children);
  const from = tiles.indexOf(drag.tile);
  const to = tiles.indexOf(target);
  grid.insertBefore(drag.tile, from < to ? target.nextSibling : target);
}

function autoScroll() {
  const edge = 70;
  if (drag.y < edge) window.scrollBy(0, -12);
  else if (drag.y > window.innerHeight - edge) window.scrollBy(0, 12);
}

function cancelDrag() {
  if (!drag) return;
  clearTimeout(drag.timer);
  drag = null;
}

function endDrag(e) {
  if (!drag || (e && e.pointerId !== drag.pointerId)) return;
  clearTimeout(drag.timer);
  if (drag.active) {
    drag.ghost.remove();
    drag.tile.classList.remove("placeholder");
    document.body.classList.remove("dragging");
    const order = Array.from(grid.children).map((li) => li.dataset.id);
    items.sort((a, b) => order.indexOf(String(a.id)) - order.indexOf(String(b.id)));
    drag = null;
    afterReorder();
    return;
  }
  drag = null;
}

const preview = $("preview");
const layers = [$("preview-a"), $("preview-b")];
let previewIndex = 0;
let previewFront = 0;
let previewTimer = null;
let previewPlaying = true;

function updatePreviewFrame() {
  const size = videoSize();
  preview.style.aspectRatio = size ? `${size[0]} / ${size[1]}` : "16 / 9";
  preview.style.setProperty("--ratio", size ? size[0] / size[1] : 16 / 9);
  preview.style.background = settings.fit === "cover" ? "#000" : $("background").value;
  preview.classList.toggle("cover", settings.fit === "cover");
  $("preview-empty").hidden = items.length > 0;
  $("preview-toggle").disabled = items.length < 2;
}

function showPreview(i, animate) {
  const it = items[i];
  if (!it) { layers.forEach((l) => { l.style.opacity = 0; l.removeAttribute("src"); }); return; }
  const back = layers[1 - previewFront];
  const front = layers[previewFront];
  back.src = it.url;
  const t = transitionDuration() * 1000;
  back.getAnimations().forEach((a) => a.cancel());
  front.getAnimations().forEach((a) => a.cancel());
  if (!animate || settings.transition === "none" || !t) {
    back.style.opacity = 1; back.style.transform = "none";
    front.style.opacity = 0;
  } else if (settings.transition === "fade") {
    back.style.opacity = 1; back.style.transform = "none";
    back.animate([{ opacity: 0 }, { opacity: 1 }], { duration: t, easing: "linear" });
    front.animate([{ opacity: 1 }, { opacity: 0 }], { duration: t, easing: "linear", fill: "forwards" });
  } else {
    back.style.opacity = 1;
    back.animate([{ transform: "translateX(100%)" }, { transform: "translateX(0)" }], { duration: t, easing: "ease-in-out" });
    front.animate([{ transform: "translateX(0)", opacity: 1 }, { transform: "translateX(-100%)", opacity: 1 }], { duration: t, easing: "ease-in-out", fill: "forwards" });
  }
  back.style.zIndex = 2;
  front.style.zIndex = 1;
  previewFront = 1 - previewFront;
  $("preview-pos").textContent = items.length ? `Photo ${i + 1} / ${items.length}` : "";
}

function schedulePreview() {
  clearTimeout(previewTimer);
  if (!previewPlaying || items.length < 2) return;
  previewTimer = setTimeout(() => {
    previewIndex = (previewIndex + 1) % items.length;
    showPreview(previewIndex, true);
    schedulePreview();
  }, (duration() + transitionDuration()) * 1000);
}

function restartPreview() {
  if (previewIndex >= items.length) previewIndex = 0;
  showPreview(previewIndex, false);
  schedulePreview();
}

$("preview-toggle").addEventListener("click", () => {
  previewPlaying = !previewPlaying;
  $("preview-toggle").textContent = previewPlaying ? "⏸ Pause" : "▶ Lecture";
  schedulePreview();
});
[durationInput, trInput].forEach((el) => el.addEventListener("change", schedulePreview));

let generating = false;
let resultUrl = null;

function setProgress(pct, label) {
  $("progress").hidden = false;
  $("progress-fill").style.width = `${pct}%`;
  $("progress-label").textContent = label;
  $("summary-bottom").textContent = label;
}

function upload(formData) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/generate");
    xhr.upload.addEventListener("progress", (e) => {
      if (!e.lengthComputable) return setProgress(0, "Envoi des photos…");
      const pct = Math.round((e.loaded / e.total) * 100);
      setProgress(pct, `Envoi des photos… ${pct} %`);
    });
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (_) {  }
      if (xhr.status >= 200 && xhr.status < 300 && data.job_id) resolve(data);
      else if (xhr.status === 413) reject(new Error("Envoi trop volumineux : retire des photos."));
      else reject(new Error(data.error || `Erreur ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("Erreur réseau pendant l'envoi."));
    xhr.send(formData);
  });
}

async function waitForJob(jobId) {
  const labels = { normalizing: "Préparation des photos", transitions: "Calcul des transitions", encoding: "Encodage de la vidéo" };
  for (;;) {
    await new Promise((r) => setTimeout(r, 700));
    const res = await fetch(`/api/status/${jobId}`);
    if (!res.ok) throw new Error("Tâche introuvable sur le serveur.");
    const job = await res.json();
    if (job.status === "error") throw new Error(job.error || "Erreur pendant la création de la vidéo.");
    const pct = job.total ? Math.round((job.current / job.total) * 100) : 0;
    setProgress(pct, `${labels[job.status] || "Traitement"}… ${pct} %`);
    if (job.status === "done") return;
  }
}

async function generate() {
  if (generating || !items.length) return;
  generating = true;
  showError("");
  $("result").hidden = true;
  refresh();
  $("generate").textContent = "Création en cours…";
  setProgress(0, "Envoi des photos… 0 %");

  try {
    const fd = new FormData();
    items.forEach((it) => fd.append("images", it.file, it.file.name));
    fd.append("duration", duration());
    fd.append("transition", settings.transition);
    fd.append("transition_duration", Number(trInput.value));
    fd.append("aspect", settings.aspect);
    fd.append("fit", settings.fit);
    fd.append("background", $("background").value);
    fd.append("resolution", resolution());
    fd.append("crf", crf());

    const { job_id } = await upload(fd);
    await waitForJob(job_id);

    setProgress(100, "Récupération de la vidéo…");
    const res = await fetch(`/api/download/${job_id}`);
    if (!res.ok) throw new Error(`Erreur ${res.status} au téléchargement.`);
    const blob = await res.blob();
    if (resultUrl) URL.revokeObjectURL(resultUrl);
    resultUrl = URL.createObjectURL(blob);

    $("result-video").src = resultUrl;
    $("result-download").href = resultUrl;
    $("result-download").textContent = `Télécharger (${fmtBytes(blob.size)})`;
    $("result").hidden = false;
    $("progress").hidden = true;
    $("result").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    $("progress").hidden = true;
    showError(err.message || String(err));
    errorEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } finally {
    generating = false;
    $("generate").textContent = "Générer la vidéo";
    refresh();
  }
}

$("generate").addEventListener("click", generate);
$("generate-mobile").addEventListener("click", generate);
$("result-close").addEventListener("click", () => {
  $("result").hidden = true;
  $("result-video").pause();
});

render();
