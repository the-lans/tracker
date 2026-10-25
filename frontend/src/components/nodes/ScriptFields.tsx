import { Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScriptLanguage } from "@/lib/types";

/** Script-нода: язык раннера и текст скрипта (правило 4 — без шаблонизации). */
export function ScriptFields({
  language,
  content,
  onLanguageChange,
  onContentChange,
}: {
  language: ScriptLanguage;
  content: string;
  onLanguageChange: (language: ScriptLanguage) => void;
  onContentChange: (content: string) => void;
}) {
  return (
    <>
      <div>
        <Label>Язык</Label>
        <Select value={language} onValueChange={(v) => onLanguageChange(v as ScriptLanguage)}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ScriptLanguage.PYTHON}>python</SelectItem>
            <SelectItem value={ScriptLanguage.BASH}>bash</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div>
        <Label htmlFor="node-script">Содержимое скрипта</Label>
        <Textarea
          id="node-script"
          rows={6}
          className="font-mono text-small"
          value={content}
          onChange={(e) => onContentChange(e.target.value)}
        />
      </div>
    </>
  );
}
