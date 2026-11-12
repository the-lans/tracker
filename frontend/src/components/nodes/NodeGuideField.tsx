import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Раздел 5: гайд «Обычного промта» — значение переменной `{{node.guide_url}}`. */
export function NodeGuideField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <Label htmlFor="node-guide">Гайд (URL Confluence)</Label>
      <Input id="node-guide" value={value} onChange={(e) => onChange(e.target.value)} />
      <p className="mt-1 text-small text-text-3">В тексте промта — {"{{node.guide_url}}"}.</p>
    </div>
  );
}
