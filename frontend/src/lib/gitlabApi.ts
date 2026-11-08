/**
 * Доступ к GitLab API учётных данных Git (раздел 3.1, 16.2): что отправить на
 * сервер и можно ли сохранить форму.
 */

import type {
  GitCredential,
  GitCredentialInput,
  GitCredentialKind,
  GitlabApiState,
} from "@/components/admin/gitCredentials.types";

export const GITLAB_API_OK = "ok";
export const GITLAB_API_DISABLED = "disabled";

export function initialGitlabApi(credential?: GitCredential): GitlabApiState {
  return {
    enabled: credential?.gitlab_api_enabled ?? false,
    sameToken: credential?.kind !== "ssh_key" && !credential?.gitlab_api_token_set,
    token: "",
    url: credential?.gitlab_api_url ?? "",
  };
}

function usesGitToken(kind: GitCredentialKind, state: GitlabApiState): boolean {
  return kind === "https_token" && state.sameToken;
}

/** Без токена API опрос невозможен: у SSH-ключа и при отдельном токене HTTPS. */
export function gitlabApiTokenMissing(
  kind: GitCredentialKind,
  state: GitlabApiState,
  tokenSet: boolean,
): boolean {
  return state.enabled && !usesGitToken(kind, state) && !state.token && !tokenSet;
}

export function gitlabApiBody(
  kind: GitCredentialKind,
  state: GitlabApiState,
  tokenSet: boolean,
): Pick<GitCredentialInput, "gitlab_api_enabled" | "gitlab_api_url" | "gitlab_api_token"> {
  const body = { gitlab_api_enabled: state.enabled, gitlab_api_url: state.url.trim() || null };
  if (usesGitToken(kind, state)) {
    // Свой токен больше не нужен — сохранённый удаляется.
    return tokenSet ? { ...body, gitlab_api_token: "" } : body;
  }
  return state.token ? { ...body, gitlab_api_token: state.token } : body;
}

export function gitlabApiCheckMessage(result: string): string | null {
  if (result === GITLAB_API_DISABLED) return null;
  if (result === GITLAB_API_OK) return "GitLab API доступен.";
  return `GitLab API: ${result}`;
}
