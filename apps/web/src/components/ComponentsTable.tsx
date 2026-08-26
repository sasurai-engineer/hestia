import type { ComponentOut } from '../lib/api';
import { lifeSummary, titleCase } from '../lib/format';

/**
 * The inventory the platform inferred on day one, with its uncertainty shown:
 * the install band, the confidence, and how much expected life is spent.
 */
export function ComponentsTable({
  components,
  nowYear,
}: {
  components: ComponentOut[];
  nowYear: number;
}) {
  if (components.length === 0) {
    return <p className="muted">No components yet — assemble the dossier to infer them.</p>;
  }
  return (
    <div className="card card--flush">
      <table className="table">
        <thead>
          <tr>
            <th>Component</th>
            <th>Installed</th>
            <th>Life spent</th>
            <th>Basis</th>
          </tr>
        </thead>
        <tbody>
          {components.map((component) => {
            const life = lifeSummary(component, nowYear);
            return (
              <tr key={component.code}>
                <td>
                  {component.display_name}
                  <div className="faint">{titleCase(component.system)}</div>
                </td>
                <td>
                  {component.installed_year_low != null && component.installed_year_high != null
                    ? component.installed_year_low === component.installed_year_high
                      ? String(component.installed_year_low)
                      : `${String(component.installed_year_low)}–${String(component.installed_year_high)}`
                    : 'unknown'}
                </td>
                <td>
                  {life.spent != null ? (
                    // biome-ignore lint/a11y/useSemanticElements: native <meter> styling is not reliably overridable cross-browser; the full ARIA meter contract is carried instead
                    <div
                      className="lifebar"
                      role="meter"
                      aria-label={`${component.display_name} life spent`}
                      aria-valuenow={Math.round(life.spent * 100)}
                      aria-valuemin={0}
                      aria-valuemax={100}
                    >
                      <div
                        className={
                          life.beyondExpected
                            ? 'lifebar__fill lifebar__fill--spent'
                            : 'lifebar__fill'
                        }
                        style={{ width: `${String(Math.round(life.spent * 100))}%` }}
                      />
                    </div>
                  ) : (
                    <span className="faint">—</span>
                  )}
                </td>
                <td>
                  <span className="muted">
                    {component.provenance_kind} · {Math.round(component.confidence * 100)}%
                  </span>
                  {component.derived_from ? (
                    <div className="faint">{component.derived_from}</div>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
