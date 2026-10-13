import { CircleAlertIcon } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";

interface FormErrorProps {
  message?: string | null;
}

/** Form-level error banner (server errors); renders nothing without a message. */
export function FormError({ message }: FormErrorProps) {
  if (!message) return null;
  return (
    <Alert variant="destructive" role="alert">
      <CircleAlertIcon />
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}
