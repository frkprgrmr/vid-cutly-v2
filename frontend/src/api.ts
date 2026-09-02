import type { Clip, Health, Job, YouTubeConnection, YouTubeUpload } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers }
  });
  if (!response.ok) {
    let message = `Request gagal (${response.status})`;
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // Keep the HTTP fallback.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/health"),
  listJobs: () => request<Job[]>("/api/jobs"),
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),
  deleteJob: async (id: string) => {
    const response = await fetch(`/api/jobs/${id}`, { method: "DELETE" });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "Proyek gagal dihapus");
    }
  },
  createJob: (url: string) =>
    request<Job>("/api/jobs", {
      method: "POST",
      body: JSON.stringify({ url, rights_confirmed: true })
    }),
  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: "POST" }),
  updateClip: (jobId: string, clipId: string, data: Partial<Clip>) =>
    request<Clip>(`/api/jobs/${jobId}/clips/${clipId}`, {
      method: "PATCH",
      body: JSON.stringify(data)
    }),
  renderClip: (jobId: string, clipId: string) =>
    request<Clip>(`/api/jobs/${jobId}/clips/${clipId}/render`, { method: "POST" }),
  youtubeStatus: () => request<YouTubeConnection>("/api/youtube/status"),
  youtubeConnect: () => request<{ authorization_url: string }>("/api/youtube/connect", { method: "POST" }),
  youtubeDisconnect: () => request<YouTubeConnection>("/api/youtube/disconnect", { method: "POST" }),
  uploadYouTube: (jobId: string, clipId: string, data: YouTubeUpload) =>
    request<Clip>(`/api/jobs/${jobId}/clips/${clipId}/youtube-upload`, {
      method: "POST",
      body: JSON.stringify(data)
    })
};
