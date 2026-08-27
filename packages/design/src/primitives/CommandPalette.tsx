import { type KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from 'react';
import { fuzzyMatch } from '../fuzzy.js';
import { focusIfPresent, syncDialog } from './dom.js';

/**
 * One keystroke to any property, page, or verb. A combobox over a listbox:
 * every key lives on the input, options are pointer targets, and the whole
 * thing rides the native <dialog> top layer.
 */
export type Command = {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
};

type CommandPaletteProps = {
  open: boolean;
  onClose: () => void;
  commands: readonly Command[];
};

export function CommandPalette({ open, onClose, commands }: CommandPaletteProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);

  const matches = useMemo(
    () => commands.filter((command) => fuzzyMatch(query, command.label)),
    [commands, query],
  );
  const activeIndex = Math.min(active, Math.max(0, matches.length - 1));
  const activeCommand = matches[activeIndex];

  useEffect(() => {
    syncDialog(dialogRef.current, open);
    if (open) {
      setQuery('');
      setActive(0);
      focusIfPresent(inputRef.current);
    }
  }, [open]);

  const run = (command: Command | undefined) => {
    if (command === undefined) {
      return;
    }
    onClose();
    command.run();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive(Math.min(activeIndex + 1, Math.max(0, matches.length - 1)));
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive(Math.max(activeIndex - 1, 0));
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      run(activeCommand);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      className="dialog palette"
      aria-label="Command palette"
      onClose={onClose}
      onCancel={onClose}
    >
      <input
        ref={inputRef}
        className="palette__input"
        placeholder="Type a command…"
        role="combobox"
        aria-expanded={matches.length > 0}
        aria-controls={listId}
        aria-activedescendant={
          activeCommand === undefined ? undefined : `${listId}-${activeCommand.id}`
        }
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setActive(0);
        }}
        onKeyDown={onKeyDown}
      />
      {matches.length === 0 ? (
        <p className="palette__empty">Nothing answers to that.</p>
      ) : (
        <ul className="palette__list" id={listId} role="listbox" aria-label="Commands">
          {matches.map((command, index) => (
            // The combobox pattern: focus stays on the input, options are
            // announced via aria-activedescendant and clicked with a pointer.
            // The a11y rules this trips are switched off for this file alone
            // in the package biome.json — the pattern is ARIA-correct and the
            // linter cannot model it.
            <li
              key={command.id}
              id={`${listId}-${command.id}`}
              role="option"
              aria-selected={index === activeIndex}
              className="palette__option"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => run(command)}
            >
              <span>{command.label}</span>
              {command.hint === undefined ? null : (
                <span className="palette__hint">{command.hint}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </dialog>
  );
}

/** The palette's hotkey: ⌘K (or Ctrl+K), wired once per page. */
export function useCommandK(onOpen: () => void): void {
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
        event.preventDefault();
        onOpen();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onOpen]);
}
