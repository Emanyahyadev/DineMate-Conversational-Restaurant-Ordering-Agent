export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ChatResponse = {
  reply: string;
  conversation_id: string;
};

export type MenuItem = {
  id: string;
  name: string;
  category: string;
  price: number;
  tags: string[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function sendMessage(
  message: string,
  userId: string,
  conversationId: string | null,
): Promise<ChatResponse> {
  return request<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      user_id: userId,
      conversation_id: conversationId,
    }),
  });
}

export function fetchMenu(): Promise<MenuItem[]> {
  return request<MenuItem[]>("/api/menu");
}
