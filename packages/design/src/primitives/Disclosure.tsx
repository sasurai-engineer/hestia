import { type ReactNode, useId, useState } from 'react';

/**
 * The depth mechanism: content unfolds in place, animated by grid rows so
 * height is never measured in script. Closed content stays rendered but
 * inert — the panel keeps its height animation and assistive tech skips it.
 */
type DisclosureProps = {
  summary: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
};

export function Disclosure({ summary, defaultOpen = false, children }: DisclosureProps) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();
  return (
    <div className="disclosure">
      <button
        type="button"
        className="disclosure__summary"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="disclosure__marker" aria-hidden="true">
          ❯
        </span>
        {summary}
      </button>
      <div
        id={panelId}
        className={open ? 'disclosure__panel disclosure__panel--open' : 'disclosure__panel'}
      >
        <div className="disclosure__inner" inert={open ? undefined : true}>
          {children}
        </div>
      </div>
    </div>
  );
}
