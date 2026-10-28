import {
  LibraryPromptRunStatus,
  LlmAccountStatus,
  ManualRequestStatus,
  ManualRequestType,
  NodeLogStatus,
  NodeLogTriggerType,
  NodeType,
  RemoteControlStatus,
  TaskStatus,
  UserRole,
  type CurrentUser,
  type LlmAccount,
  type ManualRequest,
  type NodeItem,
  type NodeLog,
  type PendingOption,
  type Task,
  type TaskLibraryPromptItem,
  type TaskNodeItem,
  type User,
} from "@/lib/types";

const CREATED_AT = "2026-10-25T10:00:00Z";

/** Варианты ревью плана — как их присылает backend (раздел 9.3). */
export const PLAN_OPTIONS: PendingOption[] = [
  { id: "accept_auto", label: "Принять план и продолжить автоматически" },
  { id: "accept_default", label: "Принять план, подтверждать каждое действие" },
  { id: "revise", label: "Доработать план" },
];

export function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "t1",
    code: "RR-12345",
    title: "Экспорт отчётов в CSV",
    description: "",
    guide_url: null,
    jira_issue_url: null,
    status: TaskStatus.NEW,
    pipeline_id: "p1",
    llm_account_id: "acc1",
    parent_task_id: null,
    use_parent_summary: false,
    session_id: null,
    current_permission_mode: null,
    auto_accept_plan: false,
    remote_control_status: RemoteControlStatus.DISCONNECTED,
    scheduled_start_at: null,
    auto_start_enabled: false,
    last_failed_order_index: null,
    repo_cleaned_at: null,
    created_by: "u1",
    created_at: CREATED_AT,
    updated_at: CREATED_AT,
    ...overrides,
  };
}

export function makeNodeLog(overrides: Partial<NodeLog> = {}): NodeLog {
  return {
    id: "log1",
    node_id: "n1",
    trigger_type: NodeLogTriggerType.PIPELINE,
    attempt_number: 1,
    rendered_prompt: null,
    llm_output_text: null,
    user_input_text: null,
    decision_output_offset: null,
    script_stdout: null,
    script_exit_code: null,
    status: NodeLogStatus.SUCCESS,
    pending_question: null,
    pending_plan_text: null,
    pending_options: null,
    started_at: CREATED_AT,
    finished_at: CREATED_AT,
    ...overrides,
  };
}

export function makeTaskNode(overrides: Partial<TaskNodeItem> = {}): TaskNodeItem {
  return {
    id: "tn1",
    node_id: "n1",
    order_index: 0,
    is_enabled: true,
    pause_after: false,
    name: "Реализация",
    node_type: NodeType.PLAIN_PROMPT,
    editable: true,
    is_custom: false,
    prompt_template: null,
    command_invocation: null,
    ...overrides,
  };
}

export function makeLibraryPrompt(
  overrides: Partial<TaskLibraryPromptItem> = {},
): TaskLibraryPromptItem {
  return {
    id: "lp1",
    node_id: "l1",
    name: "Ревью безопасности",
    node_type: NodeType.PLAIN_PROMPT,
    last_run_status: LibraryPromptRunStatus.NEVER_RUN,
    last_run_at: null,
    active_request_id: null,
    ...overrides,
  };
}

export function makeNode(overrides: Partial<NodeItem> = {}): NodeItem {
  return {
    id: "n1",
    pipeline_id: "p1",
    order_index: 0,
    name: "Реализация",
    description: null,
    node_type: NodeType.PLAIN_PROMPT,
    prompt_template: "Реализуй задачу {{task.code}}",
    command_invocation: null,
    script_language: null,
    script_content: null,
    docker_image: null,
    timeout_seconds: 600,
    max_retries: 3,
    retry_base_delay_seconds: 5,
    guide_url: null,
    is_skipped: false,
    is_library_item: false,
    llm_output_last_n: null,
    is_archived: false,
    created_by: "u1",
    ...overrides,
  };
}

export function makeManualRequest(overrides: Partial<ManualRequest> = {}): ManualRequest {
  return {
    id: "mq1",
    request_type: ManualRequestType.FREEFORM_PROMPT,
    node_id: null,
    raw_prompt_text: "Проверь выгрузку на больших отчётах",
    status: ManualRequestStatus.QUEUED,
    requested_at: CREATED_AT,
    ...overrides,
  };
}

export function makeCurrentUser(overrides: Partial<CurrentUser> = {}): CurrentUser {
  return { id: "u1", email: "anna@example.com", role: UserRole.USER, ...overrides };
}

export function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: "u1",
    email: "anna@example.com",
    os_username: "anna",
    role: UserRole.USER,
    is_active: true,
    created_at: CREATED_AT,
    ssh_public_key: null,
    ssh_key_fingerprint: null,
    ssh_key_last_used_at: null,
    jira_email: null,
    jira_token_set: false,
    ...overrides,
  };
}

export function makeLlmAccount(overrides: Partial<LlmAccount> = {}): LlmAccount {
  return {
    id: "acc1",
    label: "Claude Max — команда",
    claude_config_dir: "/data/claude-accounts/team",
    status: LlmAccountStatus.ACTIVE,
    created_by: "u1",
    ...overrides,
  };
}
