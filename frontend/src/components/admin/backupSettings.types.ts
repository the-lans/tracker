/** Поля формы бэкапа в S3; секреты пустые — оставить сохранённые. */
export interface BackupForm {
  enabled: boolean;
  endpoint: string;
  region: string;
  bucket: string;
  access_key: string;
  secret_key: string;
  folder: string;
  retention_count: number;
  passphrase: string;
}

export type BackupTextField = "endpoint" | "region" | "bucket" | "access_key";

export type BackupSecretField = "secret_key" | "passphrase";
