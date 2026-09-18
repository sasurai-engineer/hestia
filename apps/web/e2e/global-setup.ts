import { execFileSync } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Every e2e walk arrives authenticated (#40), the same way the API suites
 * do: the ceremony itself is exercised by test_auth.py with a software
 * authenticator, and the walks here test what lies BEHIND the door. A
 * session is seeded straight into the database (only its sha256 lands
 * there, exactly as the API stores it) and the raw token becomes a cookie
 * in Playwright's storage state. Cookies bind to hosts, not ports, so one
 * localhost cookie reaches both the web app (:3000) and the API (:8000).
 *
 * The login walk through /welcome and /login belongs to the web half of
 * #40 and will drive a WebAuthn virtual authenticator when those routes
 * exist.
 */
const databaseUrl =
  process.env.HESTIA_DATABASE_URL ?? 'postgresql://postgres:postgres@localhost:5432/hestia';

export default function globalSetup(): void {
  const token = randomBytes(32).toString('base64url');
  const digestHex = createHash('sha256').update(token).digest('hex');
  const seed = `
    INSERT INTO users (handle, role) VALUES ('e2e-owner', 'owner')
    ON CONFLICT (handle) DO NOTHING;
    INSERT INTO sessions (user_id, token_sha256, expires_at)
    SELECT id, decode('${digestHex}', 'hex'), now() + interval '4 hours'
    FROM users WHERE handle = 'e2e-owner';
  `;
  execFileSync('psql', [databaseUrl, '-v', 'ON_ERROR_STOP=1', '-q', '-c', seed], {
    stdio: ['ignore', 'inherit', 'inherit'],
  });

  const authDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '.auth');
  mkdirSync(authDir, { recursive: true });
  writeFileSync(
    path.join(authDir, 'storage-state.json'),
    JSON.stringify({
      cookies: [
        {
          name: 'hestia_session',
          value: token,
          domain: 'localhost',
          path: '/',
          expires: Math.floor(Date.now() / 1000) + 4 * 60 * 60,
          httpOnly: true,
          secure: false,
          sameSite: 'Strict',
        },
      ],
      origins: [],
    }),
  );
}
