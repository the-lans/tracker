/** Минимальные типы Google Identity Services (клиентский вход, раздел 19.1 ТЗ) —
 * официальный пакет типов не подключён, чтобы не тянуть лишнюю зависимость
 * ради десятка полей. */
interface GoogleCredentialResponse {
  credential: string;
}

interface GoogleAccountsId {
  initialize(config: {
    client_id: string;
    callback: (response: GoogleCredentialResponse) => void;
  }): void;
  renderButton(
    parent: HTMLElement,
    options: { theme?: "outline" | "filled_blue"; size?: "large" | "medium"; width?: number },
  ): void;
  prompt(): void;
}

interface Window {
  google?: {
    accounts: {
      id: GoogleAccountsId;
    };
  };
}
