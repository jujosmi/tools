const form = document.getElementById("form");
const input = document.getElementById("url");
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
  setStatus("Starting conversion…");

  try{
    const r = await fetch("/api/convert", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({url:input.value.trim()})
    });
    const data = await r.json();
    if(!r.ok || !data.ok) throw new Error(data.error || "Could not start conversion.");
    setStatus("Processing your audio…");
    await poll(data.jobId);
  }catch(err){
    setStatus(err.message || "Something went wrong.", true);
  }finally{
    submit.disabled = false;
  }
}

async function poll(jobId){
  const maxMs = 8 * 60 * 1000;
  const started = Date.now();

  while(Date.now() - started < maxMs){
    const r = await fetch(`/api/status/${encodeURIComponent(jobId)}`, {cache:"no-store"});
    const data = await r.json();
    if(!r.ok || !data.ok) throw new Error(data.error || "Conversion failed.");

    if(data.status === "ready"){
      const title = data.title || "your audio";
      download.textContent = `Download MP3 — ${title}`;
      download.href = data.downloadPath || `/api/download/${encodeURIComponent(jobId)}`;
      // No download="" attribute here: the server returns an MP3 attachment on success and
      // a readable HTML error page if the provider returns junk or the temporary link expires.
      download.classList.remove("hidden");
      setStatus("Your MP3 is ready. Click Download MP3 to retrieve it.");
      return;
    }

    const progress = typeof data.progress === "number" ? ` ${Math.round(data.progress)}%` : "";
    setStatus(`Processing your audio…${progress}`);
    await new Promise(resolve => setTimeout(resolve, 2500));
  }
  throw new Error("This conversion is taking longer than expected. Try again in a moment.");
}

form.addEventListener("submit", e => {
  e.preventDefault();
  start();
});
