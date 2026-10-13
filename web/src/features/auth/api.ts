import { startAuthentication, type PublicKeyCredentialRequestOptionsJSON } from "@simplewebauthn/browser";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { LoginResponse, Me } from "@/lib/api";
import { http } from "@/lib/http";

export const ME_KEY = ["me"] as const;

export interface Credentials {
  username: string;
  password: string;
}

export interface InviteAcceptInput {
  token: string;
  username: string;
  password: string;
}

/** The signed-in user; errors with 401 when there is no (fully authenticated) session. */
export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: async () => (await http.get<Me>("/me")).data,
    staleTime: 60_000,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: Credentials) =>
      (await http.post<LoginResponse>("/auth/login", input)).data,
    onSuccess: (result) => {
      if (!result.mfa_required) void queryClient.invalidateQueries({ queryKey: ME_KEY });
    },
  });
}

export function useTotpLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (code: string) => {
      await http.post("/auth/totp", { code });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ME_KEY }),
  });
}

/** Second factor with a passkey: get options, let the browser sign, send the assertion. */
export function usePasskeyLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const begin = await http.post<{ options: PublicKeyCredentialRequestOptionsJSON }>("/auth/webauthn/begin");
      const credential = await startAuthentication({ optionsJSON: begin.data.options });
      await http.post("/auth/webauthn/finish", { credential });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ME_KEY }),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await http.post("/auth/logout");
    },
    onSettled: () => queryClient.clear(),
  });
}

export function useAcceptInvite() {
  return useMutation({
    mutationFn: async (input: InviteAcceptInput) =>
      (await http.post<{ username: string }>("/auth/invite/accept", input)).data,
  });
}

export function useRequestReset() {
  return useMutation({
    mutationFn: async (email: string) => {
      await http.post("/auth/password-reset/request", { email });
    },
  });
}

export function useConfirmReset() {
  return useMutation({
    mutationFn: async (input: { token: string; password: string }) => {
      await http.post("/auth/password-reset/confirm", input);
    },
  });
}
