let activeModalId = null;
let previousFocus = null;
const onCloseHandlers = new Map();

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

function getModalFocusables(modal) {
  return Array.from(modal.querySelectorAll(FOCUSABLE)).filter(
    (el) => !el.closest(".hidden") && el.offsetParent !== null,
  );
}

export function registerModalCloseHandler(modalId, handler) {
  onCloseHandlers.set(modalId, handler);
}

export function isModalOpen(modalId) {
  const modal = document.getElementById(modalId);
  return modal && !modal.classList.contains("hidden");
}

export function openModal(modalId) {
  if (activeModalId && activeModalId !== modalId) {
    closeModal(activeModalId);
  }
  const modal = document.getElementById(modalId);
  if (!modal) return;
  previousFocus = document.activeElement;
  modal.classList.remove("hidden");
  document.body.classList.add("modal-open");
  activeModalId = modalId;
  const focusables = getModalFocusables(modal);
  (focusables[0] || modal).focus();
}

export function closeModal(modalId = activeModalId) {
  if (!modalId) return;
  const modal = document.getElementById(modalId);
  if (modal) modal.classList.add("hidden");
  if (activeModalId === modalId) {
    activeModalId = null;
    document.body.classList.remove("modal-open");
    if (previousFocus && typeof previousFocus.focus === "function") {
      previousFocus.focus();
    }
    previousFocus = null;
  }
  const handler = onCloseHandlers.get(modalId);
  if (handler) handler();
}

export function getActiveModalId() {
  return activeModalId;
}

export function initModals() {
  document.querySelectorAll("[data-modal-close]").forEach((element) => {
    element.addEventListener("click", () => {
      const modal = element.closest(".modal");
      if (modal) closeModal(modal.id);
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && activeModalId) {
      closeModal(activeModalId);
      return;
    }

    if (event.key !== "Tab" || !activeModalId) return;
    const modal = document.getElementById(activeModalId);
    if (!modal) return;
    const focusables = getModalFocusables(modal);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
}
