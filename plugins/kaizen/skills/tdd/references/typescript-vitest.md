# TypeScript + Vitest Reference

Language-specific patterns for TDD with TypeScript and Vitest.

## Test Runner Commands

```bash
# RED: watch mode for specific file
npx vitest tests/feature.test.ts

# GREEN: run with short output
npx vitest run tests/feature.test.ts

# REGRESSION: full suite, no watch
npx vitest run

# COVERAGE: check gaps locally
npx vitest run --coverage

# Quick count
npx vitest run --reporter=dot
```

## Mock Strategy — TypeScript/Vitest

### Monkeypatch via vi.mock (hoisted)

`vi.mock` is hoisted to the top of the file. Use `vi.importActual` for partial mocks.

```typescript
import { it, expect, vi, beforeEach } from 'vitest';

// Hoisted to top — runs before imports
vi.mock('../src/services', () => ({
  ExternalService: vi.fn().mockImplementation(() => ({
    process: vi.fn()
  }))
}));
```

### Tier 1.5: Contract-Safe Mocking

TypeScript enforces signature matching implicitly via type system:

```typescript
import { ExternalService } from '../src/services';

// TypeScript will error if mock doesn't match ExternalService interface
const mockService: jest.Mocked<ExternalService> = {
  process: vi.fn(),
  // Missing methods → compile error
};
```

### Route mock by content (multi-component flows)

```typescript
vi.mocked(callLLM).mockImplementation((prompt: string) => {
  if (prompt.includes('classify')) return Promise.resolve(CLASSIFICATION);
  if (prompt.includes('evaluate')) return Promise.resolve(EVALUATION);
  return Promise.resolve(DEFAULT);
});
```

### Local state reset

```typescript
beforeEach(() => {
  vi.clearAllMocks();
  process.env.API_KEY = 'test_key';
});

afterEach(() => {
  delete process.env.API_KEY;
});
```

### Global state cleanup

```typescript
// In vitest.setup.ts
afterEach(() => {
  // Reset any module-level singletons
  vi.restoreAllMocks();
});
```

## Stub Pattern for RED Phase

```typescript
// feature.test.ts
import { describe, it, expect } from 'vitest';

// If implementation doesn't exist yet, test will fail at import
// or use dynamic import with try/catch
let Processor: any;
try {
  const mod = await import('../src/processor');
  Processor = mod.Processor;
} catch {
  Processor = class {
    run(): never { throw new Error('TDD: Implement in src/processor.ts'); }
  };
}
```

## Async Test Patterns

### Concurrency verification

```typescript
it('should not exceed max concurrent calls', async () => {
  let current = 0;
  let peak = 0;

  const trackedFn = async () => {
    current++;
    peak = Math.max(peak, current);
    await new Promise(res => setTimeout(res, 10));
    current--;
  };

  await Promise.all([trackedFn(), trackedFn(), trackedFn()]);
  expect(peak).toBeLessThanOrEqual(3);
});
```

### Timer mocking

```typescript
import { vi, beforeEach, afterEach } from 'vitest';

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

it('debounces calls', async () => {
  const fn = vi.fn();
  const debounced = debounce(fn, 100);
  debounced();
  debounced();
  vi.advanceTimersByTime(100);
  expect(fn).toHaveBeenCalledOnce();
});
```

## Property-Based Testing (fast-check)

```typescript
import fc from 'fast-check';

it('decode(encode(val)) === val for all strings', () => {
  fc.assert(
    fc.property(fc.string(), (data) => {
      expect(decode(encode(data))).toBe(data);
    })
  );
});

it('sort preserves length', () => {
  fc.assert(
    fc.property(fc.array(fc.integer()), (arr) => {
      expect(mySort(arr)).toHaveLength(arr.length);
    })
  );
});
```

Install: `npm install -D fast-check`

## Mutation Testing (Stryker)

```bash
# Install
npm install -D @stryker-mutator/core @stryker-mutator/vitest-runner

# Init config
npx stryker init

# Run against specific module
npx stryker run --mutate 'src/mymodule.ts'

# View report
open reports/mutation/html/index.html
```

Target >90% mutation score on changed code.

## File System Hermeticity

```typescript
import { mkdtempSync, writeFileSync, readFileSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';

it('writes output to file', () => {
  const dir = mkdtempSync(join(tmpdir(), 'test-'));
  const file = join(dir, 'output.txt');
  writeFileSync(file, 'content');
  expect(readFileSync(file, 'utf-8')).toBe('content');
});
```

## Live Verification Pattern

```typescript
import { describe, it, expect } from 'vitest';

const BACKEND_AVAILABLE = await checkBackend().catch(() => false);

describe.skipIf(!BACKEND_AVAILABLE)('Live Integration', () => {
  it('connects to real endpoint', async () => {
    const result = await realApiCall('test');
    expect(result).toBeDefined();
  });
});
```
