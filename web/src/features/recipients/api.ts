import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ME_KEY } from "@/features/auth/api";
import type { Recipient } from "@/lib/api";
import { http } from "@/lib/http";

export const RECIPIENTS_KEY = ["recipients"] as const;

export interface PgpInput {
  id: string;
  public_key: string | null;
  protect_subject: boolean;
}

export function useRecipients() {
  return useQuery({
    queryKey: RECIPIENTS_KEY,
    queryFn: async () => (await http.get<Recipient[]>("/recipients")).data,
  });
}

function useRecipientMutation<TInput>(request: (input: TInput) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RECIPIENTS_KEY }),
  });
}

export function useAddRecipient() {
  return useRecipientMutation((email: string) => http.post<Recipient>("/recipients", { email }));
}

/** Disabling or deleting may move the default recipient, so the profile is refreshed too. */
function useRecipientRemovalMutation<TInput>(request: (input: TInput) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: RECIPIENTS_KEY }),
        queryClient.invalidateQueries({ queryKey: ME_KEY }),
      ]),
  });
}

export function useSetRecipientDisabled() {
  return useRecipientRemovalMutation((input: { id: string; disabled: boolean }) =>
    http.patch<Recipient>(`/recipients/${input.id}`, { disabled: input.disabled }),
  );
}

export function useDeleteRecipient() {
  return useRecipientRemovalMutation((id: string) => http.delete(`/recipients/${id}`));
}

export function useResendVerification() {
  return useMutation({
    mutationFn: (id: string) => http.post(`/recipients/${id}/resend-verification`),
  });
}

export function useSetPgpKey() {
  return useRecipientMutation((input: PgpInput) =>
    http.put<Recipient>(`/recipients/${input.id}/pgp`, {
      public_key: input.public_key,
      protect_subject: input.protect_subject,
    }),
  );
}
