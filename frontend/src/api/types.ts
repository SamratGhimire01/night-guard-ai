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
}

export interface PlanRead {
  business_id: string
  plan: 'free' | 'premium'
  features: string[]
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
