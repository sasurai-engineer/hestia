/**
 * The stamp: statutory authority pressed into the paper. Survey-blue belongs
 * to citations alone, so this is the one component allowed to wear it.
 */
export function CitationChip({ cite, detail }: { cite: string; detail?: string | undefined }) {
  return (
    <span className="citation-chip" title={detail ?? cite}>
      {cite}
    </span>
  );
}
