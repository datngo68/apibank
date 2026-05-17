import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { endpoints, type AuthMeResponse } from "@/lib/api";

export const AUTH_QUERY_KEY = ["auth", "me"] as const;

export function useAuth() {
  return useQuery<AuthMeResponse | null>({
    queryKey: AUTH_QUERY_KEY,
    queryFn: async () => {
      try {
        const res = await endpoints.me();
        return res.data;
      } catch (err) {
        const status = (err as { response?: { status?: number } }).response?.status ?? 0;
        if (status === 401) return null;
        throw err;
      }
    },
    staleTime: 30_000,
    retry: false,
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => endpoints.logout(),
    onSettled: () => {
      qc.setQueryData(AUTH_QUERY_KEY, null);
      qc.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
    },
  });
}
