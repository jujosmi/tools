const form = document.getElementById("form");
const input = document.getElementById("url");
const bitrateSelect = document.getElementById("bitrate");
const submit = document.getElementById("submit");
const statusBox = document.getElementById("status");
const download = document.getElementById("download");

function setStatus(message, error=false){
  statusBox.textContent = message;
  statusBox.classList.remove("hidden","error");
  if(error) statusBox.classList.add("error");
}
function hideDownload(){
  download.classList.add("hidden");
  download.removeAttribute("href");
  download.removeAttribute("download");
}

async function start(){
  hideDownload();
  submit.disabled = true;
  const bitrate = bitrateSelect.value;
  setStatus(`Preparing ${bitrate} kbps MP3…`);

  try{
    const r = await fetch("/api/convert", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({url:input.value.trim(), bitrate})
    });
    const data = await r.json();
    if(!r.ok || !data.ok) throw new Error(data.error || "Could not start conversion.");
    setStatus("Retrieving source audio…");
    await poll(data.jobId, bitrate);
  }catch(err){
    setStatus(err.message || "Something went wrong.", true);
  }finally{
    submit.disabled = false;
  }
}

async function poll(jobId, bitrate){
  const maxMs = 8 * 60 * 1000;
  const started = Date.now();

  while(Date.now() - started < maxMs){
    const r = await fetch(`/api/status/${encodeURIComponent(jobId)}`, {cache:"no-store"});
    const data = await r.json();
    if(!r.ok || !data.ok) throw new Error(data.error || "Conversion failed.");

    if(data.status === "ready"){
      const title = data.title || "your audio";
      download.textContent = `Download ${bitrate} kbps MP3 — ${title}`;
      download.href = `${data.downloadPath || `/api/download/${encodeURIComponent(jobId)}`}?bitrate=${encodeURIComponent(bitrate)}`;
      download.classList.remove("hidden");
      setStatus(`Your ${bitrate} kbps MP3 is ready. Starting download automatically…`);

      // Start the download as soon as the job reports ready. Keep the visible link as
      // a fallback in case the browser blocks an automatic download.
      download.setAttribute("aria-label", `Download ${bitrate} kbps MP3 — ${title}`);
      download.click();

      // Some browsers may prevent programmatic downloads after an asynchronous wait.
      // The link remains visible so the user can click it manually if needed.
      window.setTimeout(() => {
        if (!download.classList.contains("hidden")) {
          setStatus("Your MP3 is ready. If the download didn't start, click the Download MP3 link.");
        }
      }, 1800);
      return;
    }

    const progress = typeof data.progress === "number" ? ` ${Math.round(data.progress)}%` : "";
    setStatus(`Preparing source audio…${progress}`);
    await new Promise(resolve => setTimeout(resolve, 2500));
  }
  throw new Error("This conversion is taking longer than expected. Try again in a moment.");
}

form.addEventListener("submit", e => {
  e.preventDefault();
  start();
});
