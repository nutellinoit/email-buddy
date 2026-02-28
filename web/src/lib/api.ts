const API_URL = process.env.API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, revalidate = 30): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    next: { revalidate },
  });
  if (!res.ok) {
    throw new Error(`API ${path}: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// --- Types ---

export interface CategoryConfig {
  name: string;
  folder: string;
  threshold: number;
  description: string;
  is_default: boolean;
}

export interface AppConfig {
  categories: CategoryConfig[];
  llm_model: string;
  process_interval: number;
  idle_enabled: boolean;
  email_limit: number;
  email_fetch_days: number;
  dry_run: boolean;
  learning_enabled: boolean;
  learning_retention_days: number;
  daily_summary_enabled: boolean;
  daily_summary_hour: number;
  email_retention_days: number;
}

export interface Statistics {
  total_processed: number;
  by_classification: Record<string, number>;
  recent_processed_24h: number;
  average_confidence: Record<string, number>;
  database_path: string;
}

export interface PeriodStats {
  total_processed: number;
  by_classification: Record<string, number>;
  average_confidence: Record<string, number>;
  top_senders: Record<string, number>;
  learning_entries: number;
}

export interface TimelineBucket {
  period: string;
  [classification: string]: string | number;
}

export interface ProcessedEmail {
  id: number | null;
  email_id: string;
  message_id: string;
  subject: string;
  sender: string;
  date_received: string;
  classification: string;
  confidence: number;
  reason: string;
  folder_moved_to: string | null;
  processed_at: string;
  content_hash: string;
}

export interface LearningStats {
  total_learning_entries: number;
  by_learning_type: Record<string, number>;
  recent_learning_7d: number;
  top_learning_domains: Record<string, number>;
}

export interface DailySummary {
  id: number | null;
  generated_at: string;
  period_start: string;
  period_end: string;
  total_processed: number;
  stats_json: string;
  narrative: string | null;
  delivered: boolean;
}

export interface HealthStatus {
  status: string;
  database: string;
  database_exists: boolean;
}

// --- API functions ---

export const getHealth = () => apiFetch<HealthStatus>("/api/health", 10);
export const getConfig = () => apiFetch<AppConfig>("/api/config", 60);
export const getStats = () => apiFetch<Statistics>("/api/stats");
export const getStatsSince = (hours = 24) =>
  apiFetch<PeriodStats>(`/api/stats/since?hours=${hours}`);
export const getTimeline = (hours = 168) =>
  apiFetch<TimelineBucket[]>(`/api/stats/timeline?hours=${hours}`);
export const getEmails = (limit = 50, classification?: string) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (classification) params.set("classification", classification);
  return apiFetch<ProcessedEmail[]>(`/api/emails?${params}`);
};
export const getRecentEmails = (hours = 24, limit = 20) =>
  apiFetch<ProcessedEmail[]>(`/api/emails/recent?hours=${hours}&limit=${limit}`);
export const getLearningStats = () =>
  apiFetch<LearningStats>("/api/learning/stats");
export const getLearning = (limit = 10, days = 30) =>
  apiFetch<string[]>(`/api/learning?limit=${limit}&days=${days}`);
export const getSummaries = (limit = 7) =>
  apiFetch<DailySummary[]>(`/api/summaries?limit=${limit}`);
