/**
 * Global test setup.
 * This file is referenced by vitest.config.ts → test.setupFiles.
 *
 * The canonical setup lives in ./test-utils/setup.ts which already
 * imports @testing-library/jest-dom/vitest and mocks browser APIs.
 * This file simply re-exports it so both entry points resolve to the
 * same setup logic.
 */
import "./test-utils/setup";
