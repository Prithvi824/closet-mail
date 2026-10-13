import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ME_KEY } from "@/features/auth/api";
import type { Me, SettingsUpdate } from "@/lib/api";
import { http } from "@/lib/http";

export function useUpdateSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (changes: SettingsUpdate) => (await http.patch<Me>("/me/settings", changes)).data,
    onSuccess: (me) => {
      queryClient.setQueryData(ME_KEY, me);
      // The default recipient is shown on the recipients list too.
      return queryClient.invalidateQueries({ queryKey: ["recipients"] });
    },
  });
}

export function useTotpSetup() {
  return useMutation({
    mutationFn: async () => (await http.post<{ otpauth_uri: string }>("/me/totp/setup")).data,
  });
}

export function useTotpEnable() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (code: string) =>
      (await http.post<{ backup_codes: string[] }>("/me/totp/enable", { code })).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ME_KEY }),
  });
}

export function useTotpDisable() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (password: string) => {
      await http.delete("/me/totp", { data: { password } });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ME_KEY }),
  });
}
