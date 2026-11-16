export interface TwgConnection {
  enabled: boolean;
  configured: boolean;
  site: string | null;
  email: string | null;
}

export interface TwgConnectionUpdate {
  site: string;
  email: string;
  token: string | null;
}
