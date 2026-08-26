import type { DefectOut } from '../lib/api';
import { defectConsequences, titleCase } from '../lib/format';

/** The era-defect register: suspected, never confirmed, always cited. */
export function DefectRegister({ defects }: { defects: DefectOut[] }) {
  if (defects.length === 0) {
    return <p className="muted">No latent-defect flags for this vintage.</p>;
  }
  return (
    <div className="grid grid--cards">
      {defects.map((defect) => (
        <div className="card" key={defect.kind}>
          <strong>{titleCase(defect.kind)}</strong>{' '}
          <span className="pill pill--flag">{defect.status}</span>
          <p className="muted" style={{ margin: '6px 0' }}>
            {defectConsequences(defect).join(' · ') || 'no modeled consequence'}
          </p>
          {defect.derived_from ? <p className="faint">{defect.derived_from}</p> : null}
          {defect.citation ? <p className="citation">{defect.citation}</p> : null}
        </div>
      ))}
    </div>
  );
}
