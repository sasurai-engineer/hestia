import type { ScheduleEReport } from '../lib/api';
import { formatMoney } from './TransactionsTable';

/** Schedule E as the form reads, every line carrying its authority, the
 * exclusions shown, and unanswered BAR questions surfaced — never binned. */
export function ScheduleEView({ report }: { report: ScheduleEReport }) {
  return (
    <>
      <div className="card card--flush">
        <table className="table">
          <thead>
            <tr>
              <th>Line</th>
              <th>Item</th>
              <th style={{ textAlign: 'right' }}>Amount</th>
              <th>Authority</th>
            </tr>
          </thead>
          <tbody>
            {[...report.income_lines, ...report.expense_lines].map((line) => (
              <tr key={line.line_no}>
                <td>{line.line_no}</td>
                <td>{line.label}</td>
                <td style={{ textAlign: 'right' }}>{formatMoney(line.amount)}</td>
                <td>
                  <span className="citation">{line.citation}</span>
                </td>
              </tr>
            ))}
            <tr>
              <td>18</td>
              <td>Depreciation expense</td>
              <td style={{ textAlign: 'right' }}>{formatMoney(report.depreciation_line_18)}</td>
              <td>
                <span className="citation">{report.depreciation_citation}</span>
              </td>
            </tr>
            <tr>
              <td />
              <td>
                <strong>
                  Income {formatMoney(report.total_income)} · Expenses{' '}
                  {formatMoney(report.total_expenses)} · Net
                </strong>
              </td>
              <td style={{ textAlign: 'right' }}>
                <strong>{formatMoney(report.net)}</strong>
              </td>
              <td />
            </tr>
          </tbody>
        </table>
      </div>

      {report.needs_classification.length > 0 ? (
        <div className="card" style={{ marginTop: 14 }}>
          <strong className="error-note">
            {report.needs_classification.length} charge(s) need a repair-vs-improvement answer
          </strong>
          {report.needs_classification.map((flag) => (
            <p className="muted" key={flag.event_uuid}>
              {flag.occurred_on} · {flag.memo ?? 'no memo'} · {formatMoney(flag.amount)} —{' '}
              <span className="faint">{flag.reason}</span>
            </p>
          ))}
        </div>
      ) : null}

      {report.excluded.length > 0 ? (
        <div className="card" style={{ marginTop: 14 }}>
          <strong>Real money, not on this form</strong>
          {report.excluded.map((row) => (
            <p className="muted" key={row.label}>
              {formatMoney(row.amount)} — {row.label}{' '}
              <span className="citation">{row.citation}</span>
            </p>
          ))}
        </div>
      ) : null}

      <p className="faint" style={{ marginTop: 14 }}>
        {report.signoff
          ? `Signed off by ${report.signoff.confirmed_by}.`
          : 'Not yet reviewed by a tax professional.'}{' '}
        {report.caveat}
      </p>
    </>
  );
}
