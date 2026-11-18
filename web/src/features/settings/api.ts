import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ME_KEY } from "@/features/auth/api";
import { http } from "@/lib/http";

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
