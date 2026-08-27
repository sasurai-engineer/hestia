/**
 * Case-insensitive subsequence match — the palette's whole search engine.
 * "brs" finds "burst pipe"; the empty query finds everything. Deliberately
 * not scored: with a command list this small, order is the caller's business
 * and a ranking model is a dependency wearing a disguise.
 */
export function fuzzyMatch(query: string, candidate: string): boolean {
  const wanted = query.toLowerCase();
  const haystack = candidate.toLowerCase();
  let found = 0;
  for (const character of haystack) {
    // Once the query is consumed, wanted[found] is undefined and never
    // matches — a bounds guard here would be redundant state.
    if (character === wanted[found]) {
      found += 1;
    }
  }
  return found === wanted.length;
}
