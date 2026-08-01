import { useQuery } from "@tanstack/react-query";

import { useRuntime } from "./RuntimeProvider";

export function useJobsQuery(libraryId: string | null) {
  const runtime = useRuntime();
  return useQuery({
    queryKey: ["library", libraryId, "jobs"],
    queryFn: ({ signal }) => runtime.listJobs(libraryId!, undefined, 0, 200, signal),
    enabled: libraryId !== null,
    refetchInterval: (query) => {
      const counts = query.state.data?.counts;
      return counts && (counts.active > 0 || counts.queued > 0) ? 1_000 : 5_000;
    },
  });
}
