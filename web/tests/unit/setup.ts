import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

// On a busy CI runner a screen can take longer than the 1 s default to show what a test waits for.
// A wait that finds its element returns at once; this only gives a slow one room before it fails.
configure({ asyncUtilTimeout: 4000 });
