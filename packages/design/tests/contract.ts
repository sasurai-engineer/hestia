import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/** Shared access to the token contract for the law tests. */

export const ROOT = join(__dirname, '..');

export type TokenEntry = { $value: string; $description: string };
export type ContrastPair = { fg: string; bg: string; ratio: number; floor: number };
type ContrastBlock = { $description: string; pairs: ContrastPair[] };

type Contract = Record<string, unknown> & { $contrast: ContrastBlock };

const contract = JSON.parse(
  readFileSync(join(ROOT, 'tokens/hestia-tokens.json'), 'utf8'),
) as Contract;

export const tokenEntries = Object.entries(contract).filter(
  (entry): entry is [string, TokenEntry] => !entry[0].startsWith('$'),
);

export const tokenValues = new Map(tokenEntries.map(([name, entry]) => [name, entry.$value]));

export const contrastPairs = contract.$contrast.pairs;
