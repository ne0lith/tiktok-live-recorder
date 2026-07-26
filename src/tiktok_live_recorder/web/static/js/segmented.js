const updaters = new WeakMap();

export function updateSegmentedControl(container) {
  if (!container) return;
  const indicator = container.querySelector(".segment-indicator");
  const active = container.querySelector(".is-active");
  if (!indicator) return;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  indicator.style.transition = reducedMotion ? "none" : "";
  if (!active) {
    indicator.style.opacity = "0";
    return;
  }
  indicator.style.opacity = "1";
  indicator.style.width = `${active.offsetWidth}px`;
  indicator.style.transform = `translateX(${active.offsetLeft}px)`;
}

export function initSegmentedControl(container) {
  if (!container || updaters.has(container)) return;

  const indicator = document.createElement("span");
  indicator.className = "segment-indicator";
  indicator.setAttribute("aria-hidden", "true");
  container.prepend(indicator);

  const update = () => updateSegmentedControl(container);
  updaters.set(container, update);

  container.addEventListener("click", () => {
    requestAnimationFrame(update);
  });

  if (typeof ResizeObserver !== "undefined") {
    const observer = new ResizeObserver(() => update());
    observer.observe(container);
    container.querySelectorAll("button").forEach((button) => observer.observe(button));
  }

  window.addEventListener("resize", update);
  requestAnimationFrame(update);
}

export function initSegmentedControls() {
  document.querySelectorAll(".segmented-control").forEach(initSegmentedControl);
}
