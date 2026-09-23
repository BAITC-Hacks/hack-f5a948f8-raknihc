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
  employee_id: string; as_of_date: string; assessed_on: string; mode: 'mock' | 'live'
  skills_basis: 'last_review' | 'current'; target: Employee['career_goal']
  status: 'target_set' | 'no_goal' | 'target_unavailable'; requirements: Requirement[]
  met_count: number; critical_gap_count: number; progress_pct: number | null; message: string
}
export interface DashboardData {
  profile: Employee; catalog: Catalog; history: HistoryRecord[]; events: Activity[]; trajectory: Trajectory
}
