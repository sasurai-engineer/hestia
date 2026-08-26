import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  // Next's compiler wants tsconfig `jsx: preserve`; the Vite 8 (oxc)
  // transform must emit automatic-runtime JSX for tests instead.
  oxc: { jsx: { runtime: 'automatic' } },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
    coverage: {
      provider: 'v8',
      // Pages and the form are exercised end-to-end against the running
      // stack (Playwright — carried item); the unit bar covers everything
      // pure: the client, the display arithmetic, and the components.
      include: ['src/lib/**/*.ts', 'src/components/**/*.tsx'],
      exclude: ['src/lib/api-schema.d.ts', 'src/components/PropertyForm.tsx'],
      thresholds: { lines: 100, branches: 100, functions: 100, statements: 100 },
    },
  },
});
