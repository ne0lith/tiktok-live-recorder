export function userChipMarkup(username, { variant = "focus", dismissAction = "clear-focus" } = {}) {
  const dismissLabel =
    dismissAction === "unhide-user"
      ? `Show @${username} again`
      : `Clear focus for @${username}`;
  const dismissAttr =
    dismissAction === "unhide-user"
      ? `data-unhide-user="${username}"`
      : 'data-clear-focus="1"';
  const chipClass =
    variant === "focus"
      ? "summary-chip summary-chip--focus"
      : "summary-chip summary-chip--muted";
  return `<span class="${chipClass}">
    <span class="summary-chip-label">@${username}</span>
    <button type="button" class="summary-chip-dismiss" ${dismissAttr} aria-label="${dismissLabel}">x</button>
  </span>`;
}

export function bindChipDismiss(container, handlers) {
  if (!container) return;
  container.addEventListener("click", (event) => {
    const dismiss = event.target.closest(".summary-chip-dismiss");
    if (!dismiss) return;
    event.stopPropagation();
    if (dismiss.hasAttribute("data-clear-focus") && handlers.onClearFocus) {
      handlers.onClearFocus();
      return;
    }
    const unhide = dismiss.getAttribute("data-unhide-user");
    if (unhide && handlers.onUnhideUser) {
      handlers.onUnhideUser(unhide);
    }
  });
}
