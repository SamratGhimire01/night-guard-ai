export interface RegisterRequest {
  business_name: string
  timezone: string
  email: string
  password: string
}

export interface RegisterResponse {
  business_id: string
  user_id: string
  email: string
  role: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

export type LanguageMode = 'automatic' | 'ask'

export type ContentScope = 'single_business' | 'aggregator'

export interface BusinessRead {
  id: string
  name: string
  description: string | null
  address: string | null
  phone: string | null
  email: string | null
  website: string | null
  timezone: string
  currency: string
  languages: string[] | null
  tone: string | null
  sms_enabled: boolean
  follow_ups_enabled: boolean
  plan: 'free' | 'premium'
  brand_color: string
  logo_url: string | null
  payment_collection_enabled: boolean
  payment_providers: ('esewa' | 'khalti')[]
  reminder_enabled: boolean
  reminder_minutes_before: number
  language_mode: LanguageMode
  content_scope: ContentScope
  booking_enabled: boolean
}

export interface PaymentSettingsUpdate {
  payment_collection_enabled: boolean
  payment_providers: ('esewa' | 'khalti')[]
}

export interface PaymentRead {
  id: string
  business_id: string
  appointment_id: string
  provider: string
  amount: string
  currency: string
  status: 'pending' | 'completed' | 'failed'
  gateway_reference: string | null
  payment_url: string
  collected_in_person_amount: string | null
  collected_in_person_at: string | null
}

export interface BusinessUpdate {
  name?: string
  description?: string | null
  address?: string | null
  phone?: string | null
  email?: string | null
  website?: string | null
  timezone?: string
  currency?: string
  tone?: string | null
  brand_color?: string
  logo_url?: string | null
  reminder_enabled?: boolean
  reminder_minutes_before?: number
  language_mode?: LanguageMode
  content_scope?: ContentScope
  booking_enabled?: boolean
}

export interface PlanRead {
  business_id: string
  plan: 'free' | 'premium'
  features: string[]
}

export interface BusinessReferenceData {
  timezones: string[]
  currencies: string[]
}

export interface GoogleCalendarStatus {
  connected: boolean
  calendar_name: string | null
  // Google rejected the stored token (real check) — reconnect required.
  needs_reconnect: boolean
  // false = Google couldn't be reached, so the token's state is unknown.
  verified: boolean
}

export interface GoogleCalendarAuthorizationURL {
  authorization_url: string
}

export type ChannelType = 'whatsapp' | 'messenger' | 'instagram' | 'email'

export interface IntegrationRead {
  id: string
  type: ChannelType | 'google_calendar'
  // Secrets (access_token / page_access_token / app_password) are stripped by the backend
  // before this ever reaches the dashboard — write-only, like a password.
  config: Record<string, string>
  enabled: boolean
}

export interface IntegrationUpsert {
  type: ChannelType
  config: Record<string, string>
  enabled?: boolean
}

export interface IntegrationTestResult {
  ok: boolean
  detail: string
}

// WhatsApp Embedded Signup — a NEW, self-serve alternative to hand-typing
// IntegrationUpsert's whatsapp fields above. See ChannelsPage.tsx.
export interface WhatsAppEmbeddedSignupConfig {
  configured: boolean
  app_id: string
  config_id: string
  api_version: string
}

export interface ServiceRead {
  id: string
  business_id: string
  name: string
  description: string | null
  price: string
  duration_minutes: number
  staff_id: string | null
  deposit_enabled: boolean
  deposit_percentage: number | null
}

export interface ServiceWrite {
  name: string
  description?: string | null
  price: string
  duration_minutes: number
  staff_id?: string | null
  deposit_enabled?: boolean
  deposit_percentage?: number | null
}

export interface StaffRead {
  id: string
  business_id: string
  name: string
  role: string
}

export interface StaffWrite {
  name: string
  role: string
}

export type AppointmentStatus = 'pending' | 'confirmed' | 'arrived' | 'cancelled' | 'completed' | 'no_show'

export interface AppointmentListItem {
  id: string
  business_id: string
  customer_id: string
  service_id: string
  staff_id: string | null
  scheduled_at: string
  duration_minutes: number
  status: AppointmentStatus
  created_at: string
  group_booking_id: string | null
  customer_name: string
  service_name: string | null
  staff_name: string | null
  checked_in_at: string | null
  completed_at: string | null
}

export interface AppointmentRead {
  id: string
  business_id: string
  customer_id: string
  service_id: string
  staff_id: string | null
  scheduled_at: string
  duration_minutes: number
  status: AppointmentStatus
  created_at: string
  group_booking_id: string | null
  checked_in_at: string | null
  completed_at: string | null
}

export interface CheckinRequest {
  token: string
}

export interface PaymentCheckinInfo {
  payment_id: string
  amount: string
  currency: string
  remaining: string
  status: 'pending' | 'completed' | 'failed'
  collected_in_person_amount: string | null
  collected_in_person_at: string | null
}

export interface CheckinResponse {
  appointment_id: string
  status: AppointmentStatus
  checked_in_at: string
  customer_name: string
  service_name: string
  scheduled_at: string
  pending_payment: PaymentCheckinInfo | null
}

export interface RecordInPersonPaymentRequest {
  amount: string
}

export interface HandoffListItem {
  id: string
  conversation_id: string
  reason: string
  status: string
  resolved_at: string | null
  created_at: string
  customer_name: string
  channel: string
}

export interface BusinessHourDay {
  day_of_week: number
  closed: boolean
  open_time: string | null
  close_time: string | null
}

export interface HolidayException {
  id: string
  date: string
  closed: boolean
  open_time: string | null
  close_time: string | null
}

export interface HolidayExceptionCreate {
  date: string
  closed: boolean
  open_time?: string | null
  close_time?: string | null
}

export interface BusinessHoursResponse {
  weekly: BusinessHourDay[]
  exceptions: HolidayException[]
}

export type KnowledgeStatus = 'draft' | 'approved' | 'archived'

export interface KnowledgeDocumentRead {
  id: string
  business_id: string
  title: string
  content: string
  source: string
  status: KnowledgeStatus
  version: number
  approved_by: string | null
  approved_at: string | null
  created_at: string
  updated_at: string
}

// --- Reports (Phase 16/17/37) -----------------------------------------------

export interface RevenueEstimate {
  value: string
  appointment_count: number
  definition: string
}

export interface AppointmentReportRow {
  id: string
  scheduled_at: string
  status: string
  customer_name: string | null
  service_name: string | null
  staff_name: string | null
  group_booking_id: string | null
}

export interface DailyReport {
  business_id: string
  business_name: string
  timezone: string
  report_date: string
  appointments: AppointmentReportRow[]
  cancellations: unknown[]
  reschedules: unknown[]
  new_leads: unknown[]
  human_review: { count: number; implemented: boolean; note: string }
  revenue_estimate: RevenueEstimate
  summary: {
    appointments_scheduled: number
    appointments_by_status: Record<string, number>
    cancellations: number
    reschedules: number
    new_leads: number
    human_review_open_count: number
  }
}

interface RateWithDefinition {
  value: number | null
  numerator: number
  denominator: number
  definition: string
}

export interface MonthlyReport {
  business_id: string
  business_name: string
  timezone: string
  year: number
  month: number
  period_label: string
  conversations: { total: number }
  customers: { new: number; total_at_month_end: number }
  appointments: {
    requested: number
    scheduled_for_month: number
    cancellation_events_this_month: number
    cancelled_of_scheduled: number
    completed: { count: number; implemented: boolean; note: string }
    rescheduled: { events: number; distinct_appointments: number }
  }
  cancellation_rate: RateWithDefinition
  booking_conversion: RateWithDefinition
  revenue_estimate: RevenueEstimate
  busiest_days: { day: string; count: number }[]
  busiest_hours: { hour: number; count: number }[]
  most_requested_services: { service_id: string; service_name: string | null; count: number }[]
}

export interface YearlyReportMonth {
  month: number
  month_name: string
  appointments_requested: number
  appointments_scheduled: number
  cancelled: number
  revenue_estimate: string
}

export interface YearOverYearMetric {
  current: number | string
  prior: number | string
  change_pct: number | null
}

export type YearOverYear =
  | { available: true; prior_year: number; appointments_scheduled: YearOverYearMetric; revenue_estimate: YearOverYearMetric; new_customers: YearOverYearMetric }
  | { available: false; prior_year: number; note: string }

export interface YearlyReport {
  business_id: string
  business_name: string
  timezone: string
  year: number
  period_label: string
  conversations: { total: number }
  customers: { new: number }
  appointments: {
    requested: number
    scheduled_for_year: number
    cancelled_of_scheduled: number
    completed: { count: number; implemented: boolean; note: string }
    rescheduled: { events: number }
  }
  cancellation_rate: RateWithDefinition
  booking_conversion: RateWithDefinition
  revenue_estimate: RevenueEstimate
  month_by_month: YearlyReportMonth[]
  most_requested_services: { service_id: string; service_name: string | null; count: number }[]
  year_over_year: YearOverYear
}

// ---- Inbox (Phase 52) ----

export type InboxSender = 'customer' | 'agent' | 'staff'
export type DeliveryStatus = 'sent' | 'simulated' | 'failed' | 'suppressed' | 'pending'

export interface InboxListItem {
  id: string
  channel: string
  customer_name: string
  last_message_preview: string
  last_message_sender: InboxSender
  last_message_at: string
  last_message_delivery_status: DeliveryStatus | null
  needs_reply: boolean
  unread: boolean
  open_handoff: boolean
  takeover_active: boolean
  takeover_by_email: string | null
  lead_signal: LeadSignal
}

export type LeadSignal = 'high' | 'medium' | 'low' | null

export interface InboxSummary {
  needs_reply: number
  handoffs: number
  leads: number
}

export interface TakeoverState {
  active: boolean
  until: string | null
  taken_over_by: string | null
}

export interface InboxConversation {
  id: string
  channel: string
  customer_id: string
  customer_name: string
  customer_phone: string | null
  customer_email: string | null
  takeover: TakeoverState
  takeover_by_email: string | null
  reply: { can_reply: boolean; reason: string | null; window_closes_at: string | null }
  open_handoff: { id: string; reason: string } | null
  last_customer_message_at: string | null
  lead_signal: LeadSignal
  lead_summary: string | null
}

export interface InboxMessage {
  id: string
  sender_type: InboxSender
  content: string
  created_at: string
  delivery_status: DeliveryStatus | null
  delivery_detail: string | null
  sent_by_user_id: string | null
  sent_by_email: string | null
}
