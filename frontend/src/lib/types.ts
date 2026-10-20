/**
 * Зеркало типов backend/db/models/enums.py и backend/api/schemas.py.
 * Источник истины — сами эти файлы; при расхождении обновлять отсюда.
 */

export const UserRole = { ADMIN: "admin", USER: "user" } as const;
export type UserRole = (typeof UserRole)[keyof typeof UserRole];

export const TaskStatus = {
  NEW: "new",
  QUEUED: "queued",
  IN_PROGRESS: "in_progress",
  PAUSED: "paused",
  PLAN_REVIEW: "plan_review",
  AWAITING_INPUT: "awaiting_input",
  REBASE_CONFLICT: "rebase_conflict",
  FAILED: "failed",
  DONE: "done",
} as const;
export type TaskStatus = (typeof TaskStatus)[keyof typeof TaskStatus];

export const PermissionMode = {
  PLAN: "plan",
  DEFAULT: "default",
  ACCEPT_EDITS: "acceptEdits",
  BYPASS_PERMISSIONS: "bypassPermissions",
} as const;
export type PermissionMode = (typeof PermissionMode)[keyof typeof PermissionMode];

export const RemoteControlStatus = {
  CONNECTED: "connected",
  DISCONNECTED: "disconnected",
  RECONNECTING: "reconnecting",
} as const;
export type RemoteControlStatus = (typeof RemoteControlStatus)[keyof typeof RemoteControlStatus];

export const RepositoryRole = { READ_ONLY: "read_only", READ_WRITE: "read_write" } as const;
export type RepositoryRole = (typeof RepositoryRole)[keyof typeof RepositoryRole];

export const MergeStatus = {
  NOT_PUSHED: "not_pushed",
  PUSHED: "pushed",
  MERGED: "merged",
  CONFLICT: "conflict",
} as const;
export type MergeStatus = (typeof MergeStatus)[keyof typeof MergeStatus];

export const NodeType = {
  PLAIN_PROMPT: "plain_prompt",
  SLASH_COMMAND: "slash_command",
  SCRIPT: "script",
  CLEAR_CONTEXT: "clear_context",
  PLAN_PROMPT: "plan_prompt",
} as const;
export type NodeType = (typeof NodeType)[keyof typeof NodeType];

export const ScriptLanguage = { PYTHON: "python", BASH: "bash" } as const;
export type ScriptLanguage = (typeof ScriptLanguage)[keyof typeof ScriptLanguage];

export const LibraryPromptRunStatus = {
  NEVER_RUN: "never_run",
  QUEUED: "queued",
  RUNNING: "running",
  SUCCESS: "success",
  FAILED: "failed",
  STOPPED: "stopped",
} as const;
export type LibraryPromptRunStatus =
  (typeof LibraryPromptRunStatus)[keyof typeof LibraryPromptRunStatus];

export const ManualRequestType = {
  LIBRARY_PROMPT: "library_prompt",
  FREEFORM_PROMPT: "freeform_prompt",
} as const;
export type ManualRequestType = (typeof ManualRequestType)[keyof typeof ManualRequestType];

export const ManualRequestStatus = {
  QUEUED: "queued",
  PROCESSING: "processing",
  DONE: "done",
  CANCELLED: "cancelled",
} as const;
export type ManualRequestStatus = (typeof ManualRequestStatus)[keyof typeof ManualRequestStatus];

export const NodeLogTriggerType = {
  PIPELINE: "pipeline",
  LIBRARY_MANUAL: "library_manual",
  FREEFORM_MANUAL: "freeform_manual",
} as const;
export type NodeLogTriggerType = (typeof NodeLogTriggerType)[keyof typeof NodeLogTriggerType];

export const NodeLogStatus = {
  PENDING: "pending",
  RUNNING: "running",
  AWAITING_DECISION: "awaiting_decision",
  SUCCESS: "success",
  FAILED: "failed",
  STOPPED: "stopped",
} as const;
export type NodeLogStatus = (typeof NodeLogStatus)[keyof typeof NodeLogStatus];

export const AppLogLevel = {
  DEBUG: "debug",
  INFO: "info",
  WARNING: "warning",
  ERROR: "error",
  CRITICAL: "critical",
} as const;
export type AppLogLevel = (typeof AppLogLevel)[keyof typeof AppLogLevel];

export const LlmAccountStatus = {
  ACTIVE: "active",
  RATE_LIMITED: "rate_limited",
  DISABLED: "disabled",
} as const;
export type LlmAccountStatus = (typeof LlmAccountStatus)[keyof typeof LlmAccountStatus];

export const EnvVariableScope = { GLOBAL: "global", REPOSITORY: "repository" } as const;
export type EnvVariableScope = (typeof EnvVariableScope)[keyof typeof EnvVariableScope];

export const McpAuthType = {
  NONE: "none",
  API_KEY: "api_key",
  BEARER_TOKEN: "bearer_token",
} as const;
export type McpAuthType = (typeof McpAuthType)[keyof typeof McpAuthType];

export const McpIsolationMode = {
  NONE: "none",
  ISOLATED_FLAG: "isolated_flag",
  PER_TASK_DATA_DIR: "per_task_data_dir",
} as const;
export type McpIsolationMode = (typeof McpIsolationMode)[keyof typeof McpIsolationMode];

export const PeriodicScheduleType = { INTERVAL: "interval", CRONTAB: "crontab" } as const;
export type PeriodicScheduleType = (typeof PeriodicScheduleType)[keyof typeof PeriodicScheduleType];

export const PeriodicRunStatus = {
  SUCCESS: "success",
  FAILED: "failed",
  RUNNING: "running",
} as const;
export type PeriodicRunStatus = (typeof PeriodicRunStatus)[keyof typeof PeriodicRunStatus];

// --- Пользователь / auth --------------------------------------------------

export interface CurrentUser {
  id: string;
  email: string;
  role: UserRole;
}

export interface LoginResponse {
  session_token: string;
  user: CurrentUser;
}

export interface User {
  id: string;
  email: string;
  os_username: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface UserUpdateRequest {
  role?: UserRole | null;
  is_active?: boolean | null;
  os_username?: string | null;
}

export interface AllowedEmail {
  id: string;
  email: string;
  added_by: string | null;
  created_at: string;
}

// --- Задачи ----------------------------------------------------------------

export interface Task {
  id: string;
  code: string;
  title: string;
  description: string;
  guide_url: string | null;
  status: TaskStatus;
  pipeline_id: string | null;
  llm_account_id: string | null;
  parent_task_id: string | null;
  use_parent_summary: boolean;
  session_id: string | null;
  current_permission_mode: PermissionMode | null;
  auto_accept_plan: boolean;
  remote_control_status: RemoteControlStatus;
  scheduled_start_at: string | null;
  auto_start_enabled: boolean;
  last_failed_order_index: number | null;
  repo_cleaned_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskRepositoryAttach {
  repository_id: string;
  role: RepositoryRole;
  base_branch: string;
}

/** Раздел 14.2 «Дублировать задачу»: те же поля формы, без родителя. */
export interface TaskDuplicateRequest {
  code: string;
  title: string;
  description: string;
  guide_url?: string | null;
  llm_account_id?: string | null;
  repositories?: TaskRepositoryAttach[];
}

export interface TaskCreateRequest extends TaskDuplicateRequest {
  parent_task_id?: string | null;
  use_parent_summary?: boolean;
}

/** PATCH /tasks/{id}: auto_accept_plan — до `done`, остальное — только в `new`. */
export interface TaskUpdateRequest {
  title?: string;
  description?: string;
  guide_url?: string | null;
  llm_account_id?: string | null;
  auto_start_enabled?: boolean;
  scheduled_start_at?: string | null;
  auto_accept_plan?: boolean;
}

export interface TaskRepository {
  id: string;
  repository_id: string;
  role: RepositoryRole;
  branch_name: string;
  base_branch: string;
  pushed_at: string | null;
  merge_status: MergeStatus;
}

export interface PendingOption {
  id: string;
  label: string;
}

export interface NodeLog {
  id: string;
  node_id: string | null;
  trigger_type: NodeLogTriggerType;
  attempt_number: number;
  rendered_prompt: string | null;
  llm_output_text: string | null;
  user_input_text: string | null;
  script_stdout: string | null;
  script_exit_code: number | null;
  status: NodeLogStatus;
  pending_question: string | null;
  pending_plan_text: string | null;
  pending_options: PendingOption[] | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface DecisionRequest {
  node_log_id: string;
  option_id: string;
  feedback_text?: string | null;
}

export interface ManualRequest {
  id: string;
  request_type: ManualRequestType;
  node_id: string | null;
  raw_prompt_text: string | null;
  status: ManualRequestStatus;
  requested_at: string;
}

export interface TaskLibraryPrompt {
  id: string;
  node_id: string;
  last_run_status: LibraryPromptRunStatus;
  last_run_at: string | null;
}

/** Строка таблицы «Системные промты задачи»: ■ останавливает `active_request_id`. */
export interface TaskLibraryPromptItem extends TaskLibraryPrompt {
  name: string;
  node_type: NodeType;
  active_request_id: string | null;
}

/** Снимок ноды пайплайна в задаче (`task_nodes`, раздел 13.1). */
export interface TaskNodeItem {
  id: string;
  node_id: string;
  order_index: number;
  is_enabled: boolean;
  name: string;
  node_type: NodeType;
  editable: boolean;
}

/** Раздел 13.3, 15.2: нода, которая берёт вывод у отключаемой. */
export interface NodeDependent {
  node_id: string;
  name: string;
}

export interface PipelineDependentsRequest {
  node_id: string;
  enabled_node_ids: string[];
}

export interface BindPipelineRequest {
  pipeline_id: string;
  disabled_node_ids: string[];
}

export interface TaskStatusEvent {
  task_id: string;
  status: TaskStatus;
}

// --- Пайплайны и ноды --------------------------------------------------

export interface Pipeline {
  id: string;
  name: string;
  is_archived: boolean;
}

export interface NodeItem {
  id: string;
  pipeline_id: string | null;
  order_index: number | null;
  name: string;
  description: string | null;
  node_type: NodeType;
  prompt_template: string | null;
  command_invocation: string | null;
  script_language: ScriptLanguage | null;
  script_content: string | null;
  docker_image: string | null;
  timeout_seconds: number;
  max_retries: number;
  retry_base_delay_seconds: number;
  guide_url: string | null;
  is_skipped: boolean;
  is_library_item: boolean;
  llm_output_last_n: number | null;
  is_archived: boolean;
}

export interface NodeCreateRequest {
  pipeline_id?: string | null;
  order_index?: number | null;
  name: string;
  description?: string | null;
  node_type: NodeType;
  prompt_template?: string | null;
  command_invocation?: string | null;
  script_language?: ScriptLanguage | null;
  script_content?: string | null;
  docker_image?: string | null;
  timeout_seconds?: number;
  max_retries?: number;
  retry_base_delay_seconds?: number;
  guide_url?: string | null;
  is_skipped?: boolean;
  llm_output_last_n?: number | null;
}

export type NodeUpdateRequest = Partial<NodeCreateRequest> & { is_archived?: boolean };

// --- Репозитории / шаблоны -----------------------------------------------

export interface Repository {
  id: string;
  name: string;
  git_url: string;
  default_template_id: string | null;
}

export interface RepositoryCreateRequest {
  name: string;
  git_url: string;
  default_template_id?: string | null;
  deploy_key: string;
}

export type RepositoryUpdateRequest = Partial<RepositoryCreateRequest>;

export interface TemplateFileTree {
  [path: string]: string;
}

export interface Template {
  id: string;
  name: string;
  files: TemplateFileTree;
  mcp_server_ids: string[];
}

export interface TemplateCreateRequest {
  name: string;
  files: TemplateFileTree;
  mcp_server_ids?: string[];
}

export type TemplateUpdateRequest = Partial<TemplateCreateRequest>;

export interface TemplatePreviewRequest {
  text: string;
  scope: "pipeline" | "library" | "freeform";
  task_id?: string | null;
  node_id?: string | null;
}

export interface TemplatePreviewResponse {
  rendered_text: string;
}

// --- LLM-аккаунты ----------------------------------------------------------

export interface LlmAccount {
  id: string;
  label: string;
  claude_config_dir: string;
  status: LlmAccountStatus;
}

export interface LlmAccountCreateRequest {
  label: string;
  claude_config_dir: string;
  status?: LlmAccountStatus;
}

export type LlmAccountUpdateRequest = Partial<LlmAccountCreateRequest>;

// --- Переменные окружения --------------------------------------------------

export interface EnvVariable {
  id: string;
  key: string;
  is_secret: boolean;
  scope: EnvVariableScope;
  repository_id: string | null;
}

export interface EnvVariableCreateRequest {
  key: string;
  value: string;
  is_secret?: boolean;
  scope: EnvVariableScope;
  repository_id?: string | null;
}

export interface EnvVariableUpdateRequest {
  value?: string;
  is_secret?: boolean;
}

// --- MCP-серверы -------------------------------------------------------

export interface McpServer {
  id: string;
  name: string;
  url: string;
  auth_type: McpAuthType;
  is_healthy: boolean;
  has_stateful_resource: boolean;
  isolation_mode: McpIsolationMode | null;
  isolation_path_template: string | null;
}

export interface McpServerCreateRequest {
  name: string;
  url: string;
  auth_type: McpAuthType;
  auth_config: string;
  has_stateful_resource?: boolean;
  isolation_mode?: McpIsolationMode | null;
  isolation_path_template?: string | null;
}

export type McpServerUpdateRequest = Partial<McpServerCreateRequest>;

// --- Административная часть -------------------------------------------

export interface PeriodicTask {
  id: string;
  name: string;
  display_name: string;
  description: string;
  task_path: string;
  schedule_type: PeriodicScheduleType;
  interval_seconds: number | null;
  crontab_expression: string | null;
  is_enabled: boolean;
  last_run_at: string | null;
  last_run_status: PeriodicRunStatus | null;
  next_run_at: string | null;
}

export interface PeriodicTaskUpdateRequest {
  interval_seconds?: number;
  crontab_expression?: string;
  is_enabled?: boolean;
}

export interface AppLog {
  id: string;
  level: AppLogLevel;
  source: string;
  message: string;
  context: Record<string, unknown>;
  task_id: string | null;
  created_at: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id: string;
  };
}
