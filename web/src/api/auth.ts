export class LaunchAuthenticationError extends Error {}

export function consumeLaunchToken(
  location: Pick<Location, "hash" | "pathname" | "search"> = window.location,
  history: Pick<History, "replaceState"> = window.history,
): string {
  const fragment = new URLSearchParams(location.hash.replace(/^#/, ""));
  const token = fragment.get("token");
  if (!token) {
    throw new LaunchAuthenticationError(
      "This application must be opened by `doc-evidence serve`; no launch credential was present.",
    );
  }
  history.replaceState(null, "", `${location.pathname}${location.search}`);
  return token;
}
