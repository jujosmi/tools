const form = document.getElementById("convertForm");
const input = document.getElementById("urlInput");
const button = document.getElementById("convertBtn");
const buttonText = document.getElementById("buttonText");
const spinner = document.getElementById("buttonSpinner");
const message = document.getElementById("message");

function setMessage(text, kind = "info") {
  message.hidden = !text;
  message.textContent = text;
  message.className = `message ${kind}`;
}

function setBusy(busy) {
  button.disabled = busy;
  input.disabled = busy;
  spinner.hidden = !busy;
  buttonText.textContent = busy ? "Converting…" : "Convert to MP3";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = input.value.trim();

  if (!url) {
    setMessage("Paste a YouTube video URL first.", "error");
    input.focus();
    return;
  }

  setBusy(true);
  setMessage("Preparing your MP3…", "info");

  try {
    const response = await fetch("/api/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url })
    });

    if (!response.ok) {
      let errorText = "Conversion failed. Please try another video.";
      try {
        const data = await response.json();
        if (data.error) errorText = data.error;
      } catch (_) {}
      throw new Error(errorText);
    }

    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i);
    let filename = match ? decodeURIComponent(match[1].replace(/\"/g, "")) : "jujosmi-audio.mp3";
    if (!filename.toLowerCase().endsWith(".mp3")) filename += ".mp3";

    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);

    setMessage("Done — your MP3 download should have started.", "success");
  } catch (error) {
    setMessage(error.message || "Something went wrong.", "error");
  } finally {
    setBusy(false);
  }
});
