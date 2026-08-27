/**
 * The two effects primitives perform on real DOM nodes, extracted so every
 * branch — including the null paths React refs make unreachable inside a
 * mounted component — is directly testable.
 */

type DialogLike = Pick<HTMLDialogElement, 'open' | 'showModal' | 'close'>;

/** Drive a native dialog to match the declared `open` prop. */
export function syncDialog(dialog: DialogLike | null, open: boolean): void {
  if (dialog === null) {
    return;
  }
  if (open && !dialog.open) {
    dialog.showModal();
    return;
  }
  if (!open && dialog.open) {
    dialog.close();
  }
}

/** Focus a node that may not have mounted yet. */
export function focusIfPresent(element: Pick<HTMLElement, 'focus'> | null): void {
  if (element !== null) {
    element.focus();
  }
}
