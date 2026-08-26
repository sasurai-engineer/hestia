import type { HazardOut } from '../lib/api';
import { titleCase } from '../lib/format';

export function HazardCard({ hazard }: { hazard: HazardOut }) {
  const sfha = hazard.in_special_flood_hazard_area;
  return (
    <div className="card">
      <strong>{titleCase(hazard.kind)}</strong>
      <p>
        Zone {hazard.zone ?? 'unmapped'}
        {sfha === null ? null : (
          <span className={sfha ? 'pill pill--failed' : 'pill pill--ok'} style={{ marginLeft: 10 }}>
            {sfha ? 'in the special flood hazard area' : 'outside the SFHA'}
          </span>
        )}
      </p>
      {hazard.base_flood_elevation_ft != null ? (
        <p className="muted">Base flood elevation {hazard.base_flood_elevation_ft} ft</p>
      ) : null}
    </div>
  );
}
