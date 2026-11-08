export type GitCredentialKind = "https_token" | "ssh_key";

/** Раздел 3.1: токены не возвращаются — только признак, что токен API сохранён. */
export interface GitCredential {
  id: string;
  name: string;
  kind: GitCredentialKind;
  host: string;
  username: string;
  gitlab_api_enabled: boolean;
  gitlab_api_url: string | null;
  gitlab_api_token_set: boolean;
}

/** `gitlab_api_token`: не передан — оставить сохранённый, пустая строка — удалить. */
export interface GitCredentialInput {
  name: string;
  kind: GitCredentialKind;
  host: string;
  username: string;
  secret?: string;
  gitlab_api_enabled: boolean;
  gitlab_api_url: string | null;
  gitlab_api_token?: string;
}

/** Итог проверки: чтение Git и доступ к GitLab API (`ok`, `disabled` или причина отказа). */
export interface GitCredentialCheck {
  read_access: boolean;
  gitlab_api: string;
}

/** Состояние полей GitLab API в форме учётных данных. */
export interface GitlabApiState {
  enabled: boolean;
  /** Только для HTTPS: запрашивать API тем же токеном, что и Git. */
  sameToken: boolean;
  token: string;
  url: string;
}
