import { startRegistration, type PublicKeyCredentialCreationOptionsJSON } from "@simplewebauthn/browser";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { Passkey } from "@/lib/api";
import { http } from "@/lib/http";

export const PASSKEYS_KEY = ["passkeys"] as const;

export function usePasskeys() {
  return useQuery({
    queryKey: PASSKEYS_KEY,
    queryFn: async () => (await http.get<Passkey[]>("/me/webauthn")).data,
  });
}

/** Register a passkey: server options → browser ceremony → server verification. */
export function useRegisterPasskey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => {
      const begin = await http.post<{ options: PublicKeyCredentialCreationOptionsJSON }>(
        "/me/webauthn/register/begin",
      );
      const credential = await startRegistration({ optionsJSON: begin.data.options });
      return (await http.post<Passkey>("/me/webauthn/register/finish", { name, credential })).data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PASSKEYS_KEY }),
  });
}

export function useDeletePasskey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await http.delete(`/me/webauthn/${id}`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PASSKEYS_KEY }),
  });
}
