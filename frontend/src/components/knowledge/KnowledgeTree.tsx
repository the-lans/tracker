import { useState } from "react";
import { ChevronDown, ChevronRight, FileText, Folder } from "lucide-react";

export interface KnowledgeTreeEntry {
  id: string;
  path: string;
  version: number;
  is_directory: boolean;
  deleted_at: string | null;
}

interface Branch {
  path: string;
  name: string;
  entry?: KnowledgeTreeEntry;
  children: Map<string, Branch>;
}

function branches(entries: KnowledgeTreeEntry[]): Branch[] {
  const root = new Map<string, Branch>();
  for (const entry of entries) {
    let children = root;
    let path = "";
    for (const part of entry.path.split("/")) {
      path = path ? `${path}/${part}` : part;
      let node = children.get(part);
      if (!node) { node = {name: part, path, children: new Map()}; children.set(part, node); }
      if (path === entry.path) node.entry = entry;
      children = node.children;
    }
  }
  return [...root.values()];
}

function TreeBranch({ branch, onOpen, onFolder, selectedPath }: {branch: Branch; onOpen: (entry: KnowledgeTreeEntry) => void; onFolder: (path: string, entry?: KnowledgeTreeEntry) => void; selectedPath: string}) {
  const [expanded, setExpanded] = useState(true);
  const folder = branch.entry?.is_directory || branch.children.size > 0;
  return <li>
    <div className={`flex min-w-0 items-center gap-1 rounded-md hover:bg-surface-2 ${selectedPath === branch.path ? "bg-accent-tint text-accent" : "text-text-2"}`}>
      {folder && <button className="touch-target shrink-0" aria-label={`${expanded ? "Свернуть" : "Развернуть"} ${branch.path}`} aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}</button>}
      {folder ? <Folder className="size-4 shrink-0" /> : <FileText className="size-4 shrink-0" />}
      <button className="min-w-0 flex-1 break-all rounded px-1 py-2 text-left text-sm hover:text-text" aria-current={selectedPath === branch.path ? "true" : undefined} title={branch.path} onClick={() => { if (folder) { onFolder(branch.path, branch.entry); setExpanded(true); } else if (branch.entry) onOpen(branch.entry); }}>{branch.name}{branch.entry && !folder && ` · v${branch.entry.version}`}</button>
    </div>
    {expanded && branch.children.size > 0 && <ul className="ml-3 border-l pl-1">{[...branch.children.values()].map((child) => <TreeBranch key={child.path} branch={child} onOpen={onOpen} onFolder={onFolder} selectedPath={selectedPath} />)}</ul>}
  </li>;
}

export function KnowledgeTree({entries, onOpen, onFolder, selectedPath}: {entries: KnowledgeTreeEntry[]; onOpen: (entry: KnowledgeTreeEntry) => void; onFolder: (path: string, entry?: KnowledgeTreeEntry) => void; selectedPath: string}) {
  return <ul aria-label="Файлы базы знаний">{branches(entries).map((branch) => <TreeBranch key={branch.path} branch={branch} onOpen={onOpen} onFolder={onFolder} selectedPath={selectedPath} />)}</ul>;
}
