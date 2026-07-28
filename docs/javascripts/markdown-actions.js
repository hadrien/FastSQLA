const bindMarkdownCopy = () => {
  const button = document.querySelector("[data-copy-markdown]");
  if (!button || button.dataset.copyBound === "true") {
    return;
  }

  button.dataset.copyBound = "true";
  button.addEventListener("click", async () => {
    const actions = button.closest("[data-markdown-url]");
    const status = actions?.querySelector("[role='status']");

    try {
      if (!actions || !status || !navigator.clipboard) {
        throw new Error("Markdown copy controls are unavailable.");
      }

      const response = await fetch(actions.dataset.markdownUrl);
      if (!response.ok) {
        throw new Error(`Markdown request failed with status ${response.status}.`);
      }

      await navigator.clipboard.writeText(await response.text());
      status.textContent = "Copied";
      window.setTimeout(() => {
        status.textContent = "";
      }, 2000);
    } catch (error) {
      if (status) {
        status.textContent = "Copy failed";
      }
      console.error("Unable to copy the Markdown page.", error);
    }
  });
};

if (typeof document$ === "undefined") {
  document.addEventListener("DOMContentLoaded", bindMarkdownCopy);
} else {
  document$.subscribe(bindMarkdownCopy);
}
