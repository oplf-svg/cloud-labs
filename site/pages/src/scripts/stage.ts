// Loads one build of the recorder, and the other one when the reader asks for it.
const stage = document.querySelector<HTMLElement>("#stage")!;
const builds = document.querySelector<HTMLFieldSetElement>("#builds")!;
const measured = document.querySelector<HTMLOutputElement>("#measured")!;
const choices = [...builds.querySelectorAll<HTMLInputElement>("input")];
const KEY = "recorder-build";

function remembered(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null; // Some browsers forbid storage. The choice is then forgotten, and nothing else changes.
  }
}

function remember(build: string): void {
  try {
    localStorage.setItem(KEY, build);
  } catch {
    // See above.
  }
}

/** Waits until the element has drawn itself. */
const drawn = (element: HTMLElement) =>
  new Promise<void>((done) => {
    if (element.querySelector(".rec")) return done();
    const watch = new MutationObserver(() => {
      if (!element.querySelector(".rec")) return;
      watch.disconnect();
      done();
    });
    watch.observe(element, { childList: true, subtree: true });
  });

async function load(choice: HTMLInputElement): Promise<void> {
  const started = performance.now();
  try {
    await import(/* @vite-ignore */ `/builds/${choice.value}/main.js`);
    if (!choice.checked) return; // The reader has chosen again in the meantime.
    const element = document.createElement(`recorder-${choice.value}`);
    element.dataset["for"] = "recorder-data";
    stage.replaceChildren(element);
    await drawn(element);
    const ms = Math.max(1, Math.round(performance.now() - started));
    const parts: Record<string, string> = { kb: choice.dataset["kb"] ?? "", ms: String(ms) };
    measured.textContent = (measured.dataset["text"] ?? "").replace(/\{(\w+)\}/g, (whole, name: string) => parts[name] ?? whole);
  } catch {
    stage.textContent = stage.dataset["failed"] ?? "";
    measured.textContent = "";
  }
}

const start = choices.find((choice) => choice.value === remembered()) ?? choices[0]!;
start.checked = true;
builds.hidden = false;
for (const choice of choices) {
  choice.addEventListener("change", () => {
    remember(choice.value);
    void load(choice);
  });
}
void load(start);
