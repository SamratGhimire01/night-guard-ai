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
