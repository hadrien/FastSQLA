const bindMarkdownCopy = () => {
  const button = document.querySelector("[data-copy-markdown]");
  if (!button || button.dataset.copyBound === "true") {
    return;
  }

  button.dataset.copyBound = "true";
  button.addEventListener("click", async () => {
    const actions = button.closest("[data-markdown-url]");
    const status = actions?.querySelector("[role='status']");
    const label = button.querySelector("[data-copy-label]");
    const resetCopyState = () => {
      if (label) label.textContent = "Copy for LLM";
      if (status) status.textContent = "";
    };

    try {
      if (!actions || !status || !label || !navigator.clipboard) {
        throw new Error("Markdown copy controls are unavailable.");
      }

      const response = await fetch(actions.dataset.markdownUrl);
      if (!response.ok) {
        throw new Error(`Markdown request failed with status ${response.status}.`);
      }

      await navigator.clipboard.writeText(await response.text());
      label.textContent = "Copied";
      status.textContent = "Page Markdown copied";
      window.setTimeout(resetCopyState, 2000);
    } catch (error) {
      if (label) {
        label.textContent = "Copy failed";
      }
      if (status) {
        status.textContent = "Page Markdown could not be copied";
      }
      window.setTimeout(resetCopyState, 2000);
      console.error("Unable to copy the Markdown page.", error);
    }
  });
};

if (typeof document$ === "undefined") {
  document.addEventListener("DOMContentLoaded", bindMarkdownCopy);
} else {
  document$.subscribe(bindMarkdownCopy);
}
