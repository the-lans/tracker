"""
Разбор аргументов команд: данные не исполняются и не подставляются в код скрипта.
"""

from __future__ import annotations

import re
import shlex
import uuid
from dataclasses import dataclass

from services.errors import ValidationError

MAX_COMMAND_LENGTH = 16000
MAX_COMMAND_NAME_LENGTH = 64
MAX_ARGUMENT_HINT_LENGTH = 200
MAX_COMMAND_INPUT_NAME_LENGTH = MAX_COMMAND_NAME_LENGTH + 1
# `$1` и `$ARGUMENTS[1]` — первый аргумент, как у Bash-скриптов.
FIRST_ARGUMENT_INDEX = 1
_POSITIONAL_ARGUMENT_PREFIX = "$ARGUMENTS["
_ALL_ARGUMENTS_TOKEN = "$ARGUMENTS"
_COMMAND_NAME = re.compile(rf"[a-z][a-z0-9_-]{{0,{MAX_COMMAND_NAME_LENGTH - 1}}}")
_ARGUMENT = re.compile(r"(?P<escape>\\*)\$(?P<argument>ARGUMENTS(?:\[\d+\])?|\d+)(?![\w\[])")


def normalize_slash_name(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    name = value.strip().removeprefix("/").lower()
    if not _COMMAND_NAME.fullmatch(name):
        raise ValidationError(
            "Имя команды: латинская буква, далее буквы, цифры, _ или -, до 64 символов"
        )
    return name


@dataclass(frozen=True)
class CommandArguments:
    name: str
    raw: str
    values: list[str]


def _validate_invocation(text: str) -> None:
    if len(text) > MAX_COMMAND_LENGTH or "\x00" in text:
        raise ValidationError("Команда слишком длинная или содержит недопустимые символы")


def invocation_name(text: str) -> str:
    _validate_invocation(text)
    first = text.lstrip().split(maxsplit=1)[0] if text.strip() else ""
    if not first.startswith("/") or first == "/":
        raise ValidationError("Укажите команду вида /имя аргументы")
    # Имена нативных команд могут содержать двоеточия и другие символы.
    # Ограничения имён библиотеки и разбор её аргументов применяются после поиска.
    return first[1:].lower()


def parse_invocation(text: str) -> CommandArguments:
    _validate_invocation(text)
    match = re.fullmatch(r"/([^\s]+)(?:[ \t\r\n]+([\s\S]*))?", text.lstrip())
    if match is None:
        raise ValidationError("Укажите команду вида /имя аргументы")
    name = normalize_slash_name(match[1])
    if name is None:
        raise ValidationError("Не указано имя команды")
    return parse_arguments(match[2] or "", name=name)


def parse_arguments(raw: str, *, name: str = "") -> CommandArguments:
    """
    Аргументы — текст после имени команды: кавычки и экранирование по правилам
    shell, без исполнения выражений.
    """
    _validate_invocation(raw)
    try:
        values = shlex.split(raw, posix=True)
    except ValueError as exc:
        raise ValidationError("Проверьте кавычки и экранирование аргументов") from exc
    return CommandArguments(name=name, raw=raw, values=values)


@dataclass(frozen=True)
class ArgumentTemplate:
    text: str
    replacements: dict[str, str]
    extra: str

    def expand(self, rendered: str) -> str:
        if self.replacements:
            pattern = "|".join(re.escape(marker) for marker in self.replacements)
            rendered = re.sub(pattern, lambda match: self.replacements[match[0]], rendered)
        return rendered + self.extra


def _argument_value(match: re.Match[str], arguments: CommandArguments) -> tuple[str, bool]:
    token = "$" + match["argument"]
    escapes = match["escape"]
    if len(escapes) == 1:
        return token, False
    if token == _ALL_ARGUMENTS_TOKEN:
        return escapes + arguments.raw, True
    digits = (
        token[len(_POSITIONAL_ARGUMENT_PREFIX) : -1]
        if token.startswith(_POSITIONAL_ARGUMENT_PREFIX)
        else token[1:]
    )
    digits = digits.lstrip("0") or "0"
    # Нумерация с единицы: `$0` и индекс вне диапазона остаются текстом,
    # огромные числа не преобразуем.
    if len(digits) < len(str(MAX_COMMAND_LENGTH)):
        index = int(digits) - FIRST_ARGUMENT_INDEX
        if 0 <= index < len(arguments.values):
            return escapes + arguments.values[index], True
    return escapes + token, False


def prepare_arguments(template: str, arguments: CommandArguments) -> ArgumentTemplate:
    replacements: dict[str, str] = {}
    received_argument = False
    prefix = f"TRACKER_ARGUMENT_{uuid.uuid4().hex}_"

    def protect(match: re.Match[str]) -> str:
        nonlocal received_argument
        replacement, received = _argument_value(match, arguments)
        received_argument = received_argument or received
        marker = prefix + str(len(replacements))
        replacements[marker] = replacement
        return marker

    text = _ARGUMENT.sub(protect, template)
    extra = f"\n\nARGUMENTS: {arguments.raw}" if arguments.raw and not received_argument else ""
    return ArgumentTemplate(text=text, replacements=replacements, extra=extra)
