import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useSubdomainLabel } from "@/features/subdomains/useSubdomainLabel";
import type { Recipient } from "@/lib/api";
import { http } from "@/lib/http";
import { sub } from "@/lib/paths";

export const recipientsKey = (label: string) => ["s", label, "recipients"] as const;

export interface PgpInput {
  id: string;
  public_key: string | null;
  protect_subject: boolean;
}

export function useRecipients() {
  const label = useSubdomainLabel();
  return useQuery({
    queryKey: recipientsKey(label),
    queryFn: async () => (await http.get<Recipient[]>(sub(label, "/recipients"))).data,
  });
}

function useRecipientMutation<TInput>(label: string, request: (input: TInput) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: recipientsKey(label) }),
  });
}

export function useAddRecipient() {
  const label = useSubdomainLabel();
  return useRecipientMutation(label, (email: string) => http.post<Recipient>(sub(label, "/recipients"), { email }));
}

export function useSetRecipientDisabled() {
  const label = useSubdomainLabel();
  return useRecipientMutation(label, (input: { id: string; disabled: boolean }) =>
    http.patch<Recipient>(sub(label, `/recipients/${input.id}`), { disabled: input.disabled }),
  );
}

export function useSetRecipientDefault() {
  const label = useSubdomainLabel();
  return useRecipientMutation(label, (input: { id: string; forward_by_default: boolean }) =>
    http.patch<Recipient>(sub(label, `/recipients/${input.id}`), { forward_by_default: input.forward_by_default }),
  );
}

export function useDeleteRecipient() {
  const label = useSubdomainLabel();
  return useRecipientMutation(label, (id: string) => http.delete(sub(label, `/recipients/${id}`)));
}

export function useResendVerification() {
  const label = useSubdomainLabel();
  return useMutation({
    mutationFn: (id: string) => http.post(sub(label, `/recipients/${id}/resend-verification`)),
  });
}

export function useSetPgpKey() {
  const label = useSubdomainLabel();
  return useRecipientMutation(label, (input: PgpInput) =>
    http.put<Recipient>(sub(label, `/recipients/${input.id}/pgp`), {
      public_key: input.public_key,
      protect_subject: input.protect_subject,
    }),
  );
}
