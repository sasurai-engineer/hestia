import type { ChainLink } from '../lib/api';

/**
 * The governing-body walk, most specific first. An empty chain is shown as
 * exactly what it is — no pack loaded — never guessed around.
 */
export function JurisdictionChain({ chain }: { chain: ChainLink[] }) {
  if (chain.length === 0) {
    return (
      <p className="muted">
        No jurisdiction pack covers this property yet — rules and deadlines are not generated for
        it, and that gap is reported, not hidden.
      </p>
    );
  }
  return (
    <p>
      {chain.map((link, index) => (
        <span key={link.name}>
          {index > 0 ? <span className="faint"> → </span> : null}
          <span>{link.name}</span> <span className="faint">({link.level})</span>
        </span>
      ))}
    </p>
  );
}
