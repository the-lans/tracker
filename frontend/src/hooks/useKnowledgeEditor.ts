import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/apiClient";
import { errorMessage } from "@/lib/errors";
import type { KnowledgeEntry } from "@/lib/knowledge.types";

interface FileContent { content: string; version: number }

/** Состояние одного редактора: ответы предыдущего выбора не меняют новый файл. */
export function useKnowledgeEditor() {
  const sequence = useRef(0);
  const [entry, setEntry] = useState<KnowledgeEntry | null>(null);
  const [path, setPath] = useState("");
  const [text, setText] = useState("");
  const [originalText, setOriginalText] = useState("");
  const [viewedVersion, setViewedVersion] = useState<number | null>(null);
  const [binary, setBinary] = useState(false);
  const [directory, setDirectory] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => () => { sequence.current++; }, []);

  function reset() {
    sequence.current++;
    setEntry(null); setPath(""); setText(""); setOriginalText("");
    setBinary(false); setDirectory(false); setLoading(false); setError(""); setViewedVersion(null);
  }

  function selectDirectory(file: KnowledgeEntry) {
    reset();
    setEntry(file); setPath(file.path); setDirectory(true);
  }

  async function open(file: KnowledgeEntry, version?: number): Promise<boolean> {
    const request = ++sequence.current;
    setLoading(true); setError("");
    if (version === undefined) {
      setEntry(file); setPath(file.path); setDirectory(file.is_directory);
      setBinary(false); setText(""); setOriginalText("");
    }
    try {
      const result = await api.get<FileContent>(`/knowledge/entries/${file.id}/content`, {version});
      if (request !== sequence.current) return false;
      setText(result.content); setBinary(false);
      setViewedVersion(version ?? null);
      if (version === undefined) {
        setEntry({...file, version: result.version});
        setOriginalText(result.content);
      }
      return true;
    } catch (cause) {
      if (request !== sequence.current) return false;
      if (version === undefined) setBinary(true);
      setError(errorMessage(cause, "Не удалось открыть файл"));
      return false;
    } finally {
      if (request === sequence.current) setLoading(false);
    }
  }

  function acceptSaved(file: KnowledgeEntry, sentText: string, request: number) {
    if (request !== sequence.current) return;
    setEntry(file); setOriginalText(sentText); setViewedVersion(null);
  }

  return {
    entry, path, text, originalText, viewedVersion, binary, directory, loading, error,
    setPath, setText, setDirectory, open, reset, selectDirectory, acceptSaved,
    generation: () => sequence.current,
    resetIfCurrent: (request: number) => { if (request === sequence.current) reset(); },
  };
}
