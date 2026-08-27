import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { relaunch } from "@tauri-apps/plugin-process";
import {
  check as checkForTauriUpdate,
  type DownloadEvent,
  type Update,
} from "@tauri-apps/plugin-updater";

import { createHttpRuntime } from "./httpRuntime";
import type {
  DocEvidenceRuntime,
  HostCapabilities,
  NativeCollectionOperation,
  NativeLibraryOperation,
} from "./runtime";
import type {
  DesktopUpdateRuntime,
  UpdateCheckReason,
  UpdateDownloadEvent,
} from "../updater/runtime";

const desktopProtocol = "doc-evidence.desktop.v1";
const tokenPattern = /^[0-9a-f]{64}$/;
type DesktopPlatform = "macos" | "windows";
type DesktopArchitecture = "arm64" | "x86_64";

interface DesktopRuntimeInfo {
  readonly baseUrl: string;
  readonly bearerToken: string;
  readonly protocolVersion: string;
  readonly applicationVersion: string;
  readonly apiVersion: 1;
  readonly platform: DesktopPlatform;
  readonly architecture: DesktopArchitecture;
  readonly baselinePack: {
    readonly packId: string;
    readonly version: string;
    readonly manifestSha256: string;
  } | null;
  readonly hostCapabilities: HostCapabilities;
}

interface DesktopHandshake {
  readonly schema_version: "doc-evidence.desktop-handshake.v1";
  readonly compatible: true;
  readonly protocol_version: "doc-evidence.desktop.v1";
  readonly application_version: string;
  readonly api_version: 1;
  readonly platform: DesktopPlatform;
  readonly architecture: DesktopArchitecture;
  readonly application_home_source: "environment" | "desktop_host" | "platform_default";
  readonly baseline_pack: {
    readonly pack_id: string;
    readonly version: string;
    readonly manifest_sha256: string;
  } | null;
  readonly capabilities: string[];
}

export interface DesktopBridge {
  invoke<T>(command: string, arguments_?: Record<string, unknown>): Promise<T>;
  listen<T>(event: string, callback: (payload: T) => void): Promise<UnlistenFn>;
}

const tauriBridge: DesktopBridge = {
  invoke: (command, arguments_) => invoke(command, arguments_),
  listen: <T,>(event: string, callback: (payload: T) => void) =>
    listen<T>(event, (message) => callback(message.payload)),
};

export interface DesktopRuntimeBootstrap {
  readonly runtime: DocEvidenceRuntime;
  readonly updater: DesktopUpdateRuntime;
  monitor(onFailure: (message: string) => void): Promise<UnlistenFn>;
}

function createTauriUpdateRuntime(): DesktopUpdateRuntime {
  let current: Update | null = null;
  const close = async () => {
    const candidate = current;
    current = null;
    if (candidate) await candidate.close();
  };
  return {
    async check(reason: UpdateCheckReason) {
      await close();
      current = await checkForTauriUpdate({
        headers: { "X-Check-Reason": reason },
        timeout: 20_000,
      });
      if (!current) return null;
      return { version: current.version, notes: current.body };
    },
    async install(onEvent: (event: UpdateDownloadEvent) => void) {
      if (!current) throw new Error("No signed update is ready to install.");
      await current.downloadAndInstall((event: DownloadEvent) => {
        if (event.event === "Started") {
          onEvent({ phase: "started", totalBytes: event.data.contentLength });
        } else if (event.event === "Progress") {
          onEvent({ phase: "progress", chunkBytes: event.data.chunkLength });
        } else {
          onEvent({ phase: "finished" });
        }
      });
    },
    relaunch,
    close,
  };
}

function validateRuntimeInfo(value: DesktopRuntimeInfo): DesktopRuntimeInfo {
  const baseUrl = new URL(value.baseUrl);
  if (
    baseUrl.protocol !== "http:" ||
    baseUrl.hostname !== "127.0.0.1" ||
    !baseUrl.port ||
    baseUrl.pathname !== "/" ||
    baseUrl.search ||
    baseUrl.hash
  ) {
    throw new Error("The desktop engine returned an invalid loopback address.");
  }
  if (
    value.protocolVersion !== desktopProtocol ||
    value.apiVersion !== 1 ||
    !(
      (value.platform === "macos" && value.architecture === "arm64") ||
      (value.platform === "windows" && value.architecture === "x86_64")
    ) ||
    !value.applicationVersion ||
    !tokenPattern.test(value.bearerToken) ||
    typeof value.hostCapabilities?.createManagedLibrary !== "boolean" ||
    typeof value.hostCapabilities?.registerExistingLibrary !== "boolean" ||
    typeof value.hostCapabilities?.addCollection !== "boolean"
  ) {
    throw new Error("The desktop engine compatibility record is invalid.");
  }
  if (
    value.baselinePack !== null &&
    (!value.baselinePack.packId ||
      !value.baselinePack.version ||
      !tokenPattern.test(value.baselinePack.manifestSha256))
  ) {
    throw new Error("The desktop extractor-pack record is invalid.");
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function compatiblePack(value: unknown, info: DesktopRuntimeInfo): boolean {
  if (info.baselinePack === null) return value === null;
  return (
    isRecord(value) &&
    Object.keys(value).length === 3 &&
    value.pack_id === info.baselinePack.packId &&
    value.version === info.baselinePack.version &&
    value.manifest_sha256 === info.baselinePack.manifestSha256
  );
}

function validateHandshake(value: unknown, info: DesktopRuntimeInfo): DesktopHandshake {
  if (!isRecord(value)) {
    throw new Error("The desktop handshake is invalid.");
  }
  const keys = new Set(Object.keys(value));
  const expected = [
    "schema_version",
    "compatible",
    "protocol_version",
    "application_version",
    "api_version",
    "platform",
    "architecture",
    "application_home_source",
    "baseline_pack",
    "capabilities",
  ];
  if (
    keys.size !== expected.length ||
    expected.some((key) => !keys.has(key)) ||
    value.schema_version !== "doc-evidence.desktop-handshake.v1" ||
    value.compatible !== true ||
    value.protocol_version !== desktopProtocol ||
    value.application_version !== info.applicationVersion ||
    value.api_version !== info.apiVersion ||
    value.platform !== info.platform ||
    value.architecture !== info.architecture ||
    !["environment", "desktop_host", "platform_default"].includes(
      String(value.application_home_source),
    ) ||
    !Array.isArray(value.capabilities) ||
    value.capabilities.some((capability) => typeof capability !== "string") ||
    !compatiblePack(value.baseline_pack, info) ||
    ((info.hostCapabilities.createManagedLibrary ||
      info.hostCapabilities.registerExistingLibrary ||
      info.hostCapabilities.addCollection) &&
      !value.capabilities.includes("native_library_authorization"))
  ) {
    throw new Error("The desktop handshake is incompatible.");
  }
  return value as unknown as DesktopHandshake;
}

async function authenticatedHandshake(info: DesktopRuntimeInfo): Promise<DesktopHandshake> {
  const response = await fetch(`${info.baseUrl}/api/v1/desktop/handshake`, {
    headers: { Authorization: `Bearer ${info.bearerToken}` },
    referrerPolicy: "no-referrer",
  });
  if (!response.ok) {
    throw new Error(`The desktop engine rejected its handshake (${response.status}).`);
  }
  return validateHandshake(await response.json(), info);
}

export async function createDesktopRuntime(
  bridge: DesktopBridge = tauriBridge,
): Promise<DesktopRuntimeBootstrap> {
  const info = validateRuntimeInfo(
    await bridge.invoke<DesktopRuntimeInfo>("desktop_runtime"),
  );
  await authenticatedHandshake(info);
  const http = createHttpRuntime(info.baseUrl, info.bearerToken);
  const runtime: DocEvidenceRuntime = {
    ...http,
    hostCapabilities: info.hostCapabilities,
    createManagedLibrary: () =>
      bridge.invoke<NativeLibraryOperation>("desktop_create_managed_library"),
    registerExistingLibrary: () =>
      bridge.invoke<NativeLibraryOperation>("desktop_register_existing_library"),
    addCollection: (libraryId) =>
      bridge.invoke<NativeCollectionOperation>("desktop_add_collection", {
        libraryId,
      }),
  };
  return {
    runtime,
    updater: createTauriUpdateRuntime(),
    monitor: (onFailure) =>
      bridge.listen<string>("desktop-runtime-failed", onFailure),
  };
}
