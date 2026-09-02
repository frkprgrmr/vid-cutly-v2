export type ScoreBreakdown = {
  hook: number;
  insight: number;
  emotion: number;
  uniqueness: number;
  standalone: number;
  short_form_fit: number;
};

export type Clip = {
  id: string;
  job_id: string;
  rank: number;
  start_seconds: number;
  end_seconds: number;
  score: number;
  scores: ScoreBreakdown;
  title: string;
  thumbnail_headline: string;
  hook: string;
  reason: string;
  keywords: string[];
  status: "pending" | "selected" | "rendering" | "rendered" | "failed";
  output_url?: string | null;
  thumbnail_url?: string | null;
  error?: string | null;
  framing_mode: "auto" | "left" | "center" | "right" | "fit_blur" | "split";
  youtube_status: "idle" | "uploading" | "uploaded" | "failed";
  youtube_progress: number;
  youtube_video_id?: string | null;
  youtube_url?: string | null;
  youtube_error?: string | null;
};

export type Job = {
  id: string;
  url: string;
  title?: string | null;
  duration_seconds?: number | null;
  status: "queued" | "downloading" | "analyzing" | "ready" | "rendering" | "completed" | "failed";
  progress: number;
  stage_message: string;
  rights_confirmed: boolean;
  source_url?: string | null;
  source_channel?: string | null;
  video_summary?: string | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
  clips: Clip[];
};

export type Health = {
  ok: boolean;
  gemini_configured: boolean;
  gemini_model: string;
  youtube_configured: boolean;
  tools: Record<string, boolean>;
};

export type YouTubeConnection = {
  configured: boolean;
  connected: boolean;
  channel_id?: string | null;
  channel_title?: string | null;
};

export type YouTubeUpload = {
  title: string;
  description: string;
  privacy_status: "private" | "unlisted" | "public";
  tags: string[];
  made_for_kids: boolean;
};
