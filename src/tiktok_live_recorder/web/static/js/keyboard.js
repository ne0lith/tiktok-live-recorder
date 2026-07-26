import { closeModal, getActiveModalId, openModal } from "./modal.js";
import { setSelectedProfile } from "./status.js";
import { selectedProfile } from "./state.js";

const SHORTCUTS = [
  { keys: "/", description: "Focus media search" },
  { keys: "Esc", description: "Clear user focus or close modal" },
  { keys: "?", description: "Show keyboard shortcuts" },
  { keys: "l", description: "Open logs" },
  { keys: "s", description: "Open settings" },
];

function isTypingTarget(target) {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}

function renderShortcutsList() {
  const list = document.getElementById("shortcuts-list");
  if (!list) return;
  list.innerHTML = SHORTCUTS.map(
    ({ keys, description }) =>
      `<li><kbd>${keys}</kbd><span>${description}</span></li>`,
  ).join("");
}

export function initKeyboardShortcuts() {
  renderShortcutsList();

  document.addEventListener("keydown", (event) => {
    if (isTypingTarget(event.target) && event.key !== "Escape") return;

    if (event.key === "?" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      openModal("shortcuts-modal");
      return;
    }

    if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      document.getElementById("media-search")?.focus();
      return;
    }

    if (event.key === "Escape") {
      if (getActiveModalId()) {
        closeModal();
        return;
      }
      if (selectedProfile) {
        event.preventDefault();
        setSelectedProfile(null);
      }
      return;
    }

    if (event.key === "l" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      document.getElementById("logs-toggle")?.click();
      return;
    }

    if (event.key === "s" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      document.getElementById("settings-toggle")?.click();
    }
  });
}
