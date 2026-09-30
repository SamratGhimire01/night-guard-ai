import { useCallback, useEffect, useRef, useState } from 'react'
import jsQR from 'jsqr'
import { Alert, Badge, Button, NumberInput, Paper, Stack, Text, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { apiFetch, ApiError } from '../../api/client'
import type { AppointmentRead, CheckinResponse, PaymentRead } from '../../api/types'

export default function CheckInPage() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const rafRef = useRef<number | null>(null)
  // Scanning pauses the instant a code is decoded (set false) and only
  // resumes when staff explicitly click "Scan next" — otherwise the same
  // still-visible QR code would be decoded and submitted repeatedly on
  // every animation frame.
  const scanningRef = useRef(true)

  const [cameraError, setCameraError] = useState<string | null>(null)
  // Real, self-reported camera facing side (from the actual granted
  // MediaStreamTrack's own getSettings() — never assumed from the
  // constraint we asked for, since a browser/device can grant something
  // other than what was requested). Lets staff on a real phone see for
  // themselves which camera is actually active, and lets you verify the
  // "prefer rear camera" fix worked without needing to trust the request
  // alone — not every camera/browser reports this capability, so it can
  // legitimately stay unknown.
  const [activeFacingMode, setActiveFacingMode] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<CheckinResponse | null>(null)
  const [resultError, setResultError] = useState<string | null>(null)
  const [paymentAmount, setPaymentAmount] = useState<number | ''>('')
  const [recordingPayment, setRecordingPayment] = useState(false)
  // NULL until the real, separate "mark service complete" action (below)
  // claims it — a scan alone only ever means ARRIVED, never done.
  const [completedAt, setCompletedAt] = useState<string | null>(null)
  const [completing, setCompleting] = useState(false)

  // A ref, not a plain closure captured by the animation-frame loop below:
  // the loop is started exactly once (on mount) so the camera stream is
  // never restarted, but it must always call the CURRENT version of this
  // function (which closes over the latest state setters) — the standard
  // "always-fresh callback, one-time effect" pattern.
  const handleScanRef = useRef<(token: string) => void>(() => {})

  const handleScan = useCallback(async (token: string) => {
    setSubmitting(true)
    setResultError(null)
    try {
      const res = await apiFetch<CheckinResponse>('/appointments/checkin', {
        method: 'POST',
        body: JSON.stringify({ token }),
      })
      setResult(res)
      setPaymentAmount(res.pending_payment ? Number(res.pending_payment.remaining) : '')
    } catch (err) {
      setResultError(err instanceof ApiError ? err.message : 'Check-in failed.')
    } finally {
      setSubmitting(false)
    }
  }, [])

  useEffect(() => {
    handleScanRef.current = handleScan
  }, [handleScan])

  useEffect(() => {
    let cancelled = false

    function tick() {
      const video = videoRef.current
      const canvas = canvasRef.current
      if (video && canvas && scanningRef.current && video.readyState === video.HAVE_ENOUGH_DATA) {
        canvas.width = video.videoWidth
        canvas.height = video.videoHeight
        const ctx = canvas.getContext('2d')
        if (ctx) {
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
          const frame = ctx.getImageData(0, 0, canvas.width, canvas.height)
          const code = jsQR(frame.data, frame.width, frame.height)
          if (code && code.data) {
            scanningRef.current = false
            handleScanRef.current(code.data)
          }
        }
      }
      rafRef.current = requestAnimationFrame(tick)
    }

    // `{ ideal: 'environment' }`, not a bare 'environment' string: a bare
    // value can be treated as a hard (near-exact) requirement by some
    // browsers, which would throw OverconstrainedError on a desktop webcam
    // that has no "environment" facing side to offer at all — `ideal` asks
    // for the rear camera on a device that has one (real phones) while
    // still resolving to whatever camera IS available otherwise (desktop
    // webcams), so this one constraint object correctly covers both.
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: { ideal: 'environment' } } })
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        streamRef.current = stream
        const [track] = stream.getVideoTracks()
        // Real self-report, not an echo of what we asked for — getSettings()
        // returns what the browser actually granted.
        setActiveFacingMode(track?.getSettings().facingMode ?? null)
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          videoRef.current.play()
        }
        rafRef.current = requestAnimationFrame(tick)
      })
      .catch((err) => {
        setCameraError(err instanceof Error ? err.message : 'Could not access the camera.')
      })

    return () => {
      cancelled = true
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
      streamRef.current?.getTracks().forEach((t) => t.stop())
    }
  }, [])

  function scanNext() {
    setResult(null)
    setResultError(null)
    setPaymentAmount('')
    setCompletedAt(null)
    scanningRef.current = true
  }

  async function markComplete() {
    if (!result) return
    setCompleting(true)
    try {
      const updated = await apiFetch<AppointmentRead>(`/appointments/${result.appointment_id}/complete`, {
        method: 'POST',
      })
      setCompletedAt(updated.completed_at)
      notifications.show({ message: 'Marked as service complete.', color: 'green' })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Failed to mark complete.', color: 'red' })
    } finally {
      setCompleting(false)
    }
  }

  async function recordPayment() {
    if (!result?.pending_payment || paymentAmount === '') return
    setRecordingPayment(true)
    try {
      const updated = await apiFetch<PaymentRead>(`/payments/${result.pending_payment.payment_id}/collect-in-person`, {
        method: 'POST',
        body: JSON.stringify({ amount: String(paymentAmount) }),
      })
      notifications.show({ message: 'Payment recorded.', color: 'green' })
      setResult({
        ...result,
        pending_payment: {
          ...result.pending_payment,
          collected_in_person_amount: updated.collected_in_person_amount,
          collected_in_person_at: updated.collected_in_person_at,
        },
      })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Failed to record payment.', color: 'red' })
    } finally {
      setRecordingPayment(false)
    }
  }

  return (
    <Stack gap="md" maw={560}>
      <Title order={2}>Check-in Scanner</Title>
      <Text c="dimmed" size="sm">
        Point the camera at the patient's QR code (from their confirmation email) to mark them as arrived. Real check-in
        only — nobody can check in with just a photo of the code without also being logged in here as staff.
      </Text>

      {cameraError && (
        <Alert color="red" title="Camera unavailable">
          {cameraError}
        </Alert>
      )}

      <Paper withBorder radius="md" style={{ overflow: 'hidden', position: 'relative', aspectRatio: '4 / 3' }}>
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video
          ref={videoRef}
          muted
          playsInline
          style={{ width: '100%', height: '100%', objectFit: 'cover', display: result ? 'none' : 'block' }}
        />
        <canvas ref={canvasRef} style={{ display: 'none' }} />
        {submitting && !result && (
          <Text ta="center" py="md">
            Checking in…
          </Text>
        )}
        {activeFacingMode && !result && (
          <Badge
            color="dark"
            variant="filled"
            style={{ position: 'absolute', top: 8, right: 8, opacity: 0.85 }}
          >
            Camera: {activeFacingMode === 'environment' ? 'rear' : activeFacingMode === 'user' ? 'front' : activeFacingMode}
          </Badge>
        )}
      </Paper>

      {resultError && (
        <Paper withBorder p="md" radius="md">
          <Stack gap="sm">
            <Alert color={resultError.includes('already checked in') ? 'yellow' : 'red'} title="Could not check in">
              {resultError}
            </Alert>
            <Button size="md" fullWidth onClick={scanNext}>Scan next</Button>
          </Stack>
        </Paper>
      )}

      {result && (
        <Paper withBorder p="md" radius="md">
          <Stack gap="sm">
            {/* Large, banner-style terminal-state confirmation — a small
                pill is easy to miss on a phone screen glanced at quickly
                between patients. Two real, distinct states: ARRIVED (from
                the scan itself) and COMPLETED (only after the separate
                "mark service complete" action below), never conflated. */}
            <Paper
              radius="md"
              p="lg"
              ta="center"
              bg={completedAt ? 'var(--mantine-color-teal-1)' : 'var(--mantine-color-blue-1)'}
            >
              <Stack gap={4} align="center">
                <Text size="28px" fw={800} c={completedAt ? 'teal.9' : 'blue.9'}>
                  {completedAt ? '✓ SERVICE COMPLETE' : '✓ ARRIVED'}
                </Text>
                <Badge size="lg" color={completedAt ? 'teal' : 'blue'} variant="filled">
                  {completedAt ? 'completed' : result.status}
                </Badge>
              </Stack>
            </Paper>
            <Text size="sm">
              {result.customer_name} — {result.service_name}
            </Text>
            <Text size="sm" c="dimmed">
              Scheduled: {new Date(result.scheduled_at).toLocaleString()}
            </Text>
            <Text size="xs" c="dimmed">
              Checked in at: {new Date(result.checked_in_at).toLocaleString()}
            </Text>
            {completedAt && (
              <Text size="xs" c="dimmed">
                Marked complete at: {new Date(completedAt).toLocaleString()}
              </Text>
            )}
            {!completedAt && (
              <Button size="xl" fullWidth color="teal" onClick={markComplete} loading={completing}>
                Mark service complete
              </Button>
            )}

            {result.pending_payment && (
              <Paper withBorder p="sm" radius="md">
                <Stack gap="xs">
                  <Text size="sm" fw={600}>
                    Remaining balance
                  </Text>
                  <Text size="sm" c="dimmed">
                    Deposit of {result.pending_payment.currency} {result.pending_payment.amount} was{' '}
                    {result.pending_payment.status === 'completed' ? 'paid online' : 'not confirmed online'} — remaining{' '}
                    {result.pending_payment.currency} {result.pending_payment.remaining} due at the clinic.
                  </Text>
                  {result.pending_payment.collected_in_person_at ? (
                    <Text size="sm" c="green">
                      Recorded: {result.pending_payment.currency} {result.pending_payment.collected_in_person_amount}{' '}
                      collected at {new Date(result.pending_payment.collected_in_person_at).toLocaleString()}
                    </Text>
                  ) : (
                    // Deliberately a Stack (input above, full-width button
                    // below), not a side-by-side Group: on a real phone
                    // width this is the layout that's guaranteed to fit and
                    // stay comfortably tappable without depending on wrap
                    // behavior — and it reads perfectly fine at desktop
                    // width too, so there's no responsive-only special case
                    // to get wrong.
                    <Stack gap="xs">
                      <NumberInput
                        label="Amount received in person"
                        min={0}
                        decimalScale={2}
                        size="md"
                        value={paymentAmount}
                        onChange={(v) => setPaymentAmount(v === '' ? '' : Number(v))}
                      />
                      <Button
                        size="md"
                        fullWidth
                        onClick={recordPayment}
                        loading={recordingPayment}
                        disabled={paymentAmount === ''}
                      >
                        Record payment
                      </Button>
                    </Stack>
                  )}
                  <Text size="xs" c="dimmed">
                    This is a separate, explicit record — checking in never assumes payment was received.
                  </Text>
                </Stack>
              </Paper>
            )}

            <Button size="md" fullWidth onClick={scanNext}>Scan next</Button>
          </Stack>
        </Paper>
      )}
    </Stack>
  )
}
