// Shows the claims behind one door. Without this script, all of them are shown.
const chips = [...document.querySelectorAll<HTMLButtonElement>("#doors button")];
const claims = [...document.querySelectorAll<HTMLElement>("[data-doors]")];
const groups = [...document.querySelectorAll<HTMLElement>("[data-group]")];

function show(door: string): void {
  for (const chip of chips) chip.setAttribute("aria-pressed", String(chip.value === door));
  for (const claim of claims) claim.hidden = door !== "" && !claim.dataset["doors"]!.split(" ").includes(door);
  for (const group of groups) group.hidden = !group.querySelector("[data-doors]:not([hidden])");
}

const asked = new URLSearchParams(location.search).get("for") ?? "";
for (const chip of chips) {
  chip.addEventListener("click", () => {
    show(chip.value);
    const address = new URL(location.href);
    if (chip.value) address.searchParams.set("for", chip.value);
    else address.searchParams.delete("for");
    history.replaceState(null, "", address);
  });
}
document.querySelector<HTMLElement>("#doors")!.hidden = false;
show(chips.some((chip) => chip.value === asked) ? asked : "");
