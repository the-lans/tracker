import type { BackupRun, LlmAccountStatus } from "@/lib/types";

/** Раздел 15.5: зависимость сервера в сводке «Мониторинга». */
export const ServerDependency = {
  POSTGRES: "postgres",
  REDIS: "redis",
  LLM_PROXY: "llm_proxy",
} as const;
export type ServerDependency = (typeof ServerDependency)[keyof typeof ServerDependency];

export interface DependencyStatus {
  name: ServerDependency;
  ok: boolean;
  error: string | null;
}

export interface QueueStatus {
  name: string;
  workers: number;
  /** Сообщений в брокере; null — Redis недоступен. */
  pending: number | null;
}

export interface ServerOverview {
  dependencies: DependencyStatus[];
  queues: QueueStatus[];
  manual_requests_queued: number;
  manual_requests_processing: number;
  version: string;
  deployed_at: string | null;
  /** null — флаг не прочитан (Redis недоступен). */
  maintenance: boolean | null;
  last_backup: BackupRun | null;
  last_verify: BackupRun | null;
}

export const StatsPeriod = {
  DAY: "day",
  WEEK: "week",
} as const;
export type StatsPeriod = (typeof StatsPeriod)[keyof typeof StatsPeriod];

export interface FailingNode {
  node_id: string;
  node_name: string;
  failed: number;
}

export interface NodeStats {
  period: StatsPeriod;
  since: string;
  total: number;
  success: number;
  failed: number;
  stopped: number;
  retries: number;
  avg_duration_seconds: number | null;
  max_duration_seconds: number | null;
  top_failing: FailingNode[];
}

export interface AccountUsage {
  id: string;
  label: string;
  provider: string;
  owner_email: string;
  status: LlmAccountStatus;
  usage_5h_pct: string | null;
  usage_week_pct: string | null;
  usage_5h_resets_at: string | null;
  usage_week_resets_at: string | null;
  usage_checked_at: string | null;
  switches_to_24h: number;
}

export interface LlmUsage {
  accounts: AccountUsage[];
  switches_24h: number;
}

export const VolumeName = {
  TASK_REPOS: "task_repos",
  USER_FILES: "user_files",
  CLAUDE_SESSIONS: "claude_sessions",
  LOG_ARCHIVE: "log_archive",
} as const;
export type VolumeName = (typeof VolumeName)[keyof typeof VolumeName];

export interface VolumeUsage {
  name: VolumeName;
  /** null — каталога нет там, где шёл замер. */
  size_bytes: number | null;
}

export interface DiskUsage {
  volumes: VolumeUsage[];
  measured_at: string | null;
  database_bytes: number;
  free_bytes: number | null;
  total_bytes: number | null;
}

export const ContainerKind = {
  SESSION: "session",
  NODE: "node",
} as const;
export type ContainerKind = (typeof ContainerKind)[keyof typeof ContainerKind];

export interface TaskContainer {
  name: string;
  kind: ContainerKind;
  task_id: string | null;
  task_code: string | null;
  started_at: string | null;
  orphaned: boolean;
}
