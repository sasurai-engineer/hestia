import type { ReactNode } from 'react';
import { Button } from '../primitives/Button.js';
import { CitationChip } from '../primitives/CitationChip.js';
import { Disclosure } from '../primitives/Disclosure.js';
import { Pill, type PillTone } from '../primitives/Pill.js';
import { Stat } from '../primitives/Stat.js';

/**
 * The decision-card grammar: one figure, one verdict, its authority, the
 * counterfactual, and at most one action. The authority list is a non-empty
 * tuple and the counterfactual is required — an ungrounded card is a type
 * error, not a review comment.
 *
 * Four depths: Glance (the red entry and the verdict, always visible) →
 * Scan (one sentence of drivers, the counterfactual, the authorities) →
 * Study (the caller's inputs — sliders, tables) → Audit (every figure's
 * provenance). Each depth unfolds inside the previous one.
 */
export type Authority = {
  cite: string;
  detail?: string;
  /** Statutes stamp in survey-blue; engines sign in graphite. */
  kind?: 'statute' | 'engine';
};

type DecisionCardProps = {
  title: string;
  figureLabel: string;
  figure: string;
  verdict: { label: string; tone: PillTone };
  authority: readonly [Authority, ...Authority[]];
  counterfactual: string;
  scan: string;
  study?: ReactNode;
  audit?: ReactNode;
  action?: { label: string; act: () => void };
  caveat?: string;
};

function AuthorityChip({ authority }: { authority: Authority }) {
  if (authority.kind === 'statute') {
    return <CitationChip cite={authority.cite} detail={authority.detail} />;
  }
  return (
    <span className="engine-chip" title={authority.detail ?? authority.cite}>
      {authority.cite}
    </span>
  );
}

export function DecisionCard({
  title,
  figureLabel,
  figure,
  verdict,
  authority,
  counterfactual,
  scan,
  study,
  audit,
  action,
  caveat,
}: DecisionCardProps) {
  const auditDepth =
    audit === undefined ? null : (
      <Disclosure summary={<span className="decision__depth">audit every figure</span>}>
        {audit}
      </Disclosure>
    );
  const studyDepth =
    study === undefined ? (
      auditDepth
    ) : (
      <Disclosure summary={<span className="decision__depth">adjust the inputs</span>}>
        {study}
        {auditDepth}
      </Disclosure>
    );
  return (
    <section className="card decision" aria-label={title}>
      <header className="decision__glance">
        <div className="decision__heading">
          <h3 className="decision__title">{title}</h3>
          <Pill tone={verdict.tone}>{verdict.label}</Pill>
          {action === undefined ? null : (
            <Button variant="quiet" onClick={action.act}>
              {action.label}
            </Button>
          )}
        </div>
        <Stat label={figureLabel} value={figure} />
      </header>
      <Disclosure summary={<span className="decision__depth">the working</span>}>
        <p className="decision__scan">{scan}</p>
        <p className="decision__counterfactual">{counterfactual}</p>
        <p className="decision__authority">
          {authority.map((entry) => (
            <AuthorityChip key={entry.cite} authority={entry} />
          ))}
        </p>
        {studyDepth}
      </Disclosure>
      {caveat === undefined ? null : <p className="faint decision__caveat">{caveat}</p>}
    </section>
  );
}
