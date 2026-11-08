/** Строка файла в форме шаблона; в API уходят `path`, `content` и признак `fromFile`. */
export interface TemplateFileRow {
  /** Ключ React: у строки своё состояние ошибки, индекс сдвигается при удалении. */
  key: number;
  path: string;
  content: string;
  /** Галка «Из файла»: содержимое выбирается с диска, а не вводится текстом; сохраняется в шаблоне. */
  fromFile: boolean;
  /** Файл, выбранный в этом открытии формы, — для подписи «имя · размер». */
  fileName?: string;
  fileSize?: number;
}
