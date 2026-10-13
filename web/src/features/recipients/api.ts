import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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

export function useSetRecipientDisabled() {
  return useRecipientMutation((input: { id: string; disabled: boolean }) =>
    http.patch<Recipient>(`/recipients/${input.id}`, { disabled: input.disabled }),
  );
}

export function useDeleteRecipient() {
  return useRecipientMutation((id: string) => http.delete(`/recipients/${id}`));
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
