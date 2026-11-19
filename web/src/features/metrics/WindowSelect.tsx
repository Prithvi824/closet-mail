import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const WINDOWS = [7, 30, 90];

interface WindowSelectProps {
  days: number;
  onChange: (days: number) => void;
}

/** Picks the reporting window: last 7, 30 or 90 days. */
export function WindowSelect({ days, onChange }: WindowSelectProps) {
  return (
    <Select value={String(days)} onValueChange={(value) => onChange(Number(value))}>
      <SelectTrigger aria-label="Time window" className="w-36">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {WINDOWS.map((window) => (
          <SelectItem key={window} value={String(window)}>
            Last {window} days
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
