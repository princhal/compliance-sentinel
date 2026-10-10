export type Severity = "critical" | "high" | "medium" | "low";

export interface Repo {
  id: string;
  name: string;
  url: string;
  default_branch: string;
  last_commit: string | null;
  last_indexed_at: string | null;
}

export interface Run {
  id: string;
  repo_id: string;
  repo_name: string | null;
  commit: string | null;
  trigger: string;
  triggered_by: string | null;
  mode: string;
  status: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  engine: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  stats: { obligations?: number; static_hits?: number; findings?: Record<string, number>; errors?: string[] };
  error: string | null;
  report: { id: string; sha256: string; approved_by_name: string | null; approved_at: string | null } | null;
}

export interface Citation {
  obligation_id: string;
  regulation: string;
  section_ref: string;
  source_url: string;
  retrieved_at: string;
  quote: string;
}

export interface Finding {
  id: string;
  run_id: string;
  category: string;
  label: string;
  path: string;
  start_line: number;
  end_line: number;
  severity: Severity;
  status: "violation" | "needs_review" | "compliant";
  review_status: "open" | "accepted_risk" | "false_positive" | "fixed";
  rule_id: string | null;
  evidence: string;
  reasoning: string;
  confidence: number;
  citations: Citation[];
}

export interface Regulation {
  id: string;
  regulation: string;
  title: string;
  url: string;
  version: number;
  fetched_at: string;
  status: string;
}

export interface Obligation {
  id: string;
  regulation: string;
  section_ref: string;
  category: string;
  severity: Severity;
  summary: string;
  quote: string;
  source_url: string;
}

export interface OrgSettings {
  name: string;
  slack_webhook_configured: boolean;
  alert_emails: string[];
  alert_min_severity: Severity;
}
