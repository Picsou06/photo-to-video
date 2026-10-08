const imagesInput = document.getElementById("images");
const countEl = document.getElementById("count");
const form = document.getElementById("video-form");
const submitBtn = document.getElementById("submit-btn");
const errorEl = document.getElementById("error");
const progressWrap = document.getElementById("progress-wrap");
const progressLabel = document.getElementById("progress-label");
const progressBar = document.getElementById("progress-bar");

imagesInput.addEventListener("change", () => {
  const n = imagesInput.files.length;
  countEl.textContent = n ? `${n} photo${n > 1 ? "s" : ""} sélectionnée${n > 1 ? "s" : ""}` : "";
});

function setProgress(pct, label) {
  progressWrap.style.display = "block";
  progressBar.value = pct;
  progressLabel.textContent = label;
}

function uploadWithProgress(formData) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/generate");
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        setProgress(pct, `Envoi des photos… ${pct}%`);
      } else {
        setProgress(0, "Envoi des photos…");
      }
    });
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch (e) {
          reject(new Error("Réponse invalide du serveur"));
        }
      } else {
        try {
          reject(new Error(JSON.parse(xhr.responseText).error || `Erreur ${xhr.status}`));
        } catch (e) {
          reject(new Error(`Erreur ${xhr.status}`));
        }
      }
    };
    xhr.onerror = () => reject(new Error("Erreur réseau pendant l'envoi"));
    xhr.send(formData);
  });
}

async function pollJob(jobId) {
  while (true) {
    await new Promise((r) => setTimeout(r, 700));
    const res = await fetch(`/api/status/${jobId}`);
    if (!res.ok) throw new Error("Job introuvable");
    const job = await res.json();

    if (job.status === "error") {
      throw new Error(job.error || "Erreur inconnue pendant le traitement");
    }

    const pct = job.total ? Math.round((job.current / job.total) * 100) : 0;
    const stageLabel = job.status === "normalizing" ? "Préparation des photos" : "Encodage de la vidéo";
    setProgress(pct, `${stageLabel}… ${pct}%`);

    if (job.status === "done") return;
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorEl.style.display = "none";

  const n = imagesInput.files.length;
  if (!n) return;

  submitBtn.disabled = true;
  submitBtn.textContent = "En cours…";
  setProgress(0, "Envoi des photos… 0%");

  try {
    const formData = new FormData(form);
    const { job_id } = await uploadWithProgress(formData);

    await pollJob(job_id);

    setProgress(100, "Téléchargement…");
    const res = await fetch(`/api/download/${job_id}`);
    if (!res.ok) throw new Error(`Erreur ${res.status} au téléchargement`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "video.mp4";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    progressWrap.style.display = "none";
  } catch (err) {
    errorEl.textContent = err.message || String(err);
    errorEl.style.display = "block";
    progressWrap.style.display = "none";
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Générer la vidéo";
  }
});
