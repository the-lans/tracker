import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  BackupForm,
  BackupSecretField,
  BackupTextField,
} from "@/components/admin/backupSettings.types";
import type { BackupSettings } from "@/lib/types";

const MIN_RETENTION = 1;
const MAX_RETENTION = 365;

const TEXT_FIELDS: Array<{ field: BackupTextField; label: string; placeholder: string }> = [
  { field: "endpoint", label: "Адрес S3", placeholder: "https://s3.example.com" },
  { field: "region", label: "Регион", placeholder: "ru-1" },
  { field: "bucket", label: "Бакет", placeholder: "my-bucket" },
  { field: "access_key", label: "Ключ доступа (Access Key)", placeholder: "" },
];

const SECRET_FIELDS: Array<{
  field: BackupSecretField;
  label: string;
  setFlag: "secret_key_set" | "passphrase_set";
}> = [
  { field: "secret_key", label: "Секретный ключ (Secret Key)", setFlag: "secret_key_set" },
  { field: "passphrase", label: "Пароль шифрования копий", setFlag: "passphrase_set" },
];

/** Поля подключения к S3, папка и число хранимых копий; секреты не показываются. */
export function BackupSettingsFields({
  form,
  settings,
  onChange,
}: {
  form: BackupForm;
  settings: BackupSettings;
  onChange: (changes: Partial<BackupForm>) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {TEXT_FIELDS.map(({ field, label, placeholder }) => (
        <div key={field} className="min-w-0">
          <Label htmlFor={`backup-${field}`}>{label}</Label>
          <Input
            id={`backup-${field}`}
            placeholder={placeholder}
            autoComplete="off"
            spellCheck={false}
            value={form[field]}
            onChange={(event) => onChange({ [field]: event.target.value })}
          />
        </div>
      ))}
      {SECRET_FIELDS.map(({ field, label, setFlag }) => (
        <div key={field} className="min-w-0">
          <Label htmlFor={`backup-${field}`}>{label}</Label>
          <Input
            id={`backup-${field}`}
            type="password"
            autoComplete="new-password"
            placeholder={settings[setFlag] ? "Сохранён — ввод заменит" : ""}
            value={form[field]}
            onChange={(event) => onChange({ [field]: event.target.value })}
          />
        </div>
      ))}
      <div className="min-w-0">
        <Label htmlFor="backup-folder">Папка в бакете</Label>
        <Input
          id="backup-folder"
          spellCheck={false}
          value={form.folder}
          onChange={(event) => onChange({ folder: event.target.value })}
          required
        />
      </div>
      <div className="min-w-0">
        <Label htmlFor="backup-retention">Хранить копий</Label>
        <Input
          id="backup-retention"
          type="number"
          min={MIN_RETENTION}
          max={MAX_RETENTION}
          value={form.retention_count}
          onChange={(event) => onChange({ retention_count: Number(event.target.value) })}
          required
        />
      </div>
    </div>
  );
}
