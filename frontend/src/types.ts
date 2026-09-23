export type Grade = 'Junior' | 'Middle' | 'Senior' | 'Lead'
export type SkillType = 'hard' | 'soft'
export interface User {
  user_id: string; username: string; role: 'employee' | 'hr'; employee_id: string | null
}
export interface Session {
  access_token: string; expires_at: string; token_type: 'bearer'; user: User
}
export interface Employee {
  employee_id: string; full_name: string; department: string; role: string; grade: Grade
  manager_id: string | null; hire_date: string; tenure_months: number
  work_format: 'office' | 'hybrid' | 'remote'; preferred_language: 'kk' | 'ru' | 'en'
  career_goal: { target_role: string; target_grade: Grade } | null
  skills: Record<string, number>; last_review_date: string
}
export interface Skill {
  skill_id: string; name: string; type: SkillType; category: string; description: string
}
export interface Catalog {
  proficiency_scale: Record<string, string>; skills: Skill[]
  role_profiles: { role: string; grade: Grade; required_skills: Record<string, number>; critical_skills: string[] }[]
}
export type HistoryStatus = 'completed' | 'in_progress' | 'dropped' | 'no_show' | 'declined' | 'overdue'
export interface HistoryRecord {
  record_id: string; employee_id: string; event_id: string; date: string; due_date: string | null
  status: HistoryStatus; completion_pct: number; score: number | null; feedback_rating: number | null
  assigned_by: 'self' | 'manager' | 'hr'; completed_at: string | null
}
export interface Activity {
  event_id: string; title: string; description: string; type: string
  format: 'online' | 'offline' | 'self_paced'; duration_hours: number; mandatory: boolean
}
export interface Requirement {
  skill_id: string; name: string; type: SkillType; current_level: number; required_level: number
  gap: number; critical: boolean
}
export interface Trajectory {
  target_source?: 'explicit' | 'automatic' | null
  current_skills?: Record<string, number>
  employee_id: string; as_of_date: string; assessed_on: string; mode: 'mock' | 'live'
  skills_basis: 'last_review' | 'current'; target: Employee['career_goal']
  status: 'target_set' | 'no_goal' | 'target_unavailable'; requirements: Requirement[]
  met_count: number; critical_gap_count: number; progress_pct: number | null; message: string
}
export interface DashboardData {
  profile: Employee; catalog: Catalog; history: HistoryRecord[]; events: Activity[]; trajectory: Trajectory
}
export interface SkillChange {
  skill_id: string; name: string; before: number; after: number; gain: number
}
export interface PreviewBasis {
  mode: 'mock' | 'live'; skills_basis: 'last_review' | 'current'; assessed_on: string | null
  is_fallback: boolean; fallback_reason: string | null; message: string
}
export interface Recommendation {
  readiness_before?: number | null; readiness_after?: number | null
  explanation?: string | null; why_this?: string | null; why_not?: string | null
  expected_career_impact?: string | null; caution?: string | null
  explanation_source?: 'llm' | 'deterministic' | null
  event_id: string; title: string; format: Activity['format']; duration_hours: number
  session_date: string | null; reasons: string[]; score: number | null; skill_changes: SkillChange[]
}
export interface Recommendations extends PreviewBasis {
  employee_id: string; as_of_date: string; current_skills: Record<string, number>
  progress_pct: number | null; items: Recommendation[]
}
export interface Simulation extends PreviewBasis {
  employee_id: string; event_id: string; as_of_date: string; session_date: string | null
  skills_before: Record<string, number>; skills_after: Record<string, number>
  progress_before_pct: number | null; progress_after_pct: number | null; skill_changes: SkillChange[]
}

export interface CompletionResult {
  replayed: boolean
  completion: { completion_id: string; event_id: string; session_date: string | null; result: Simulation }
}
export interface HREmployee {
  employee_id: string; full_name: string; department: string; role: string; grade: Grade
  recommendation_status: 'available' | 'none' | 'unavailable'; reason: string; critical_gap_count: number | null
}
export interface HROverview {
  as_of_date: string; mode: 'mock' | 'live'; message: string; no_step_count: number; unavailable_count: number
  employees: HREmployee[]
  skill_gaps: { skill_id: string; name: string; employees_count: number; critical_count: number }[]
  events: { event_id: string; title: string; participants: number; records: number; completed: number; in_progress: number; other: number }[]
}
export interface ImportResult {
  dry_run: boolean; employees_added: number; employees_skipped: number; history_added: number; history_skipped: number; employee_ids: string[]
}
