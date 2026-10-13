import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

export interface CheckOption {
  value: string;
  label: string;
  hint?: string;
  disabled?: boolean;
}

interface CheckListProps {
  /** Prefix for element ids (must be unique on the page). */
  idPrefix: string;
  options: CheckOption[];
  selected: string[];
  onChange: (selected: string[]) => void;
  emptyText?: string;
}

/** Multi-select as a list of checkboxes (recipients, labels). */
export function CheckList({ idPrefix, options, selected, onChange, emptyText }: CheckListProps) {
  function toggle(value: string, checked: boolean) {
    onChange(checked ? [...selected, value] : selected.filter((item) => item !== value));
  }

  if (options.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyText ?? "Nothing to choose."}</p>;
  }
  return (
    <div className="flex flex-col gap-2">
      {options.map((option) => {
        const id = `${idPrefix}-${option.value}`;
        return (
          <div key={option.value} className="flex items-center gap-2">
            <Checkbox
              id={id}
              checked={selected.includes(option.value)}
              disabled={option.disabled}
              onCheckedChange={(checked) => toggle(option.value, checked === true)}
            />
            <Label htmlFor={id} className="font-normal">
              {option.label}
              {option.hint ? <span className="text-muted-foreground"> · {option.hint}</span> : null}
            </Label>
          </div>
        );
      })}
    </div>
  );
}
