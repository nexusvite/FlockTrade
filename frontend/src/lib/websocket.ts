type MessageHandler = (data: Record<string, unknown>) => void;

export class WSClient {
  private ws: WebSocket | null = null;
  private handlers: Map<string, Set<MessageHandler>> = new Map();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private url: string;

  constructor() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.url = `${proto}//${window.location.host}/ws/live/`;
  }

  connect(): void {
    const token = localStorage.getItem("access_token");
    if (!token) return;

    this.ws = new WebSocket(`${this.url}?token=${token}`);

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      const type = data.type as string;
      this.handlers.get(type)?.forEach((h) => h(data));
      this.handlers.get("*")?.forEach((h) => h(data));
    };

    this.ws.onclose = () => {
      this.reconnectTimer = setTimeout(() => this.connect(), 3000);
    };
  }

  disconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }

  on(type: string, handler: MessageHandler): () => void {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set());
    this.handlers.get(type)!.add(handler);
    return () => this.handlers.get(type)?.delete(handler);
  }
}

export const wsClient = new WSClient();
