import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * The brand laws as tests, app side. The token contract and the base voice
 * live in @hestia/design (with their own parity, purity, and contrast laws);
 * what the app answers for is how it SPENDS the livery: roles bound where
 * the law says, every color drawn through a token, and the consultancy that
 * built the product never leaking into it — the un-borrowing is a permanent
 * test, not a cleanup.
 */
const SRC = join(__dirname, '../src');
const css = readFileSync(join(SRC, 'app/globals.css'), 'utf8');

const walk = (dir: string): string[] =>
  readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });

describe('the app spends the livery lawfully', () => {
  it('reserves survey-blue for citations and ember for actions', () => {
    expect(css).toMatch(/\.citation\s*\{[^}]*var\(--survey-blue\)/);
    expect(css).toMatch(/\.button\s*\{[^}]*var\(--ember\)/);
  });

  it('never uses pure white or pure black in declarations', () => {
    const declarations = css.replaceAll(/\/\*[\s\S]*?\*\//g, '');
    expect(declarations).not.toMatch(/#fff\b|#ffffff\b|(?<!-)\bwhite\b/i);
    expect(declarations).not.toMatch(/#000\b|#000000\b|(?<!-)\bblack\b/i);
  });

  it('draws every color through a token: no raw hex in app stylesheets', () => {
    for (const file of walk(SRC).filter((path) => path.endsWith('.css'))) {
      const declarations = readFileSync(file, 'utf8').replaceAll(/\/\*[\s\S]*?\*\//g, '');
      expect(declarations, `raw hex in ${file.slice(SRC.length + 1)}`).not.toMatch(
        /#[0-9a-f]{3,8}\b/i,
      );
    }
  });
});

describe('the product carries no consultancy identity', () => {
  const ALETHEIA_HEXES = [
    '#0b1f33',
    '#0a0e14',
    '#1b2431',
    '#f6f3ea',
    '#e7c878',
    '#b99549',
    '#f7e3b0',
    '#7a5e2a',
    '#3fbfae',
  ];
  // The consultancy's site is set in Fraunces + Inter over system serif/mono
  // stacks; none of those faces may be named anywhere in this product.
  // (\bInter\b is case-sensitive on purpose: 'pointer' is innocent.)
  const ALETHEIA_FACES = [
    /Fraunces/i,
    /\bInter\b/,
    /Iowan Old Style/i,
    /Palatino/i,
    /SF Pro/i,
    /SF Mono/i,
    /\bMenlo\b/i,
    /Cascadia/i,
  ];

  for (const file of walk(SRC)) {
    if (file.endsWith('api-schema.d.ts') || file.endsWith('openapi.json')) continue;
    const relative = file.slice(SRC.length + 1);
    it(`${relative} is Aletheia-free`, () => {
      const content = readFileSync(file, 'utf8');
      expect(content.toLowerCase()).not.toContain('aletheia');
      for (const hex of ALETHEIA_HEXES) {
        expect(content.toLowerCase(), `found ${hex}`).not.toContain(hex);
      }
      for (const face of ALETHEIA_FACES) {
        expect(content, `found consultancy face ${String(face)}`).not.toMatch(face);
      }
    });
  }
});
