'use client';

import { useEffect, useState } from 'react';
import { api, type CoverageReport } from '../../lib/api';
import { titleCase } from '../../lib/format';

export default function CoveragePage() {
  const [report, setReport] = useState<CoverageReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .coverage()
      .then(setReport)
      .catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : String(caught));
      });
  }, []);

  return (
    <>
      <h1 className="page-title">Jurisdiction coverage</h1>
      <p className="page-subtitle">
        What the platform knows for each property, rule domain by rule domain — and, just as loudly,
        what it does not.
      </p>
      {error ? <p className="error-note">{error}</p> : null}
      {report?.gaps.map((gap) => (
        <p className="error-note" key={`${gap.property_id}-${gap.domain}`}>
          {gap.message}
        </p>
      ))}
      {report?.properties.map((property) => (
        <section className="section" key={property.property_id}>
          <h2 className="section__title">
            {property.label} — resolved to {property.resolution.chain[0] ?? property.state}
          </h2>
          <div className="card card--flush">
            <table className="table">
              <thead>
                <tr>
                  <th>Rule domain</th>
                  <th>Status</th>
                  <th>Source</th>
                  <th>Authority</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(property.domains).map(([domain, coverage]) => (
                  <tr key={domain}>
                    <td>{titleCase(domain)}</td>
                    <td>
                      {coverage.status === 'covered' ? (
                        <span className="pill pill--ok">covered</span>
                      ) : (
                        <span className="pill">no rules loaded</span>
                      )}
                    </td>
                    <td className="muted">{coverage.source ?? '—'}</td>
                    <td>
                      {coverage.citation ? (
                        <span className="citation">{coverage.citation}</span>
                      ) : (
                        <span className="faint">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </>
  );
}
