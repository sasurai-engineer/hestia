import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      all: true,
      include: ['src/**/*.ts'],
      // Barrel files re-export only; they carry no branches worth asserting.
      exclude: ['src/**/*.test.ts', 'src/index.ts'],
      reporter: ['text', 'lcov', 'json-summary'],
      // The floor. The mutation score in stryker.config.json is the real bar.
      thresholds: { lines: 100, branches: 100, functions: 100, statements: 100 },
    },
  },
});
