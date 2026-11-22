import { useEffect, useRef, useState } from 'react'
import { translate } from '../i18n'
import { api } from '../api/client'

export function useT(language) {
  return (key, values) => translate(language, key, values)
}

export function Button({ children, kind = 'primary', className = '', ...props }) {
  return <button className={`button button-${kind} ${className}`.trim()} {...props}>{children}</button>
}

export function Notice({ children, kind = 'info' }) {
  if (!children) return null
  return <div className={`notice notice-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>{children}</div>
}

export function ErrorNotice({ error, t, onRetry }) {
  if (!error) return null
  return <Notice kind="error"><div>{error.message || t('unknown_error')}</div>{onRetry && <button className="inline-link" onClick={onRetry}>{t('retry')}</button>}</Notice>
}

export function Loading({ t }) {
  return <div className="loading-row" role="status"><span className="spinner" />{t('loading_data')}</div>
}

export function SpeakButton({ text, language, t, className = '' }) {
  const [available, setAvailable] = useState(true)
  useEffect(() => setAvailable(typeof window !== 'undefined' && 'speechSynthesis' in window), [])
  function speak() {
    if (!available) return
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = language === 'ur' ? 'ur-PK' : 'en-US'
    window.speechSynthesis.speak(utterance)
  }
  if (!available) return null
  return <button className={`speak-button ${className}`} onClick={speak} aria-label={t('read_aloud')} title={t('read_aloud')}>🔊 <span>{t('read_aloud')}</span></button>
}

export function VoiceButton({ language, t, onText, disabled = false }) {
  const [listening, setListening] = useState(false)
  const [voiceError, setVoiceError] = useState('')
  const recorder = useRef(null)
  const recognitionRef = useRef(null)
  const chunks = useRef([])
  const Recognition = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition)
  const canRecord = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined'
  function start() {
    setVoiceError('')
    if (Recognition) {
      const recognition = new Recognition()
      recognitionRef.current = recognition
      recognition.lang = language === 'ur' ? 'ur-PK' : 'en-US'
      recognition.interimResults = false
      recognition.maxAlternatives = 1
      recognition.onresult = (event) => onText(event.results?.[0]?.[0]?.transcript || '')
      recognition.onerror = () => { setListening(false); setVoiceError(t('voice_failed')) }
      recognition.onend = () => { setListening(false); recognitionRef.current = null }
      setListening(true)
      recognition.start()
      return
    }
    if (!canRecord) { setVoiceError(t('voice_unavailable')); return }
    navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
      const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : ''
      const instance = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      recorder.current = instance
      chunks.current = []
      instance.ondataavailable = (event) => { if (event.data.size) chunks.current.push(event.data) }
      instance.onerror = () => { stream.getTracks().forEach((track) => track.stop()); setListening(false); setVoiceError(t('voice_failed')) }
      instance.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop())
        setListening(false)
        try {
          const type = instance.mimeType || 'audio/webm'
          const extension = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm'
          const file = new File([new Blob(chunks.current, { type })], `voice.${extension}`, { type })
          const transcript = await api.transcribe(file, language === 'ur' ? 'ur' : 'en')
          onText(transcript?.text || '')
        } catch { setVoiceError(t('voice_failed')) }
      }
      instance.start()
      setListening(true)
    }).catch(() => { setListening(false); setVoiceError(t('voice_failed')) })
  }
  if (!Recognition && !canRecord) return <span className="voice-unavailable">{t('voice_unavailable')}</span>
  return <div className="voice-control"><button className="voice-button" disabled={disabled} onClick={() => {
    if (recorder.current?.state === 'recording') recorder.current.stop()
    else if (listening) recognitionRef.current?.stop()
    else start()
  }} type="button">🎙️ {listening ? (Recognition ? t('voice_listening') : t('voice_stop')) : t('start_voice')}</button>{voiceError && <small role="alert">{voiceError}</small>}</div>
}

export function Field({ label, children, hint }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>
}

export function EmptyState({ icon = '🌿', title, detail, action }) {
  return <div className="empty-state"><div className="empty-icon" aria-hidden="true">{icon}</div><h3>{title}</h3>{detail && <p>{detail}</p>}{action}</div>
}

export function StatusPill({ value, t }) {
  const key = `status_${value}`
  return <span className={`status-pill status-${value || 'draft'}`}>{t(key)}</span>
}

export function formatDate(value, language) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat(language === 'ur' ? 'ur-PK' : 'en-PK', { dateStyle: 'medium' }).format(date)
}

export function useOnline() {
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine)
  useEffect(() => {
    const on = () => setOnline(true)
    const off = () => setOnline(false)
    window.addEventListener('online', on)
    window.addEventListener('offline', off)
    return () => { window.removeEventListener('online', on); window.removeEventListener('offline', off) }
  }, [])
  return online
}
