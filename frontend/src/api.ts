export type User = {
  id: string
  username: string
  email: string
  display_name: string
}

export type UserSearchItem = Pick<User, 'id' | 'username' | 'display_name'>
export type Chat = {
  id: string
  type: 'direct' | 'group'
  title: string | null
  created_by: string
  created_at: string
  updated_at: string
  last_message_at: string | null
  last_message?: string | null
  peer?: UserSearchItem | null
  muted: boolean
}
export type ChatMember = {
  user_id: string
  username: string
  display_name: string
  role: 'admin' | 'member'
  joined_at: string
}
export type Message = {
  id: string
  chat_id: string
  sender_id: string
  client_message_id: string
  content: string
  created_at: string
  edited: boolean
  delivery?: 'pending' | 'queued' | 'sent' | 'failed'
  reactions: ReactionSummary[]
  attachments: Attachment[]
  mentions: Mention[]
  reply_to: MessageReply | null
  read_by: string[]
  deleted_at: string | null
}
export type ReactionSummary = { emoji: string; count: number; reacted_by_me: boolean }
export type Attachment = { id: string; filename: string; content_type: string; size: number; download_url: string }
export type Mention = { user_id: string; username: string; display_name: string }
export type MessageReply = { id: string; sender_id: string; content: string; deleted_at: string | null }
export type MessagePage = { items: Message[]; next_cursor: string | null }
export type ChatPage = { items: Chat[]; next_offset: number | null }

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1').replace(/\/$/, '')

export class ApiError extends Error {
  code: string
  status: number

  constructor(message: string, code: string, status: number) {
    super(message)
    this.code = code
    this.status = status
  }
}

export async function api<T>(path: string, token?: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, { ...init, headers })
  } catch {
    throw new ApiError('Не удалось связаться с сервером', 'NETWORK_ERROR', 0)
  }
  const body = response.status === 204 ? null : await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(
      body?.error?.message ?? 'Запрос не выполнен',
      body?.error?.code ?? 'REQUEST_FAILED',
      response.status,
    )
  }
  return body as T
}

export async function uploadAttachment(chatId: string, file: File, token: string): Promise<Attachment> {
  let response: Response
  try {
    response = await fetch(`${apiBase}/chats/${chatId}/attachments`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': file.type || 'application/octet-stream',
        'X-File-Name': encodeURIComponent(file.name),
      },
      body: file,
    })
  } catch {
    throw new ApiError('Не удалось загрузить файл', 'NETWORK_ERROR', 0)
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(body?.error?.message ?? 'Не удалось загрузить файл', body?.error?.code ?? 'UPLOAD_FAILED', response.status)
  }
  return body as Attachment
}

export async function downloadAttachment(attachment: Attachment, token: string): Promise<void> {
  const url = new URL(attachment.download_url, `${apiBase}/`).toString()
  let response: Response
  try {
    response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
  } catch {
    throw new ApiError('Не удалось скачать файл', 'NETWORK_ERROR', 0)
  }
  if (!response.ok) throw new ApiError('Не удалось скачать файл', 'DOWNLOAD_FAILED', response.status)
  const objectUrl = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = attachment.filename
  link.click()
  URL.revokeObjectURL(objectUrl)
}

export function websocketUrl(): string {
  return `${apiBase.replace(/^http/, 'ws')}/ws`
}
