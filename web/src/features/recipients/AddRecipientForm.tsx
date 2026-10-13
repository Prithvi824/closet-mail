import { zodResolver } from "@hookform/resolvers/zod";
import { PlusIcon } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Field, FieldError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useAddRecipient } from "@/features/recipients/api";
import { errorMessage } from "@/lib/http";

const addSchema = z.object({ email: z.email("Enter a valid email address") });
type AddValues = z.infer<typeof addSchema>;

/** Inline form: add a recipient; a verification link is emailed to it. */
export function AddRecipientForm() {
  const form = useForm<AddValues>({ resolver: zodResolver(addSchema) });
  const add = useAddRecipient();
  const error = form.formState.errors.email?.message ?? (add.error ? errorMessage(add.error) : undefined);

  async function submit(values: AddValues) {
    const ok = await add.mutateAsync(values.email).then(
      () => true,
      () => false,
    );
    if (!ok) return;
    toast.success(`Verification link sent to ${values.email}`);
    form.reset();
  }

  return (
    <form onSubmit={form.handleSubmit(submit)} noValidate className="mb-4">
      <Field data-invalid={error ? true : undefined}>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            type="email"
            aria-label="New recipient address"
            placeholder="another-inbox@example.com"
            aria-invalid={error ? true : undefined}
            {...form.register("email", { onChange: () => add.reset() })}
          />
          <Button type="submit" disabled={add.isPending}>
            <PlusIcon /> Add recipient
          </Button>
        </div>
        {error ? <FieldError>{error}</FieldError> : null}
      </Field>
    </form>
  );
}
