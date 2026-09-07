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

export interface BusinessRead {
  id: string
  name: string
  description: string | null
  address: string | null
  phone: string | null
  email: string | null
  website: string | null
  timezone: string
  languages: string[] | null
  tone: string | null
  sms_enabled: boolean
  follow_ups_enabled: boolean
  plan: 'free' | 'premium'
  brand_color: string
  logo_url: string | null
}

export interface BusinessUpdate {
  name?: string
  description?: string | null
  address?: string | null
  phone?: string | null
  email?: string | null
  website?: string | null
  timezone?: string
  tone?: string | null
  brand_color?: string
  logo_url?: string | null
}

export interface PlanRead {
  business_id: string
  plan: 'free' | 'premium'
  features: string[]
}

export interface GoogleCalendarStatus {
  connected: boolean
  calendar_name: string | null
}

export interface GoogleCalendarAuthorizationURL {
  authorization_url: string
}

export interface ServiceRead {
  id: string
  business_id: string
  name: string
  description: string | null
  price: string
  duration_minutes: number
  staff_id: string | null
}

export interface ServiceWrite {
  name: string
  description?: string | null
  price: string
  duration_minutes: number
  staff_id?: string | null
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
