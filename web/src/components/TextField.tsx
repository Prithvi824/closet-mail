import type { ComponentProps, ReactNode } from "react";

import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

interface TextFieldProps extends ComponentProps<typeof Input> {
  id: string;
  label: string;
  /** Validation message for this field, if any. */
  error?: string;
  description?: ReactNode;
}

/** Labelled input with description and error text; spread react-hook-form's register() into it. */
export function TextField({ id, label, error, description, ...inputProps }: TextFieldProps) {
  return (
    <Field data-invalid={error ? true : undefined}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input id={id} aria-invalid={error ? true : undefined} {...inputProps} />
      {description ? <FieldDescription>{description}</FieldDescription> : null}
      {error ? <FieldError>{error}</FieldError> : null}
    </Field>
  );
}
