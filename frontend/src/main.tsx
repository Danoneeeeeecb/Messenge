import { zodResolver } from '@hookform/resolvers/zod'
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { useForm } from 'react-hook-form'
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import {
  api,
  ApiError,
  downloadAttachment,
  type Chat,
  type ChatMember,
  type ChatPage,
  type Message,
  type MessagePage,
  type ReactionSummary,
  type User,
  type UserSearchItem,
  uploadAttachment,
  websocketUrl,
} from './api'
import './style.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, retry: 1, refetchOnWindowFocus: false } },
})

const loginSchema = z.object({
  identifier: z.string().min(1, 'Введите username или email'),
  password: z.string().min(1, 'Введите пароль'),
})
const registerSchema = z.object({
  username: z.string().min(3).max(32).regex(/^[a-zA-Z0-9_]+$/, 'Только латиница, цифры и _'),
  email: z.string().email('Введите корректный email'),
  password: z.string().min(12, 'Минимум 12 символов').max(128),
  display_name: z.string().trim().min(1, 'Введите имя').max(80),
})
const groupSchema = z.object({ title: z.string().trim().min(1, 'Введите название').max(120) })

type LoginValues = z.infer<typeof loginSchema>
type RegisterValues = z.infer<typeof registerSchema>
type LocalMessage = Message
type SocketStatus = 'connecting' | 'online' | 'reconnecting' | 'offline'
type PendingMessage = {
  chatId: string
  clientMessageId: string
  content: string
  attachmentIds?: string[]
  replyToMessageId?: string
}
const reactionPalette = ['👍', '❤️', '😂', '😮', '😢', '🎉', '🔥', '🙏']

function AppRoot() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<SessionApp />} />
          <Route path="/auth" element={<SessionApp />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

function SessionApp() {
  const navigate = useNavigate()
  const [token, setToken] = useState(() => sessionStorage.getItem('access_token'))
  const current = useQuery({
    queryKey: ['currentUser', token],
    queryFn: () => api<User>('/users/me', token ?? undefined),
    enabled: Boolean(token),
  })

  const signOut = useCallback(() => {
    sessionStorage.removeItem('access_token')
    setToken(null)
    queryClient.clear()
    navigate('/auth')
  }, [navigate])

  useEffect(() => {
    if (current.error instanceof ApiError && current.error.status === 401) signOut()
  }, [current.error, signOut])

  if (!token) {
    return <AuthPage onAuthenticated={(accessToken) => {
      sessionStorage.setItem('access_token', accessToken)
      setToken(accessToken)
      navigate('/')
    }} />
  }
  if (current.isLoading) return <div className="full-loader"><span className="spinner" />Проверяем сессию…</div>
  if (current.error || !current.data) return <div className="full-loader"><div className="session-error"><h2>Не удалось проверить сессию</h2><p>{current.error instanceof Error ? current.error.message : 'Попробуйте ещё раз.'}</p><button className="primary-button" onClick={() => void current.refetch()}>Повторить</button><button className="text-button" onClick={signOut}>Войти заново</button></div></div>
  return <Messenger token={token} user={current.data} onSignOut={signOut} />
}

function AuthPage({ onAuthenticated }: { onAuthenticated: (token: string) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [error, setError] = useState('')
  const login = useForm<LoginValues>({ resolver: zodResolver(loginSchema), defaultValues: { identifier: '', password: '' } })
  const register = useForm<RegisterValues>({ resolver: zodResolver(registerSchema), defaultValues: { username: '', email: '', password: '', display_name: '' } })

  const onLogin = login.handleSubmit(async (values) => {
    setError('')
    try {
      const result = await api<{ access_token: string }>('/auth/login', undefined, {
        method: 'POST', body: JSON.stringify(values),
      })
      onAuthenticated(result.access_token)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось войти')
    }
  })

  const onRegister = register.handleSubmit(async (values) => {
    setError('')
    try {
      await api('/auth/register', undefined, { method: 'POST', body: JSON.stringify(values) })
      const result = await api<{ access_token: string }>('/auth/login', undefined, {
        method: 'POST', body: JSON.stringify({ identifier: values.username, password: values.password }),
      })
      onAuthenticated(result.access_token)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось зарегистрироваться')
    }
  })

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="brand-mark">R</div>
        <p className="eyebrow">REALTIME MESSENGER</p>
        <h1>{mode === 'login' ? 'С возвращением' : 'Создать аккаунт'}</h1>
        <p className="muted">{mode === 'login' ? 'Войдите, чтобы продолжить разговоры.' : 'Пара полей — и можно начинать.'}</p>
        <div className="auth-tabs" role="tablist">
          <button className={mode === 'login' ? 'active' : ''} onClick={() => { setMode('login'); setError('') }}>Войти</button>
          <button className={mode === 'register' ? 'active' : ''} onClick={() => { setMode('register'); setError('') }}>Регистрация</button>
        </div>
        {mode === 'login' ? (
          <form className="form-stack" onSubmit={onLogin}>
            <Field label="Username или email" error={login.formState.errors.identifier?.message}>
              <input autoComplete="username" placeholder="например, alex" {...login.register('identifier')} />
            </Field>
            <Field label="Пароль" error={login.formState.errors.password?.message}>
              <input type="password" autoComplete="current-password" placeholder="Ваш пароль" {...login.register('password')} />
            </Field>
            {error && <div className="form-error">{error}</div>}
            <button className="primary-button full-width" disabled={login.formState.isSubmitting}>
              {login.formState.isSubmitting ? 'Входим…' : 'Войти в аккаунт'}
            </button>
          </form>
        ) : (
          <form className="form-stack" onSubmit={onRegister}>
            <Field label="Отображаемое имя" error={register.formState.errors.display_name?.message}>
              <input autoComplete="name" placeholder="Александр" {...register.register('display_name')} />
            </Field>
            <Field label="Username" error={register.formState.errors.username?.message}>
              <input autoComplete="username" placeholder="alex_01" {...register.register('username')} />
            </Field>
            <Field label="Email" error={register.formState.errors.email?.message}>
              <input type="email" autoComplete="email" placeholder="alex@example.com" {...register.register('email')} />
            </Field>
            <Field label="Пароль · не менее 12 символов" error={register.formState.errors.password?.message}>
              <input type="password" autoComplete="new-password" placeholder="Придумайте пароль" {...register.register('password')} />
            </Field>
            {error && <div className="form-error">{error}</div>}
            <button className="primary-button full-width" disabled={register.formState.isSubmitting}>
              {register.formState.isSubmitting ? 'Создаём…' : 'Создать аккаунт'}
            </button>
          </form>
        )}
        <div className="secure-note"><span className="secure-dot" />Пароль хранится в защищённом виде</div>
      </section>
      <div className="auth-caption">Личные разговоры. В своём ритме.</div>
    </main>
  )
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return <label className="field"><span>{label}</span>{children}{error && <small>{error}</small>}</label>
}

function Messenger({ token, user, onSignOut }: { token: string; user: User; onSignOut: () => void }) {
  const client = useQueryClient()
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null)
  const [messages, setMessages] = useState<LocalMessage[]>([])
  const [olderCursor, setOlderCursor] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [socketStatus, setSocketStatus] = useState<SocketStatus>('connecting')
  const [socketError, setSocketError] = useState('')
  const [userQuery, setUserQuery] = useState('')
  const [chatQuery, setChatQuery] = useState('')
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [olderLoading, setOlderLoading] = useState(false)
  const [olderError, setOlderError] = useState('')
  const [emojiOpen, setEmojiOpen] = useState(false)
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null)
  const [replyingTo, setReplyingTo] = useState<Message | null>(null)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [sending, setSending] = useState(false)
  const [composerError, setComposerError] = useState('')
  const [notificationEnabled, setNotificationEnabled] = useState(() =>
    typeof Notification !== 'undefined' && Notification.permission === 'granted' && localStorage.getItem('notifications_enabled') === 'true',
  )
  const [showGroup, setShowGroup] = useState(false)
  const [showMembers, setShowMembers] = useState(false)
  const [messageSearch, setMessageSearch] = useState('')
  const listRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const selectedRef = useRef(selectedChatId)
  const chatsRef = useRef<Chat[] | undefined>(undefined)
  const notificationRef = useRef(notificationEnabled)
  const lastReadSentRef = useRef(new Map<string, string>())
  const pendingRef = useRef<PendingMessage[]>([])
  const requestToClient = useRef(new Map<string, string>())
  selectedRef.current = selectedChatId

  const chats = useQuery({
    queryKey: ['chats'],
    queryFn: () => api<ChatPage>('/chats?limit=100&offset=0', token),
    refetchInterval: 30_000,
  })
  chatsRef.current = chats.data?.items
  notificationRef.current = notificationEnabled
  const selectedChat = chats.data?.items.find((chat) => chat.id === selectedChatId) ?? null
  const initialMessages = useQuery({
    queryKey: ['messages', selectedChatId],
    queryFn: () => api<MessagePage>(`/chats/${selectedChatId}/messages?limit=50`, token),
    enabled: Boolean(selectedChatId),
  })
  const members = useQuery({
    queryKey: ['members', selectedChatId],
    queryFn: () => api<ChatMember[]>(`/chats/${selectedChatId}/members`, token),
    enabled: Boolean(selectedChatId),
  })
  const query = useDebounced(messageSearch.trim(), 250)
  const searchResults = useQuery({
    queryKey: ['messageSearch', selectedChatId, query],
    queryFn: () => api<MessagePage>(`/chats/${selectedChatId}/messages/search?q=${encodeURIComponent(query)}`, token),
    enabled: Boolean(selectedChatId && query),
  })
  const isAdmin = members.data?.some((member) => member.user_id === user.id && member.role === 'admin') ?? false

  useEffect(() => {
    if (!selectedChatId || !initialMessages.data) return
    setMessages(initialMessages.data.items.map((message) => ({ ...message, delivery: 'sent' })))
    setOlderCursor(initialMessages.data.next_cursor)
    requestAnimationFrame(() => listRef.current?.scrollTo({ top: listRef.current.scrollHeight }))
  }, [selectedChatId, initialMessages.data])

  useEffect(() => {
    let retryTimer: number | undefined
    let disposed = false
    let attempts = 0
    const connect = () => {
      if (disposed) return
      setSocketStatus(attempts === 0 ? 'connecting' : 'reconnecting')
      const socket = new WebSocket(websocketUrl())
      socketRef.current = socket
      socket.onopen = () => socket.send(JSON.stringify({
        type: 'auth.authenticate', request_id: crypto.randomUUID(),
        payload: { access_token: token },
      }))
      socket.onmessage = (raw) => {
        let event: { type: string; request_id?: string; payload: Record<string, any> }
        try { event = JSON.parse(raw.data) } catch { return }
        if (event.type === 'connection.ready') {
          attempts = 0
          setSocketStatus('online')
          setSocketError('')
          const activeChatId = selectedRef.current
          if (activeChatId) void client.invalidateQueries({ queryKey: ['messages', activeChatId] })
          void client.invalidateQueries({ queryKey: ['chats'] })
          for (const pending of pendingRef.current) sendPending(socket, pending, requestToClient)
          return
        }
        if (event.type === 'message.ack' || event.type === 'message.new') {
          const saved = event.payload.message as Message
          if (event.type === 'message.ack' && event.request_id) {
            const clientId = requestToClient.current.get(event.request_id)
            if (clientId) {
              pendingRef.current = pendingRef.current.filter((item) => item.clientMessageId !== clientId)
              requestToClient.current.delete(event.request_id)
            }
          }
          if (saved.chat_id === selectedRef.current) {
            setMessages((current) => upsertMessage(current, { ...saved, delivery: 'sent' }))
          } else {
            void client.invalidateQueries({ queryKey: ['messages', saved.chat_id] })
          }
          if (event.type === 'message.new' && saved.sender_id !== user.id && document.hidden && notificationRef.current && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
            const chat = chatsRef.current?.find((item) => item.id === saved.chat_id)
            if (!chat?.muted) new Notification(chat?.title ?? chat?.peer?.display_name ?? 'Новое сообщение', { body: saved.content })
          }
          void client.invalidateQueries({ queryKey: ['chats'] })
          return
        }
        if (event.type === 'message.updated') {
          const saved = event.payload.message as Message
          const updatePage = (page: MessagePage | undefined) => page && ({
            ...page,
            items: page.items.map((item) => item.id === saved.id ? saved : item),
          })
          client.setQueryData<MessagePage>(['messages', saved.chat_id], updatePage)
          client.setQueriesData<MessagePage>({ queryKey: ['messageSearch', saved.chat_id] }, updatePage)
          if (saved.chat_id === selectedRef.current) {
            setMessages((current) => current.map((item) => item.id === saved.id ? { ...saved, delivery: 'sent' } : item))
          }
          void client.invalidateQueries({ queryKey: ['chats'] })
          return
        }
        if (event.type === 'chat.read.updated') {
          const receipt = event.payload as { chat_id: string; message_id: string; user_id: string }
          const updatePage = (page: MessagePage | undefined) => page && ({
            ...page,
            items: markReadInMessages(page.items, receipt),
          })
          client.setQueryData<MessagePage>(['messages', receipt.chat_id], updatePage)
          client.setQueriesData<MessagePage>({ queryKey: ['messageSearch', receipt.chat_id] }, updatePage)
          if (receipt.chat_id === selectedRef.current) {
            setMessages((current) => markReadInMessages(current, receipt))
          }
          return
        }
        if (event.type === 'reaction.updated') {
          const update = event.payload as {
            chat_id: string; message_id: string; user_id: string; emoji: string; active: boolean; count: number
          }
          const applyToPage = (page: MessagePage | undefined) => page && ({
            ...page,
            items: page.items.map((message) => message.id === update.message_id
              ? { ...message, reactions: updateReaction(message.reactions, update, user.id) }
              : message),
          })
          client.setQueryData<MessagePage>(['messages', update.chat_id], applyToPage)
          client.setQueriesData<MessagePage>({ queryKey: ['messageSearch', update.chat_id] }, applyToPage)
          if (update.chat_id === selectedRef.current) {
            setMessages((current) => current.map((message) => message.id === update.message_id
              ? { ...message, reactions: updateReaction(message.reactions, update, user.id) }
              : message))
          }
          return
        }
        if (event.type === 'error') {
          setSocketError(event.payload.message ?? 'Не удалось отправить сообщение')
          const clientId = event.request_id ? requestToClient.current.get(event.request_id) : undefined
          if (clientId) {
            setMessages((current) => current.map((item) => item.client_message_id === clientId ? { ...item, delivery: 'failed' } : item))
            pendingRef.current = pendingRef.current.filter((item) => item.clientMessageId !== clientId)
            requestToClient.current.delete(event.request_id!)
          }
        }
      }
      socket.onclose = (event) => {
        if (disposed) return
        if (event.code === 4401) {
          onSignOut()
          return
        }
        setSocketStatus('reconnecting')
        attempts += 1
        retryTimer = window.setTimeout(connect, Math.min(30_000, 500 * 2 ** Math.min(attempts, 6)))
      }
      socket.onerror = () => socket.close()
    }
    connect()
    return () => {
      disposed = true
      if (retryTimer) window.clearTimeout(retryTimer)
      socketRef.current?.close()
      socketRef.current = null
      setSocketStatus('offline')
    }
  }, [token, client, onSignOut, user.id])

  const startDirect = async (person: UserSearchItem) => {
    try {
      const chat = await api<Chat>('/chats/direct', token, {
        method: 'POST', body: JSON.stringify({ user_id: person.id }),
      })
      await client.invalidateQueries({ queryKey: ['chats'] })
      selectChat(chat.id)
      setUserQuery('')
    } catch (error) {
      setSocketError(error instanceof Error ? error.message : 'Не удалось открыть чат')
    }
  }

  const createGroup = async (title: string, memberIds: string[]) => {
    const chat = await api<Chat>('/chats/group', token, {
      method: 'POST', body: JSON.stringify({ title, member_ids: memberIds }),
    })
    await client.invalidateQueries({ queryKey: ['chats'] })
    selectChat(chat.id)
    setShowGroup(false)
    setShowMembers(true)
  }

  const selectChat = (chatId: string) => {
    setSelectedChatId(chatId)
    setMessages([])
    setOlderCursor(null)
    setOlderError('')
    setMessageSearch('')
    setShowMembers(false)
    setMobileNavOpen(false)
  }

  const loadOlder = async () => {
    if (!selectedChatId || !olderCursor || !listRef.current || olderLoading) return
    const element = listRef.current
    const previousHeight = element.scrollHeight
    setOlderLoading(true)
    setOlderError('')
    try {
      const page = await api<MessagePage>(
        `/chats/${selectedChatId}/messages?limit=50&before=${encodeURIComponent(olderCursor)}`,
        token,
      )
      setMessages((current) => mergeMessages(page.items, current))
      setOlderCursor(page.next_cursor)
      requestAnimationFrame(() => { element.scrollTop += element.scrollHeight - previousHeight })
    } catch (error) {
      setOlderError(error instanceof Error ? error.message : 'Не удалось загрузить историю')
    } finally {
      setOlderLoading(false)
    }
  }

  const sendMessage = async () => {
    if (!selectedChatId || sending) return
    if (editingMessageId) {
      if (!draft.trim() || draft.length > 10_000) return
      const socket = socketRef.current
      if (socket?.readyState !== WebSocket.OPEN) { setComposerError('Нет соединения. Повторите после переподключения.'); return }
      socket.send(JSON.stringify({ type: 'message.edit', request_id: crypto.randomUUID(), payload: { message_id: editingMessageId, content: draft } }))
      setMessages((current) => current.map((message) => message.id === editingMessageId ? { ...message, content: draft, edited: true } : message))
      setEditingMessageId(null)
      setDraft('')
      setComposerError('')
      return
    }
    if ((!draft.trim() && !selectedFiles.length) || draft.length > 10_000) return
    setSending(true)
    setComposerError('')
    try {
      const attachments = await Promise.all(selectedFiles.map((file) => uploadAttachment(selectedChatId, file, token)))
      const content = draft.trim() || `📎 ${attachments.map((attachment) => attachment.filename).join(', ')}`
      const pending: PendingMessage = {
        chatId: selectedChatId,
        clientMessageId: crypto.randomUUID(),
        content,
        attachmentIds: attachments.map((attachment) => attachment.id),
        replyToMessageId: replyingTo?.id,
      }
      pendingRef.current.push(pending)
      setMessages((current) => upsertMessage(current, {
        id: `pending-${pending.clientMessageId}`,
        chat_id: selectedChatId,
        sender_id: user.id,
        client_message_id: pending.clientMessageId,
        content,
        created_at: new Date().toISOString(),
        edited: false,
        reactions: [],
        attachments,
        mentions: [],
        reply_to: replyingTo ? { id: replyingTo.id, sender_id: replyingTo.sender_id, content: replyingTo.content, deleted_at: replyingTo.deleted_at } : null,
        read_by: [],
        deleted_at: null,
        delivery: socketStatus === 'online' ? 'pending' : 'queued',
      }))
      setDraft('')
      setSelectedFiles([])
      setReplyingTo(null)
      setEmojiOpen(false)
      const socket = socketRef.current
      if (socket?.readyState === WebSocket.OPEN) sendPending(socket, pending, requestToClient)
    } catch (error) {
      setComposerError(error instanceof Error ? error.message : 'Не удалось отправить сообщение')
    } finally {
      setSending(false)
    }
  }

  const editMessage = (message: Message) => {
    if (message.deleted_at) return
    setEditingMessageId(message.id)
    setReplyingTo(null)
    setDraft(message.content)
    setComposerError('')
    requestAnimationFrame(() => composerRef.current?.focus())
  }

  const deleteMessage = (message: Message) => {
    const socket = socketRef.current
    if (socket?.readyState !== WebSocket.OPEN) { setComposerError('Нет соединения. Нельзя удалить сообщение сейчас.'); return }
    socket.send(JSON.stringify({ type: 'message.delete', request_id: crypto.randomUUID(), payload: { message_id: message.id } }))
  }

  const replyToMessage = (message: Message) => {
    setEditingMessageId(null)
    setReplyingTo(message)
    setComposerError('')
    requestAnimationFrame(() => composerRef.current?.focus())
  }

  const chooseFiles = (files: FileList | null) => {
    if (!files) return
    const chosen = [...files]
    if (selectedFiles.length + chosen.length > 10) {
      setComposerError('Можно прикрепить не более 10 файлов к одному сообщению.')
      return
    }
    setSelectedFiles((current) => [...current, ...chosen])
    setComposerError('')
  }

  const toggleChatMute = async () => {
    if (!selectedChat) return
    try {
      await api(`/chats/${selectedChat.id}/preferences`, token, {
        method: 'PATCH', body: JSON.stringify({ muted: !selectedChat.muted }),
      })
      await client.invalidateQueries({ queryKey: ['chats'] })
    } catch (error) {
      setSocketError(error instanceof Error ? error.message : 'Не удалось изменить уведомления')
    }
  }

  const toggleNotifications = async () => {
    if (typeof Notification === 'undefined') { setComposerError('Этот браузер не поддерживает уведомления.'); return }
    const permission = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission
    const enabled = permission === 'granted'
    setNotificationEnabled(enabled)
    localStorage.setItem('notifications_enabled', String(enabled))
  }

  const sendReadMarker = () => {
    if (!selectedChatId || query || socketStatus !== 'online' || !listRef.current) return
    const element = listRef.current
    if (element.scrollHeight - element.scrollTop - element.clientHeight > 40) return
    const lastMessage = [...messages].reverse().find((message) => !message.id.startsWith('pending-'))
    if (!lastMessage || lastReadSentRef.current.get(selectedChatId) === lastMessage.id) return
    const socket = socketRef.current
    if (socket?.readyState !== WebSocket.OPEN) return
    socket.send(JSON.stringify({ type: 'chat.read', request_id: crypto.randomUUID(), payload: { chat_id: selectedChatId, message_id: lastMessage.id } }))
    lastReadSentRef.current.set(selectedChatId, lastMessage.id)
  }

  useEffect(() => {
    const frame = requestAnimationFrame(sendReadMarker)
    return () => cancelAnimationFrame(frame)
  }, [selectedChatId, messages.length, socketStatus, query])

  const sendReaction = (message: Message, emoji: string, active: boolean) => {
    const socket = socketRef.current
    if (socket?.readyState !== WebSocket.OPEN) return
    socket.send(JSON.stringify({
      type: 'reaction.set',
      request_id: crypto.randomUUID(),
      payload: { chat_id: message.chat_id, message_id: message.id, emoji, active },
    }))
  }

  const insertEmoji = (emoji: string) => {
    const textarea = composerRef.current
    const start = textarea?.selectionStart ?? draft.length
    const end = textarea?.selectionEnd ?? draft.length
    setDraft((current) => `${current.slice(0, start)}${emoji}${current.slice(end)}`)
    setEmojiOpen(false)
    requestAnimationFrame(() => {
      textarea?.focus()
      textarea?.setSelectionRange(start + emoji.length, start + emoji.length)
    })
  }

  const retryMessage = (message: LocalMessage) => {
    const pending: PendingMessage = {
      chatId: message.chat_id,
      clientMessageId: message.client_message_id,
      content: message.content,
      attachmentIds: message.attachments.map((attachment) => attachment.id),
      replyToMessageId: message.reply_to?.id,
    }
    pendingRef.current.push(pending)
    setMessages((current) => current.map((item) => item.client_message_id === message.client_message_id ? { ...item, delivery: 'queued' } : item))
    const socket = socketRef.current
    if (socket?.readyState === WebSocket.OPEN) sendPending(socket, pending, requestToClient)
  }

  const chatTitle = (chat: Chat) => {
    if (chat.type === 'group') return chat.title ?? 'Группа'
    const other = members.data?.find((member) => member.user_id !== user.id)
    return chat.peer?.display_name ?? (selectedChatId === chat.id && other ? other.display_name : 'Личный чат')
  }
  const visibleMessages = query ? searchResults.data?.items ?? [] : messages
  const visibleChats = chats.data?.items.filter((chat) =>
    `${chatTitle(chat)} ${chat.last_message ?? ''}`.toLocaleLowerCase().includes(chatQuery.trim().toLocaleLowerCase()),
  ) ?? []

  return (
    <main className="messenger-shell">
      {mobileNavOpen && <button className="mobile-nav-backdrop" aria-label="Закрыть меню" onClick={() => setMobileNavOpen(false)} />}
      <aside className={`sidebar ${mobileNavOpen ? 'mobile-open' : ''}`}>
        <div className="sidebar-head">
          <div className="brand-lockup"><div className="brand-mark small">R</div><span>realtime</span></div>
          <button className="icon-button" title="Создать группу" onClick={() => setShowGroup(true)}>＋</button>
        </div>
        <UserFinder token={token} query={userQuery} setQuery={setUserQuery} onChoose={startDirect} />
        <div className="section-heading"><span>ВАШИ ЧАТЫ</span><span>{chats.data?.items.length ?? ''}</span></div>
        <label className="chat-search"><span>⌕</span><input value={chatQuery} onChange={(event) => setChatQuery(event.target.value)} placeholder="Найти чат" /></label>
        <div className="chat-list">
          {chats.isLoading && <div className="empty-small">Загружаем чаты…</div>}
          {visibleChats.map((chat) => (
            <button key={chat.id} className={`chat-row ${selectedChatId === chat.id ? 'selected' : ''}`} onClick={() => selectChat(chat.id)}>
              <div className={`avatar ${chat.type === 'group' ? 'group-avatar' : ''}`}>{chat.type === 'group' ? '✳' : '◦'}</div>
              <div className="chat-row-copy"><strong>{chatTitle(chat)}</strong><span>{chat.last_message ?? (chat.type === 'group' ? 'Групповой чат' : 'Личная переписка')}</span></div>
              {chat.last_message_at && <time className="chat-time">{new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(new Date(chat.last_message_at))}</time>}
              {selectedChatId === chat.id && <span className="active-marker" />}
            </button>
          ))}
          {!chats.isLoading && !chats.data?.items.length && <div className="empty-small">Здесь появятся ваши чаты</div>}
          {!chats.isLoading && Boolean(chats.data?.items.length) && !visibleChats.length && <div className="empty-small">По запросу ничего не найдено</div>}
          {chats.error && <button className="text-button" onClick={() => void chats.refetch()}>Не загрузились. Повторить</button>}
        </div>
        <div className="profile-row">
          <div className="avatar profile-avatar">{user.display_name.slice(0, 1).toUpperCase()}</div>
          <div className="profile-copy"><strong>{user.display_name}</strong><span>@{user.username}</span></div>
          <button className={`icon-button subtle notification-toggle ${notificationEnabled ? 'toggled' : ''}`} title={notificationEnabled ? 'Отключить уведомления браузера' : 'Включить уведомления браузера'} onClick={() => void toggleNotifications()}>♧</button>
          <button className="icon-button subtle" title="Выйти" onClick={onSignOut}>↗</button>
        </div>
      </aside>

      <section className="conversation">
        {selectedChat ? <>
          <header className="conversation-head">
            <button className="icon-button mobile-nav-trigger" aria-label="Открыть чаты и поиск" onClick={() => setMobileNavOpen(true)}>☰</button>
            <div className="conversation-person">
              <div className={`avatar ${selectedChat.type === 'group' ? 'group-avatar' : ''}`}>{selectedChat.type === 'group' ? '✳' : chatTitle(selectedChat).slice(0, 1).toUpperCase()}</div>
              <div><h2>{chatTitle(selectedChat)}</h2><span>{selectedChat.type === 'group' ? `${members.data?.length ?? '…'} участника` : 'Личный чат'}</span></div>
            </div>
            <div className="head-actions">
              <span className={`connection-state ${socketStatus}`}><i />{statusLabel(socketStatus)}</span>
              <button className={`icon-button ${selectedChat.muted ? 'toggled' : ''}`} title={selectedChat.muted ? 'Включить уведомления в чате' : 'Отключить уведомления в чате'} aria-label={selectedChat.muted ? 'Включить уведомления в чате' : 'Отключить уведомления в чате'} onClick={() => void toggleChatMute()}>{selectedChat.muted ? '♩' : '♬'}</button>
              <button className={`icon-button ${showMembers ? 'toggled' : ''}`} title="Участники чата" onClick={() => setShowMembers(!showMembers)}>☷</button>
            </div>
          </header>
          <div className="conversation-toolbar">
            <label className="message-search"><span>⌕</span><input value={messageSearch} onChange={(event) => setMessageSearch(event.target.value)} placeholder="Найти в переписке" /></label>
            {socketError && <button className="socket-error" onClick={() => setSocketError('')}>{socketError} ×</button>}
          </div>
          <div className="message-scroll" ref={listRef} onScroll={sendReadMarker}>
            {!query && olderCursor && <button className="load-older" disabled={olderLoading} onClick={() => void loadOlder()}>{olderLoading ? 'Загружаем…' : 'Загрузить более ранние'}</button>}
            {olderError && <div className="inline-error">{olderError} <button className="text-button" onClick={() => void loadOlder()}>Повторить</button></div>}
            {initialMessages.isLoading && !query && <div className="empty-conversation"><span className="spinner" />Загружаем историю…</div>}
            {initialMessages.error && !query && <div className="empty-conversation"><h3>Не удалось загрузить историю</h3><p>{initialMessages.error instanceof Error ? initialMessages.error.message : 'Проверьте соединение и попробуйте снова.'}</p><button className="primary-button" onClick={() => void initialMessages.refetch()}>Повторить</button></div>}
            {query && searchResults.isFetching && <div className="search-state"><span className="spinner" />Ищем сообщения…</div>}
            {query && searchResults.error && <div className="search-state inline-error">Не удалось выполнить поиск. <button className="text-button" onClick={() => void searchResults.refetch()}>Повторить</button></div>}
            {visibleMessages.map((message) => <MessageBubble key={message.id} message={message} own={message.sender_id === user.id} token={token} onRetry={retryMessage} onReact={sendReaction} onReply={replyToMessage} onEdit={editMessage} onDelete={deleteMessage} reactionsEnabled={socketStatus === 'online'} />)}
            {visibleMessages.length === 0 && (query
              ? !searchResults.isFetching && !searchResults.error
              : !initialMessages.isLoading && !initialMessages.error) && <div className="empty-conversation"><div className="empty-icon">✳</div><h3>{query ? 'Ничего не найдено' : 'Начните разговор'}</h3><p>{query ? 'Попробуйте другое слово.' : 'Напишите первое сообщение в этом чате.'}</p></div>}
          </div>
          <div className="composer-wrap">
            <div className="composer">
              {(replyingTo || editingMessageId) && <div className="composer-context"><span>{editingMessageId ? 'Редактирование сообщения' : `Ответ ${replyingTo?.sender_id === user.id ? 'на ваше сообщение' : 'на сообщение'}`}{replyingTo && !editingMessageId ? `: ${replyingTo.content.slice(0, 90)}` : ''}</span><button onClick={() => { setReplyingTo(null); setEditingMessageId(null); setDraft('') }} aria-label="Отменить">×</button></div>}
              {selectedFiles.length > 0 && <div className="pending-attachments">{selectedFiles.map((file, index) => <button key={`${file.name}-${index}`} onClick={() => setSelectedFiles((current) => current.filter((_, currentIndex) => currentIndex !== index))}>{file.name} <span>×</span></button>)}</div>}
              <textarea ref={composerRef} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendMessage() }
              }} placeholder="Напишите сообщение…" maxLength={10_000} aria-label="Сообщение" />
              {composerError && <div className="form-error compact">{composerError}</div>}
              <div className="composer-foot"><span>Enter — отправить · Shift + Enter — новая строка</span><div className="composer-actions">
                <input ref={fileInputRef} type="file" multiple hidden onChange={(event) => { chooseFiles(event.currentTarget.files); event.currentTarget.value = '' }} />
                <button className="emoji-toggle" onClick={() => fileInputRef.current?.click()} aria-label="Прикрепить файлы" title="Прикрепить файлы">＋</button>
                <div className="emoji-control"><button className="emoji-toggle" onClick={() => setEmojiOpen(!emojiOpen)} aria-label="Добавить эмодзи" aria-expanded={emojiOpen}>☺</button>
                  {emojiOpen && <div className="emoji-picker" role="group" aria-label="Выберите эмодзи">{reactionPalette.map((emoji) => <button key={emoji} onClick={() => insertEmoji(emoji)} aria-label={`Добавить ${emoji}`}>{emoji}</button>)}</div>}
                </div>
                <button className="send-button" disabled={sending || (!draft.trim() && !selectedFiles.length) || draft.length > 10_000} onClick={() => void sendMessage()} aria-label={editingMessageId ? 'Сохранить изменения' : 'Отправить'}>{sending ? '…' : editingMessageId ? '✓' : '↗'}</button>
              </div></div>
            </div>
          </div>
        </> : <div className="welcome-pane"><button className="secondary-button mobile-nav-trigger welcome-menu" onClick={() => setMobileNavOpen(true)}>☰  Чаты и поиск</button><div className="welcome-orbit"><div className="brand-mark">R</div></div><p className="eyebrow">ВАШЕ ПРОСТРАНСТВО</p><h1>Разговоры,<br />которые рядом.</h1><p>Выберите переписку или найдите человека, чтобы начать новую.</p><div className="welcome-hint"><span>←</span> Поиск людей находится в левой панели</div></div>}
      </section>

      {showMembers && selectedChat && <MembersPanel
        chat={selectedChat} members={members.data ?? []} isAdmin={isAdmin} token={token} currentUser={user}
        onClose={() => setShowMembers(false)} onChanged={() => {
          void client.invalidateQueries({ queryKey: ['members', selectedChatId] })
          void client.invalidateQueries({ queryKey: ['chats'] })
        }}
      />}
      {showGroup && <GroupDialog token={token} onClose={() => setShowGroup(false)} onCreate={createGroup} />}
    </main>
  )
}

function UserFinder({ token, query, setQuery, onChoose }: {
  token: string; query: string; setQuery: (value: string) => void; onChoose: (user: UserSearchItem) => void
}) {
  const normalized = useDebounced(query.trim(), 250)
  const results = useQuery({
    queryKey: ['userSearch', normalized],
    queryFn: () => api<UserSearchItem[]>(`/users/search?q=${encodeURIComponent(normalized)}`, token),
    enabled: normalized.length > 0,
  })
  return <div className="user-finder">
    <label className="finder-input"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти человека" /></label>
    {normalized && <div className="finder-results">
      {results.isLoading && <div className="finder-hint">Ищем…</div>}
      {results.data?.map((person) => <button key={person.id} title={`Написать ${person.display_name}`} aria-label={`Написать ${person.display_name}`} onClick={() => onChoose(person)}><div className="avatar tiny">{person.display_name.slice(0, 1).toUpperCase()}</div><span><strong>{person.display_name}</strong><small>@{person.username}</small></span><b>Написать</b></button>)}
      {!results.isLoading && !results.error && !results.data?.length && <div className="finder-hint">Никого не нашли</div>}
      {results.error && <div className="finder-hint error-text">Не удалось выполнить поиск <button className="text-button finder-retry" onClick={() => void results.refetch()}>Повторить</button></div>}
    </div>}
  </div>
}

function GroupDialog({ token, onClose, onCreate }: { token: string; onClose: () => void; onCreate: (title: string, ids: string[]) => Promise<void> }) {
  const [selected, setSelected] = useState<UserSearchItem[]>([])
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const debounced = useDebounced(query.trim(), 250)
  const results = useQuery({
    queryKey: ['groupUserSearch', debounced],
    queryFn: () => api<UserSearchItem[]>(`/users/search?q=${encodeURIComponent(debounced)}`, token),
    enabled: debounced.length > 0,
  })
  const form = useForm<{ title: string }>({ resolver: zodResolver(groupSchema), defaultValues: { title: '' } })
  const choose = (person: UserSearchItem) => {
    setSelected((current) => current.some((item) => item.id === person.id) ? current : [...current, person])
    setQuery('')
  }
  const submit = form.handleSubmit(async ({ title }) => {
    if (!selected.length) { setError('Добавьте хотя бы одного участника'); return }
    setError('')
    try { await onCreate(title, selected.map((item) => item.id)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Не удалось создать группу') }
  })
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="dialog-card">
      <div className="dialog-head"><div><p className="eyebrow">НОВОЕ ПРОСТРАНСТВО</p><h2>Создать группу</h2></div><button className="icon-button" onClick={onClose} aria-label="Закрыть">×</button></div>
      <form className="form-stack" onSubmit={submit}>
        <Field label="Название группы" error={form.formState.errors.title?.message}><input autoFocus placeholder="Например, Команда" {...form.register('title')} /></Field>
        <label className="field"><span>Участники</span><div className="dialog-search"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти по имени или username" /></div></label>
        {debounced && <div className="dialog-user-results">
          {results.isFetching && <div className="finder-hint">Ищем пользователей…</div>}
          {results.data?.map((person) => <button type="button" key={person.id} onClick={() => choose(person)}><span>{person.display_name} <small>@{person.username}</small></span><b>＋</b></button>)}
          {!results.isFetching && results.error && <div className="finder-hint error-text">Поиск не выполнен <button type="button" className="text-button finder-retry" onClick={() => void results.refetch()}>Повторить</button></div>}
          {!results.isFetching && !results.error && !results.data?.length && <div className="finder-hint">Никого не нашли</div>}
        </div>}
        {selected.length > 0 && <div className="selected-users">{selected.map((person) => <button type="button" key={person.id} onClick={() => setSelected((current) => current.filter((item) => item.id !== person.id))}>{person.display_name} <span>×</span></button>)}</div>}
        {error && <div className="form-error">{error}</div>}
        <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>Отмена</button><button className="primary-button" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? 'Создаём…' : 'Создать группу'}</button></div>
      </form>
    </section>
  </div>
}

function MembersPanel({ chat, members, isAdmin, token, currentUser, onClose, onChanged }: {
  chat: Chat; members: ChatMember[]; isAdmin: boolean; token: string; currentUser: User; onClose: () => void; onChanged: () => void
}) {
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const debounced = useDebounced(query.trim(), 250)
  const results = useQuery({
    queryKey: ['memberSearch', debounced],
    queryFn: () => api<UserSearchItem[]>(`/users/search?q=${encodeURIComponent(debounced)}`, token),
    enabled: chat.type === 'group' && isAdmin && debounced.length > 0,
  })
  const addMember = async (person: UserSearchItem) => {
    try {
      await api(`/chats/${chat.id}/members`, token, { method: 'POST', body: JSON.stringify({ user_id: person.id }) })
      setQuery(''); setError(''); onChanged()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Не удалось добавить участника') }
  }
  const removeMember = async (member: ChatMember) => {
    try {
      await api(`/chats/${chat.id}/members/${member.user_id}`, token, { method: 'DELETE' })
      setError(''); onChanged()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Не удалось удалить участника') }
  }
  return <aside className="members-panel">
    <div className="panel-head"><div><span className="eyebrow">ИНФОРМАЦИЯ</span><h3>{chat.type === 'group' ? chat.title : 'Участники'}</h3></div><button className="icon-button" onClick={onClose} aria-label="Закрыть">×</button></div>
    <div className="member-count">{members.length} {plural(members.length, 'участник', 'участника', 'участников')}</div>
    <div className="member-list">{members.map((member) => <div className="member-row" key={member.user_id}><div className="avatar tiny">{member.display_name.slice(0, 1).toUpperCase()}</div><div className="member-copy"><strong>{member.display_name}{member.user_id === currentUser.id ? ' · вы' : ''}</strong><small>@{member.username}</small></div><span className={`role-chip ${member.role}`}>{member.role === 'admin' ? 'админ' : 'участник'}</span>{isAdmin && chat.type === 'group' && member.user_id !== currentUser.id && <button className="remove-member" title="Удалить участника" onClick={() => void removeMember(member)}>×</button>}</div>)}</div>
    {isAdmin && chat.type === 'group' && <div className="add-member-box"><label className="field"><span>Добавить участника</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Имя или username" /></label>
      {debounced && results.isFetching && <div className="finder-hint">Ищем пользователей…</div>}
      {debounced && results.data?.filter((person) => !members.some((member) => member.user_id === person.id)).map((person) => <button className="add-result" key={person.id} onClick={() => void addMember(person)}>{person.display_name} <span>＋</span></button>)}
      {debounced && results.error && <div className="finder-hint error-text">Поиск не выполнен <button className="text-button finder-retry" onClick={() => void results.refetch()}>Повторить</button></div>}
      {debounced && !results.isFetching && !results.error && results.data?.length === 0 && <div className="finder-hint">Никого не нашли</div>}
      {error && <div className="form-error compact">{error}</div>}</div>}
    {!isAdmin && chat.type === 'group' && <p className="permission-note">Управлять участниками может только администратор группы.</p>}
  </aside>
}

function MessageBubble({ message, own, token, onRetry, onReact, onReply, onEdit, onDelete, reactionsEnabled }: {
  message: LocalMessage
  own: boolean
  token: string
  onRetry: (message: LocalMessage) => void
  onReact: (message: Message, emoji: string, active: boolean) => void
  onReply: (message: Message) => void
  onEdit: (message: Message) => void
  onDelete: (message: Message) => void
  reactionsEnabled: boolean
}) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const [fileError, setFileError] = useState('')
  const deleted = Boolean(message.deleted_at)
  return <div id={`message-${message.id}`} className={`message-line ${own ? 'own' : ''}`}>
    <div className="message-bubble">
      <div className="message-actions">
        {!deleted && <button className="reaction-trigger" disabled={!reactionsEnabled || message.id.startsWith('pending-')} onClick={() => setPickerOpen(!pickerOpen)} aria-label="Поставить реакцию" title="Поставить реакцию">☺</button>}
        {!deleted && <button className="reaction-trigger message-reply-action" onClick={() => onReply(message)} aria-label="Ответить" title="Ответить">↩</button>}
        {own && !deleted && !message.id.startsWith('pending-') && <button className="reaction-trigger message-edit-action" onClick={() => onEdit(message)} aria-label="Редактировать" title="Редактировать">✎</button>}
        {own && !deleted && !message.id.startsWith('pending-') && <button className="reaction-trigger message-delete-action" onClick={() => onDelete(message)} aria-label="Удалить" title="Удалить">×</button>}
        {pickerOpen && <div className="message-reaction-picker" role="group" aria-label="Выберите реакцию">{reactionPalette.map((emoji) => <button key={emoji} disabled={!reactionsEnabled} onClick={() => { onReact(message, emoji, !message.reactions?.some((item) => item.emoji === emoji && item.reacted_by_me)); setPickerOpen(false) }}>{emoji}</button>)}</div>}
      </div>
      {message.reply_to && <button className="reply-preview" onClick={() => document.getElementById(`message-${message.reply_to?.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })} title="Перейти к исходному сообщению">↩ {message.reply_to.deleted_at ? 'Сообщение удалено' : message.reply_to.content}</button>}
      <p>{message.content}</p>
      {!deleted && message.attachments?.length > 0 && <div className="message-attachments">{message.attachments.map((attachment) => <button key={attachment.id} onClick={() => void downloadAttachment(attachment, token).catch((error: unknown) => setFileError(error instanceof Error ? error.message : 'Не удалось скачать файл'))}><span>📎</span><span>{attachment.filename}<small>{formatFileSize(attachment.size)}</small></span></button>)}</div>}
      {!deleted && message.mentions?.length > 0 && <div className="message-mentions">{message.mentions.map((mention) => <span key={mention.user_id} title={mention.display_name}>@{mention.username}</span>)}</div>}
      {!deleted && Boolean(message.reactions?.length) && <div className="reaction-list">{message.reactions.map((reaction) => <button key={reaction.emoji} className={`reaction-chip ${reaction.reacted_by_me ? 'reacted' : ''}`} disabled={!reactionsEnabled} onClick={() => onReact(message, reaction.emoji, !reaction.reacted_by_me)} aria-label={`${reaction.emoji}, реакций: ${reaction.count}${reaction.reacted_by_me ? ', ваша реакция' : ''}`} title={reaction.reacted_by_me ? 'Убрать реакцию' : 'Добавить реакцию'}>{reaction.emoji}<span>{reaction.count}</span></button>)}</div>}
      {fileError && <div className="file-error">{fileError}</div>}
      <div className="message-meta"><time>{new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(new Date(message.created_at))}</time>{message.edited && !deleted && <span>изменено</span>}{own && message.read_by?.length > 0 && <span className="read-receipt">Прочитали: {message.read_by.length}</span>}{own && <span className={`delivery ${message.delivery ?? 'sent'}`}>{message.delivery === 'failed' ? 'Не отправлено' : message.delivery === 'queued' ? 'В очереди' : message.delivery === 'pending' ? 'Отправка…' : '✓'}</span>}</div>
      {message.delivery === 'failed' && <button className="retry-button" onClick={() => onRetry(message)}>Повторить</button>}
    </div>
  </div>
}

function updateReaction(
  reactions: ReactionSummary[] | undefined,
  update: { user_id: string; emoji: string; active: boolean; count: number },
  currentUserId: string,
): ReactionSummary[] {
  const current = reactions ?? []
  if (update.count === 0) return current.filter((reaction) => reaction.emoji !== update.emoji)
  const existing = current.find((reaction) => reaction.emoji === update.emoji)
  const next: ReactionSummary = {
    emoji: update.emoji,
    count: update.count,
    reacted_by_me: update.user_id === currentUserId ? update.active : existing?.reacted_by_me ?? false,
  }
  return existing
    ? current.map((reaction) => reaction.emoji === update.emoji ? next : reaction)
    : [...current, next].sort((left, right) => reactionPalette.indexOf(left.emoji) - reactionPalette.indexOf(right.emoji))
}

function sendPending(socket: WebSocket, pending: PendingMessage, requestToClient: React.MutableRefObject<Map<string, string>>) {
  if (socket.readyState !== WebSocket.OPEN) return
  const requestId = crypto.randomUUID()
  requestToClient.current.set(requestId, pending.clientMessageId)
  socket.send(JSON.stringify({
    type: 'message.send', request_id: requestId,
    payload: {
      chat_id: pending.chatId,
      client_message_id: pending.clientMessageId,
      content: pending.content,
      attachment_ids: pending.attachmentIds ?? [],
      reply_to_message_id: pending.replyToMessageId ?? null,
    },
  }))
}

function upsertMessage(messages: LocalMessage[], incoming: LocalMessage): LocalMessage[] {
  const index = messages.findIndex((message) => message.id === incoming.id || (
    message.client_message_id === incoming.client_message_id && message.sender_id === incoming.sender_id
  ))
  const result = [...messages]
  if (index >= 0) result[index] = incoming
  else result.push(incoming)
  return result.sort((left, right) => left.created_at.localeCompare(right.created_at) || left.id.localeCompare(right.id))
}

function mergeMessages(older: Message[], current: LocalMessage[]): LocalMessage[] {
  return older.reduce((all, message) => upsertMessage(all, { ...message, delivery: 'sent' }), current)
}

function markReadInMessages(messages: Message[], receipt: { message_id: string; user_id: string }): Message[] {
  const readThroughIndex = messages.findIndex((message) => message.id === receipt.message_id)
  if (readThroughIndex < 0) return messages
  return messages.map((message, index) => {
    if (index > readThroughIndex || message.sender_id === receipt.user_id) return message
    return { ...message, read_by: message.read_by.includes(receipt.user_id) ? message.read_by : [...message.read_by, receipt.user_id] }
  })
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return debounced
}

function statusLabel(status: SocketStatus) {
  return status === 'online' ? 'На связи' : status === 'connecting' ? 'Подключение' : status === 'reconnecting' ? 'Переподключение' : 'Нет соединения'
}

function plural(count: number, one: string, few: string, many: string) {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few
  return many
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><AppRoot /></React.StrictMode>)
