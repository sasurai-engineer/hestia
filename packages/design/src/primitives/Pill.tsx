import type { ReactNode } from 'react';

export type PillTone = 'neutral' | 'ok' | 'skipped' | 'failed' | 'flag';

const TONE_CLASS: Record<PillTone, string> = {
  neutral: 'pill',
  ok: 'pill pill--ok',
  skipped: 'pill pill--skipped',
  failed: 'pill pill--failed',
  flag: 'pill pill--flag',
};

export function Pill({ tone = 'neutral', children }: { tone?: PillTone; children: ReactNode }) {
  return <span className={TONE_CLASS[tone]}>{children}</span>;
}
