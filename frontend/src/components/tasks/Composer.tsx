import { useRef, useState } from "react";
import { Clock, Eye, MessageSquarePlus, Send } from "lucide-react";
import { toast } from "sonner";
import { Textarea } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useManualQueue, useSubmitFreeformPrompt, useStopManualRequest } from "@/hooks/useTasks";
import { useCommandPreview, useRunTaskCommand, useTaskCommands, type TaskCommand } from "@/hooks/useTaskCommands";
import { ApiError } from "@/lib/apiClient";
import { useTemplatePreview } from "@/hooks/useTemplates";
import { MANUAL_REQUEST_STATUSES } from "@/components/tasks/taskStatusMeta";
import { errorMessage } from "@/lib/errors";
import { NO_LLM_ACCOUNT } from "@/lib/llmAccounts";
import { ManualRequestStatus, ManualRequestType, TaskStatus } from "@/lib/types";
import { isPreLaunch } from "@/lib/taskStatusTransitions";

/** Раздел 8, 15.2: свободный параметризованный промт — отдельно от поля
 * ответа на awaiting_input/plan_review (см. `DecisionWidget`). Не привязан к
 * конкретному статусу, но принимается, только пока сессия задачи активна
 * (раздел 8.2) или задача ждёт лимита (раздел 19.7), а до запуска — в чате
 * «Уточняется» (раздел 14.4); при занятой сессии запрос ждёт в очереди — индикатор
 * «В очереди» рядом с полем. Предпросмотр (раздел 8.2) показывает текст
 * после подстановки переменных — ровно тот, что уйдёт в сессию. */
export function Composer({
  taskId,
  taskStatus,
  llmAvailable,
  manualRequestsClosed = false,
}: {
  taskId: string;
  taskStatus: TaskStatus;
  /** Раздел 3.1, 19.7: у автора есть рабочий LLM-аккаунт — без него свободный промт выполнить некому. */
  llmAvailable: boolean;
  manualRequestsClosed?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [unknownCommand, setUnknownCommand] = useState(false);
  const requestIdentity = useRef<{ text: string; id: string } | null>(null);
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const isCommand = text.trimStart().startsWith("/");
  const prefix = isCommand ? text.trimStart().split(/\s/, 1)[0].slice(1, 65) : "";
  const { data: commands = [], isError: commandsError, isFetching: commandsLoading } = useTaskCommands(taskId, prefix, isCommand);
  const runCommand = useRunTaskCommand(taskId);
  const commandPreview = useCommandPreview(taskId);
  const showCommands = isCommand && !/\s/.test(text.trimStart());
  const [previewText, setPreviewText] = useState<string | null>(null);
  const stopRequest = useStopManualRequest(taskId);
  const submitFreeform = useSubmitFreeformPrompt(taskId);
  const preview = useTemplatePreview();
  const { data: queue } = useManualQueue(taskId);
  const refining = taskStatus === TaskStatus.REFINING;
  const acceptsRequests = MANUAL_REQUEST_STATUSES.includes(taskStatus) || refining;
  const queuedFreeform = (queue ?? []).filter(
    (request) =>
      (request.request_type === ManualRequestType.FREEFORM_PROMPT || request.command_name) &&
      request.status === ManualRequestStatus.QUEUED,
  ).length;

  function handleTextChange(value: string) {
    setText(value);
    setSelectedIndex(0);
    setUnknownCommand(false);
    setPreviewText(null);
  }

  function chooseCommand(command: TaskCommand) {
    handleTextChange(`/${command.slash_name} `);
    fieldRef.current?.focus();
  }

  function handlePreview() {
    if (isCommand) {
      commandPreview.mutate(text.trim(), {
        onSuccess: (data) => setPreviewText(data.rendered_text),
        onError: (error) => toast.error(errorMessage(error, "Ошибка предпросмотра команды")),
      });
      return;
    }
    preview.mutate(
      { text: text.trim(), scope: "freeform", task_id: taskId },
      {
        onSuccess: (data) => setPreviewText(data.rendered_text),
        onError: (error) => {
          toast.error(errorMessage(error, "Ошибка предпросмотра"));
          setPreviewText(null);
        },
      },
    );
  }

  function handleSend(direct = false) {
    if (!text.trim()) return;
    if (isCommand && !direct) {
      const invocation = text.trim();
      if (requestIdentity.current?.text !== invocation) {
        requestIdentity.current = { text: invocation, id: crypto.randomUUID() };
      }
      runCommand.mutate({ invocation, client_request_id: requestIdentity.current.id }, {
        onSuccess: () => {
          toast.success("Команда поставлена в очередь");
          setText(""); setPreviewText(null); setOpen(false); setUnknownCommand(false);
          requestIdentity.current = null;
        },
        onError: (error) => {
          setUnknownCommand(error instanceof ApiError && error.status === 404);
          toast.error(errorMessage(error, "Не удалось запустить команду"));
        },
      });
      return;
    }
    if (!llmAvailable) return;
    submitFreeform.mutate(text.trim(), {
      onSuccess: () => {
        toast.success("Промт поставлен в очередь");
        setText("");
        setPreviewText(null);
        setOpen(false);
      },
      onError: (error) => {
        toast.error(errorMessage(error, "Не удалось отправить промт"));
      },
    });
  }

  return (
    <div className="border-t border-border bg-surface p-3.5 short:sticky short:bottom-0 short:z-10 short:px-3 short:py-1.5">
      {(queue ?? []).filter((request) => request.command_name).map((request) => <div key={request.id}
        className="mb-2 flex items-center justify-between gap-2 text-small">
        <span>/{request.command_name} · версия {request.command_revision} · {request.status === ManualRequestStatus.QUEUED ? "В очереди" : "Выполняется"}</span>
        <Button size="sm" variant="secondary" disabled={stopRequest.isPending}
          onClick={() => stopRequest.mutate(request.id, {
            onError: (error) => toast.error(errorMessage(error, "Не удалось остановить команду")),
          })}>{request.status === ManualRequestStatus.QUEUED ? "Отменить" : "Остановить"} /{request.command_name}</Button>
      </div>)}
      {queuedFreeform > 0 && (
        <div className="mb-2 flex items-center gap-1.5 text-meta font-bold text-info-text short:mb-1">
          <Clock className="size-3" />
          В очереди: {queuedFreeform}
        </div>
      )}
      {manualRequestsClosed && acceptsRequests ? (
        <p className="rounded-lg bg-surface-2 px-3 py-2.5 text-note text-text-3">
          Задача завершается — приём новых промтов и команд закрыт
        </p>
      ) : isPreLaunch(taskStatus) && !refining ? (
        <div className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-note text-text-3">
          <MessageSquarePlus className="size-3.5 shrink-0" />
          Переведите задачу в «Уточняется», чтобы обсудить её с агентом
        </div>
      ) : refining && !llmAvailable ? (
        <div className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-note text-text-3">
          <MessageSquarePlus className="size-3.5 shrink-0" />
          {NO_LLM_ACCOUNT} — войдите в аккаунт на странице «LLM-аккаунты», чтобы обсудить задачу с агентом
        </div>
      ) : !llmAvailable && !acceptsRequests ? (
        <div className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-note text-text-3">
          <MessageSquarePlus className="size-3.5 shrink-0" />
          {NO_LLM_ACCOUNT} — свободный промт выполнить некому
        </div>
      ) : !acceptsRequests ? (
        <div className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-note text-text-3">
          <MessageSquarePlus className="size-3.5 shrink-0" />
          Свободный промт доступен, пока сессия задачи активна
        </div>
      ) : !open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex touch-target w-full items-center gap-2 rounded-lg bg-surface-2 px-3 py-2.5 text-left text-note text-text-3 short:py-1"
        >
          <MessageSquarePlus className="size-3.5 shrink-0" />
          {refining ? "Сообщение агенту — обсудить задачу до запуска" : "Свободный промт — задать вопрос сессии в любой момент"}
        </button>
      ) : (
        <div className="flex flex-col gap-2">
          {previewText !== null && (
            <div className="whitespace-pre-wrap rounded-lg border border-border bg-surface-2 px-3 py-2 text-note text-text-2">
              <div className="mb-1 text-caption font-extrabold uppercase tracking-wider text-text-3">
                После подстановки
              </div>
              {previewText}
            </div>
          )}
          {!llmAvailable && <p className="text-small text-text-3">{NO_LLM_ACCOUNT} — доступны только команды-скрипты.</p>}
          {showCommands && <div id="task-command-options" role="listbox" aria-label="Команды библиотеки"
            className="max-h-60 overflow-y-auto rounded-md border border-border bg-surface">
            {commandsError && <p className="p-3 text-small text-text-3">Не удалось загрузить команды. Можно повторить поиск или отправку.</p>}
            {commandsLoading && <p className="p-3 text-small text-text-3">Загрузка команд…</p>}
            {!commandsError && !commandsLoading && commands.length === 0 && <p className="p-3 text-small text-text-3">Нет подходящих команд библиотеки.</p>}
            {commands.map((command, index) => <button key={command.id} type="button" role="option"
              id={`task-command-${index}`} aria-selected={index === selectedIndex}
              className={`flex w-full flex-col p-3 text-left ${index === selectedIndex ? "bg-surface-2" : ""}`}
              onMouseDown={(event) => event.preventDefault()} onClick={() => chooseCommand(command)}>
              <span className="font-bold">/{command.slash_name} <span className="font-normal text-text-3">{command.argument_hint}</span></span>
              <span className="text-small text-text-3">{command.node_type === "script" ? "Скрипт" : "Промт"} · {command.description || command.name}</span>
            </button>)}
            {commands.length === 50 && <p className="p-3 text-small text-text-3">Показаны первые 50 команд. Уточните имя.</p>}
          </div>}
          {unknownCommand && llmAvailable && <Button variant="secondary" onClick={() => handleSend(true)}
            disabled={submitFreeform.isPending}>Отправить напрямую агенту</Button>}
          <div className="flex items-end gap-2">
            <Textarea
              autoFocus
              ref={fieldRef}
              aria-label="Промт или команда"
              aria-autocomplete="list"
              aria-controls={showCommands ? "task-command-options" : undefined}
              aria-activedescendant={showCommands && commands[selectedIndex] ? `task-command-${selectedIndex}` : undefined}
              onKeyDown={(event) => {
                if (!showCommands || commands.length === 0) return;
                if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                  event.preventDefault();
                  setSelectedIndex((index) => (index + (event.key === "ArrowDown" ? 1 : commands.length - 1)) % commands.length);
                } else if (event.key === "Enter" || event.key === "Tab") {
                  event.preventDefault(); chooseCommand(commands[selectedIndex] ?? commands[0]);
                } else if (event.key === "Escape") {
                  event.preventDefault(); handleTextChange(text + " ");
                }
              }}
              rows={2}
              placeholder="Текст промта… Доступны {{task.*}}, {{session.id}}, {{env.*}}"
              value={text}
              onChange={(event) => handleTextChange(event.target.value)}
              className="flex-1"
            />
            <Button
              size="icon"
              variant="secondary"
              aria-label="Предпросмотр подстановки"
              disabled={!text.trim() || preview.isPending || commandPreview.isPending || (!isCommand && !llmAvailable)}
              onClick={handlePreview}
            >
              <Eye className="size-4" />
            </Button>
            <Button
              size="icon"
              aria-label="Отправить"
              disabled={!text.trim() || submitFreeform.isPending || runCommand.isPending || (!isCommand && !llmAvailable)}
              onClick={() => handleSend()}
            >
              <Send className="size-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
