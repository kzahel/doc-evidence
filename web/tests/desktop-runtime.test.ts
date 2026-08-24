import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createDesktopRuntime,
  type DesktopBridge,
} from "../src/api/desktopRuntime";

const token = "a".repeat(64);

function bridge(overrides: Record<string, unknown> = {}): DesktopBridge {
  return {
    invoke: vi.fn(async (command: string) => {
      if (command === "desktop_runtime") {
        return {
          baseUrl: "http://127.0.0.1:43111",
          bearerToken: token,
          protocolVersion: "doc-evidence.desktop.v1",
          applicationVersion: "0.4.0",
          apiVersion: 1,
          platform: "macos",
          architecture: "arm64",
          baselinePack: null,
          hostCapabilities: {
            createManagedLibrary: true,
            registerExistingLibrary: true,
            addCollection: true,
          },
          ...overrides,
        };
      }
      if (command === "desktop_create_managed_library") {
        return { outcome: "cancelled", libraryId: null, status: null };
      }
      throw new Error(`unexpected command: ${command}`);
    }) as DesktopBridge["invoke"],
    listen: vi.fn(async () => () => undefined) as DesktopBridge["listen"],
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("desktop runtime bootstrap", () => {
  it("validates an authenticated loopback handshake and keeps host paths native", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.headers).toEqual({ Authorization: `Bearer ${token}` });
      return new Response(
        JSON.stringify({
          schema_version: "doc-evidence.desktop-handshake.v1",
          compatible: true,
          protocol_version: "doc-evidence.desktop.v1",
          application_version: "0.4.0",
          api_version: 1,
          platform: "macos",
          architecture: "arm64",
          application_home_source: "desktop_host",
          baseline_pack: null,
          capabilities: [
            "known_libraries",
            "durable_extraction_jobs",
            "native_library_authorization",
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const nativeBridge = bridge();

    const desktop = await createDesktopRuntime(nativeBridge);
    expect(desktop.runtime.hostCapabilities.createManagedLibrary).toBe(true);
    expect(await desktop.runtime.createManagedLibrary()).toEqual({
      outcome: "cancelled",
      libraryId: null,
      status: null,
    });
    expect(nativeBridge.invoke).toHaveBeenCalledWith(
      "desktop_create_managed_library",
    );
    expect(fetchMock.mock.calls[0]?.[0]).not.toContain(token);
  });

  it("rejects remote, token-bearing, or incompatible bootstrap records", async () => {
    vi.stubGlobal("fetch", vi.fn());
    await expect(
      createDesktopRuntime(bridge({ baseUrl: `https://example.test/#${token}` })),
    ).rejects.toThrow("invalid loopback address");
    await expect(
      createDesktopRuntime(bridge({ bearerToken: "too-short" })),
    ).rejects.toThrow("compatibility record is invalid");
    await expect(
      createDesktopRuntime(bridge({ platform: "windows", architecture: "arm64" })),
    ).rejects.toThrow("compatibility record is invalid");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("accepts the exact Windows x86_64 runtime and handshake pair", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            schema_version: "doc-evidence.desktop-handshake.v1",
            compatible: true,
            protocol_version: "doc-evidence.desktop.v1",
            application_version: "0.4.0",
            api_version: 1,
            platform: "windows",
            architecture: "x86_64",
            application_home_source: "desktop_host",
            baseline_pack: null,
            capabilities: [
              "known_libraries",
              "durable_extraction_jobs",
              "native_library_authorization",
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const desktop = await createDesktopRuntime(
      bridge({ platform: "windows", architecture: "x86_64" }),
    );

    expect(desktop.runtime.hostCapabilities.createManagedLibrary).toBe(true);
  });

  it("rejects extra handshake fields before creating the product runtime", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            schema_version: "doc-evidence.desktop-handshake.v1",
            compatible: true,
            protocol_version: "doc-evidence.desktop.v1",
            application_version: "0.4.0",
            api_version: 1,
            platform: "macos",
            architecture: "arm64",
            application_home_source: "desktop_host",
            baseline_pack: null,
            capabilities: [],
            leaked_path: "/private/example",
          }),
          { status: 200 },
        ),
      ),
    );
    await expect(createDesktopRuntime(bridge())).rejects.toThrow(
      "handshake is incompatible",
    );
  });
});
