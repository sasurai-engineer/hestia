import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { ROOT, tokenEntries } from './contract.js';

/**
 * The brand laws as tests, promoted to where the livery now lives. The token
 * contract is tokens/hestia-tokens.json; src/css is held to it verbatim, and
 * the consultancy that built the product may never leak into the package —
 * the un-borrowing is a permanent test, not a cleanup.
 */
const CSS_DIR = join(ROOT, 'src/css');

const cssFiles = readdirSync(CSS_DIR)
  .filter((name) => name.endsWith('.css'))
  .map((name) => [name, readFileSync(join(CSS_DIR, name), 'utf8')] as const);

const allCss = cssFiles.map(([, content]) => content).join('\n');
const stripped = (content: string) => content.replaceAll(/\/\*[\s\S]*?\*\//g, '');

describe('the css holds to the token contract', () => {
  const tokensCss = stripped(readFileSync(join(CSS_DIR, 'tokens.css'), 'utf8'));

  for (const [name, entry] of tokenEntries) {
    it(`--${name} is ${entry.$value}`, () => {
      expect(tokensCss).toContain(`--${name}: ${entry.$value};`);
    });
  }

  it('never uses pure white or pure black in declarations', () => {
    // Comments may TALK about them; declarations may not use them.
    // Lookbehind: token NAMES like hearth-white are legal; the color is not.
    const declarations = stripped(allCss);
    expect(declarations).not.toMatch(/#fff\b|#ffffff\b|(?<!-)\bwhite\b/i);
    expect(declarations).not.toMatch(/#000\b|#000000\b|(?<!-)\bblack\b/i);
  });

  it('sets Hestia in its own faces: Bitter, IBM Plex Sans, IBM Plex Mono', () => {
    expect(allCss).toMatch(/--serif:[^;]*Bitter/);
    expect(allCss).toMatch(/--sans:[^;]*IBM Plex Sans/);
    expect(allCss).toMatch(/--mono:[^;]*IBM Plex Mono/);
  });
});

describe('light is the law, and motion speaks in tokens', () => {
  it('commits to daylight paper: color-scheme light, no scheme media queries', () => {
    const base = readFileSync(join(CSS_DIR, 'base.css'), 'utf8');
    expect(base).toContain('color-scheme: light;');
    expect(allCss).not.toContain('prefers-color-scheme');
  });

  it('allows raw time literals only on the --dur scale itself', () => {
    for (const [name, content] of cssFiles) {
      const offenders = stripped(content)
        .split(';')
        .filter((declaration) => /\b\d+(?:\.\d+)?m?s\b/.test(declaration))
        .filter((declaration) => !/^--dur-\d+:/.test(declaration.trim()));
      expect(offenders, `raw duration in ${name}`).toEqual([]);
    }
  });

  it('allows z-index only through the --layer scale', () => {
    const offenders = stripped(allCss)
      .split(';')
      .filter((declaration) => declaration.includes('z-index'))
      .filter((declaration) => !declaration.includes('var(--layer-'));
    expect(offenders).toEqual([]);
  });
});

describe('the package carries no consultancy identity', () => {
  const BANNED_HEXES = [
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
  // The consultancy's site is set in its own faces over system serif/mono
  // stacks; none of those faces may be named anywhere in this package.
  // (\bInter\b is case-sensitive on purpose: 'pointer' is innocent.)
  const BANNED_FACES = [
    /Fraunces/i,
    /\bInter\b/,
    /Iowan Old Style/i,
    /Palatino/i,
    /SF Pro/i,
    /SF Mono/i,
    /\bMenlo\b/i,
    /Cascadia/i,
  ];

  const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((name) => {
      const path = join(dir, name);
      return statSync(path).isDirectory() ? walk(path) : [path];
    });

  for (const file of [...walk(join(ROOT, 'src')), ...walk(join(ROOT, 'tokens'))]) {
    const relative = file.slice(ROOT.length + 1);
    it(`${relative} carries only Hestia's identity`, () => {
      const content = readFileSync(file, 'utf8');
      expect(content.toLowerCase()).not.toContain('aletheia');
      for (const hex of BANNED_HEXES) {
        expect(content.toLowerCase(), `found ${hex}`).not.toContain(hex);
      }
      for (const face of BANNED_FACES) {
        expect(content, `found consultancy face ${String(face)}`).not.toMatch(face);
      }
    });
  }
});
