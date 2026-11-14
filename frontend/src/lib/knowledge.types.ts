export interface KnowledgeSection {
  id: string;
  name: string;
  user_read: boolean;
  user_write: boolean;
  publication_pending?: boolean;
}

export interface KnowledgeEntry {
  id: string;
  path: string;
  version: number;
  is_directory: boolean;
  deleted_at: string | null;
}

export interface KnowledgeVersion {
  version: number;
  created_at: string;
  created_by: string;
  task_id: string | null;
}
