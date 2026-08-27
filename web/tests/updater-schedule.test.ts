import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PERIODIC_CHECK_INTERVAL_MS,
  scheduleAutomaticChecks,
  STARTUP_CHECK_DELAY_MS,
} from "../src/updater/schedule";

afterEach(() => vi.useRealTimers());

describe("desktop updater schedule", () => {
  it("checks after startup and daily until disposed", () => {
    vi.useFakeTimers();
    const check = vi.fn();
    const dispose = scheduleAutomaticChecks(check);
    vi.advanceTimersByTime(STARTUP_CHECK_DELAY_MS);
    expect(check).toHaveBeenCalledWith("startup");
    vi.advanceTimersByTime(PERIODIC_CHECK_INTERVAL_MS);
    expect(check).toHaveBeenCalledWith("periodic");
    dispose();
    vi.advanceTimersByTime(PERIODIC_CHECK_INTERVAL_MS);
    expect(check).toHaveBeenCalledTimes(2);
  });
});
