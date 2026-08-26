import type { DeadlineOut } from '../lib/api';
import { formatDate, titleCase } from '../lib/format';

/** Deadlines with their runway and authority — never a date without a source. */
export function DeadlineList({ deadlines }: { deadlines: DeadlineOut[] }) {
  if (deadlines.length === 0) {
    return <p className="muted">Nothing on the calendar yet — run a dossier sweep.</p>;
  }
  return (
    <div className="card card--flush">
      <table className="table">
        <thead>
          <tr>
            <th>Due</th>
            <th>What</th>
            <th>Where</th>
            <th>Authority</th>
          </tr>
        </thead>
        <tbody>
          {deadlines.map((deadline) => (
            <tr key={deadline.id}>
              <td>
                <strong>{formatDate(deadline.due_on)}</strong>
                {deadline.window_opens_on ? (
                  <div className="faint">opens {formatDate(deadline.window_opens_on)}</div>
                ) : null}
              </td>
              <td>
                {titleCase(deadline.kind)}
                {deadline.note ? <div className="muted">{deadline.note}</div> : null}
              </td>
              <td>{deadline.property_label ?? <span className="faint">entity-wide</span>}</td>
              <td>
                <span className="citation">{deadline.citation}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
