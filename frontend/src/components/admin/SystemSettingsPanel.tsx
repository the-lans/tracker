import { Card } from "@/components/ui/card";

/** Раздел 15.5: "Системные настройки — дефолтные Docker-образы, дефолтные
 * значения таймаута и retry-политики для новых нод". Нет ни таблицы, ни
 * эндпоинта, хранящего эти дефолты (ноды создаются с константами из
 * `api/schemas.py::NodeCreateRequest`, не из настраиваемой конфигурации) —
 * управлять здесь пока нечем; строить локальный, ничего не сохраняющий
 * UI было бы обманчивым. */
export function SystemSettingsPanel() {
  return (
    <div className="flex flex-col gap-2">
      <div className="text-[12.5px] font-extrabold text-text-2">Системные настройки</div>
      <Card className="text-[13px] text-text-2">
        Этот раздел (дефолтные Docker-образы, таймаут и retry-политика для новых нод) пока не
        поддержан backend — нет ни таблицы, ни эндпоинта для хранения этих значений.
        Значения по умолчанию сейчас захардкожены в{" "}
        <code className="font-mono text-[12px]">api/schemas.py::NodeCreateRequest</code>.
      </Card>
    </div>
  );
}
