import type { ReactNode } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useUrlTab } from "@/hooks/useUrlTab";

export interface PageTab {
  value: string;
  label: string;
  content: ReactNode;
}

/** Вкладки раздела страницы; активная — в адресе (`?tab=`), первая — по умолчанию. */
export function PageTabs({ tabs }: { tabs: readonly PageTab[] }) {
  const [tab, setTab] = useUrlTab(
    tabs.map((item) => item.value),
    tabs[0].value,
  );

  return (
    <Tabs value={tab} onValueChange={setTab}>
      <TabsList className="mb-4 flex-wrap">
        {tabs.map((item) => (
          <TabsTrigger key={item.value} value={item.value}>
            {item.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {tabs.map((item) => (
        <TabsContent key={item.value} value={item.value}>
          {item.content}
        </TabsContent>
      ))}
    </Tabs>
  );
}
