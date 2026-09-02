import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Clip, Health, Job, YouTubeConnection, YouTubeUpload } from "./types";

const activeStatuses = new Set(["queued", "downloading", "analyzing", "rendering"]);

export default function App() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<Job | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [youtube, setYoutube] = useState<YouTubeConnection | null>(null);
  const [url, setUrl] = useState("");
  const [rights, setRights] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refreshList = async () => {
    const result = await api.listJobs();
    setJobs(result);
    return result;
  };

  useEffect(() => {
    Promise.all([api.health(), refreshList(), api.youtubeStatus()])
      .then(([status, loadedJobs, youtubeStatus]) => {
        setHealth(status);
        setYoutube(youtubeStatus);
        if (loadedJobs[0]) setSelected(loadedJobs[0]);
      })
      .catch((cause) => setError(cause.message));
  }, []);

  useEffect(() => {
    if (!selected || (!activeStatuses.has(selected.status) && !selected.clips.some((clip) => clip.youtube_status === "uploading"))) return;
    const timer = window.setInterval(async () => {
      try {
        const updated = await api.getJob(selected.id);
        setSelected(updated);
        setJobs((items) => items.map((item) => (item.id === updated.id ? updated : item)));
      } catch (cause) {
        setError((cause as Error).message);
      }
    }, 1800);
    return () => window.clearInterval(timer);
  }, [selected?.id, selected?.status, selected?.clips.some((clip) => clip.youtube_status === "uploading")]);

  async function connectYoutube() {
    setError("");
    try {
      const result = await api.youtubeConnect();
      window.location.assign(result.authorization_url);
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  async function disconnectYoutube() {
    try {
      setYoutube(await api.youtubeDisconnect());
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!rights) {
      setError("Konfirmasikan hak atau izin penggunaan video terlebih dahulu.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const job = await api.createJob(url.trim());
      setJobs((items) => [job, ...items]);
      setSelected(job);
      setUrl("");
      setRights(false);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function chooseJob(job: Job) {
    setSelected(job);
    try {
      setSelected(await api.getJob(job.id));
    } catch (cause) {
      setError((cause as Error).message);
    }
  }

  const ready = health?.gemini_configured && Object.values(health.tools).every(Boolean);

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand" onClick={() => setSelected(null)}>
          <span className="brand-mark">V</span>
          <span>VidCutly</span>
          <small>LOCAL AI STUDIO</small>
        </button>
        <div className="topbar-actions">
          {youtube?.connected ? (
            <div className="youtube-account"><span className="youtube-dot">▶</span><div><small>CHANNEL YOUTUBE</small><strong>{youtube.channel_title}</strong></div><button onClick={disconnectYoutube}>Putuskan</button></div>
          ) : (
            <button className="youtube-connect" disabled={!youtube?.configured} onClick={connectYoutube}>▶ {youtube?.configured ? "Hubungkan YouTube" : "YouTube belum disetel"}</button>
          )}
          <div className={`system-pill ${ready ? "ready" : "warning"}`}>
            <span className="status-dot" />
            {ready ? "Sistem siap" : "Setup diperlukan"}
          </div>
        </div>
      </header>

      <main className="layout">
        <aside className="sidebar">
          <button className="new-project" onClick={() => setSelected(null)}><span>＋</span> Proyek baru</button>
          <div className="sidebar-heading">
            <span>PROYEK TERBARU</span>
            <span>{jobs.length}</span>
          </div>
          <div className="job-list">
            {jobs.map((job) => (
              <button
                key={job.id}
                className={`job-item ${selected?.id === job.id ? "active" : ""}`}
                onClick={() => chooseJob(job)}
              >
                <span className="job-icon">{job.status === "completed" ? "✓" : "▶"}</span>
                <span className="job-copy">
                  <strong>{job.title || "Podcast baru"}</strong>
                  <small>{statusLabel(job.status)} · {formatDate(job.created_at)}</small>
                </span>
              </button>
            ))}
            {!jobs.length && <p className="empty-small">Belum ada proyek.</p>}
          </div>
          <div className="local-note">
            <span>⌂</span>
            <div><strong>Data tetap lokal</strong><small>Video dan hasil render tidak masuk cloud selain analisis Gemini.</small></div>
          </div>
        </aside>

        <section className="content">
          {error && <div className="error-banner"><span>!</span>{error}<button onClick={() => setError("")}>×</button></div>}
          {!selected ? (
            <Landing
              url={url}
              setUrl={setUrl}
              rights={rights}
              setRights={setRights}
              loading={loading}
              health={health}
              onSubmit={create}
            />
          ) : (
            <JobWorkspace job={selected} youtube={youtube} onConnectYoutube={connectYoutube} onUpdate={(job) => {
              setSelected(job);
              setJobs((items) => items.map((item) => item.id === job.id ? job : item));
            }} onDeleted={(id) => {
              setJobs((items) => items.filter((item) => item.id !== id));
              setSelected(null);
            }} onError={setError} />
          )}
        </section>
      </main>
    </div>
  );
}

function Landing({ url, setUrl, rights, setRights, loading, health, onSubmit }: {
  url: string;
  setUrl: (value: string) => void;
  rights: boolean;
  setRights: (value: boolean) => void;
  loading: boolean;
  health: Health | null;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <div className="landing">
      <div className="eyebrow">AI-POWERED PODCAST CLIPPING</div>
      <h1>Satu podcast.<br /><em>Lima momen terbaik.</em></h1>
      <p className="lead">Tempel URL podcast Indonesia. Gemini membaca percakapan, suara, dan ekspresi—VidCutly menyiapkan clip vertikal untuk kamu review.</p>

      <form className="url-card" onSubmit={onSubmit}>
        <label htmlFor="youtube-url">URL video YouTube</label>
        <div className="url-row">
          <span className="youtube-icon">▶</span>
          <input id="youtube-url" type="url" required placeholder="https://youtube.com/watch?v=..." value={url} onChange={(event) => setUrl(event.target.value)} />
          <button className="primary" disabled={loading}>{loading ? "Memulai…" : "Analisis video"}<span>→</span></button>
        </div>
        <label className="checkbox-row">
          <input type="checkbox" checked={rights} onChange={(event) => setRights(event.target.checked)} />
          <span>Saya memiliki hak atau izin untuk mengunduh, mengedit, dan menggunakan video ini.</span>
        </label>
      </form>

      <div className="flow-row">
        {[["01", "PASTE", "Masukkan URL podcast"], ["02", "PILIH", "AI menemukan 5 momen"], ["03", "REVIEW", "Atur timing & headline"], ["04", "EXPORT", "Unduh video 9:16"]].map(([number, title, copy], index) => (
          <div className="flow-item" key={title}>
            <span>{number}</span><div><strong>{title}</strong><small>{copy}</small></div>{index < 3 && <b>→</b>}
          </div>
        ))}
      </div>

      {health && (!health.gemini_configured || !Object.values(health.tools).every(Boolean)) && (
        <div className="setup-hint">
          Setup belum lengkap. {!health.gemini_configured && <>Isi <code>GEMINI_API_KEY</code> di <code>.env</code>. </>}
          {Object.entries(health.tools).filter(([, available]) => !available).map(([tool]) => tool).length > 0 && <>Jalankan <code>./scripts/setup.sh</code> untuk menyiapkan tool lokal.</>}
        </div>
      )}
    </div>
  );
}

function JobWorkspace({ job, youtube, onConnectYoutube, onUpdate, onDeleted, onError }: { job: Job; youtube: YouTubeConnection | null; onConnectYoutube: () => void; onUpdate: (job: Job) => void; onDeleted: (id: string) => void; onError: (message: string) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [activeClip, setActiveClip] = useState<string | null>(job.clips[0]?.id || null);
  const [previewEnd, setPreviewEnd] = useState<number | null>(null);
  const [renderPreview, setRenderPreview] = useState<Clip | null>(null);
  const busy = activeStatuses.has(job.status);

  useEffect(() => setRenderPreview(null), [job.id]);

  useEffect(() => {
    if (!renderPreview) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setRenderPreview(null);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [renderPreview]);

  function preview(clip: Clip) {
    setActiveClip(clip.id);
    setPreviewEnd(clip.end_seconds);
    if (videoRef.current) {
      videoRef.current.currentTime = clip.start_seconds;
      videoRef.current.play().catch(() => undefined);
    }
  }

  async function retry() {
    try { onUpdate(await api.retryJob(job.id)); } catch (cause) { onError((cause as Error).message); }
  }

  async function remove() {
    if (!window.confirm("Hapus proyek beserta video dan semua hasil render secara permanen?")) return;
    try { await api.deleteJob(job.id); onDeleted(job.id); } catch (cause) { onError((cause as Error).message); }
  }

  return (
    <div className="workspace">
      <div className="workspace-head">
        <div><div className="eyebrow">PROJECT / {job.id.slice(0, 8).toUpperCase()}</div><h2>{job.title || "Menyiapkan podcast…"}</h2></div>
        <div className="head-actions"><button className="delete-button" disabled={busy} onClick={remove}>Hapus</button><span className={`status-badge ${job.status}`}>{statusLabel(job.status)}</span></div>
      </div>

      {(busy || job.status === "failed") && (
        <div className={`progress-card ${job.status === "failed" ? "failed" : ""}`}>
          <div className="progress-copy"><strong>{job.stage_message}</strong><span>{job.status === "failed" ? job.error : `${job.progress}%`}</span></div>
          <div className="progress-track"><i style={{ width: `${job.progress}%` }} /></div>
          {job.status === "failed" && <button className="secondary" onClick={retry}>Coba lagi</button>}
        </div>
      )}

      {job.source_url && (
        <div className="review-grid">
          <div className="video-panel">
            <div className="panel-label"><span>PREVIEW SUMBER</span><small>{formatTime(job.duration_seconds || 0)}</small></div>
            <video
              ref={videoRef}
              src={job.source_url}
              controls
              preload="metadata"
              onTimeUpdate={(event) => {
                if (previewEnd !== null && event.currentTarget.currentTime >= previewEnd) {
                  event.currentTarget.pause();
                }
              }}
            />
            {activeClip && <div className="preview-note">Preview dimulai dari kandidat yang dipilih. Render akhir akan berformat 9:16.</div>}
          </div>
          <div className="summary-panel">
            <div className="panel-label"><span>RINGKASAN AI</span></div>
            <p>{job.video_summary || "Gemini sedang menyusun ringkasan dan kandidat clip."}</p>
            <dl><div><dt>DURASI</dt><dd>{formatTime(job.duration_seconds || 0)}</dd></div><div><dt>KANDIDAT</dt><dd>{job.clips.length}/5</dd></div><div><dt>FORMAT</dt><dd>9:16</dd></div></dl>
          </div>
        </div>
      )}

      {!!job.clips.length && (
        <div className="clips-section">
          <div className="section-heading"><div><span>REKOMENDASI GEMINI</span><h3>5 momen dengan potensi tertinggi</h3></div><small>Review timing dan tulisan sebelum render</small></div>
          <div className="clip-list">
            {job.clips.map((clip) => <ClipCard key={clip.id} clip={clip} job={job} youtube={youtube} onConnectYoutube={onConnectYoutube} active={activeClip === clip.id} onPreview={() => preview(clip)} onRenderedPreview={() => setRenderPreview(clip)} onUpdate={async () => onUpdate(await api.getJob(job.id))} onError={onError} />)}
          </div>
        </div>
      )}
      {renderPreview?.output_url && (
        <div className="render-modal-backdrop" role="presentation" onMouseDown={() => setRenderPreview(null)}>
          <section className="render-modal" role="dialog" aria-modal="true" aria-labelledby="render-preview-title" onMouseDown={(event) => event.stopPropagation()}>
            <header><div><small>PREVIEW HASIL RENDER</small><h3 id="render-preview-title">{renderPreview.title}</h3></div><button aria-label="Tutup preview" onClick={() => setRenderPreview(null)}>×</button></header>
            <video key={renderPreview.output_url} src={renderPreview.output_url} poster={renderPreview.thumbnail_url || undefined} controls autoPlay playsInline preload="metadata" />
            <footer><span>{formatTime(renderPreview.end_seconds - renderPreview.start_seconds)} · Format 9:16</span><a href={renderPreview.output_url} download>↓ Unduh MP4</a></footer>
          </section>
        </div>
      )}
    </div>
  );
}

function ClipCard({ clip, job, youtube, onConnectYoutube, active, onPreview, onRenderedPreview, onUpdate, onError }: { clip: Clip; job: Job; youtube: YouTubeConnection | null; onConnectYoutube: () => void; active: boolean; onPreview: () => void; onRenderedPreview: () => void; onUpdate: () => Promise<void>; onError: (message: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [form, setForm] = useState({ start_seconds: clip.start_seconds, end_seconds: clip.end_seconds, title: clip.title, thumbnail_headline: clip.thumbnail_headline, framing_mode: clip.framing_mode });
  const [uploadForm, setUploadForm] = useState<YouTubeUpload>({
    title: clip.title,
    description: `Source: ${job.source_channel || "YouTube"}\n\n#shorts`,
    privacy_status: "private",
    tags: [...clip.keywords, "shorts"],
    made_for_kids: false
  });

  useEffect(() => setForm({ start_seconds: clip.start_seconds, end_seconds: clip.end_seconds, title: clip.title, thumbnail_headline: clip.thumbnail_headline, framing_mode: clip.framing_mode }), [clip]);

  async function save() {
    setSaving(true);
    try { await api.updateClip(job.id, clip.id, form); setEditing(false); await onUpdate(); } catch (cause) { onError((cause as Error).message); } finally { setSaving(false); }
  }

  async function render() {
    setSaving(true);
    try { if (editing) await api.updateClip(job.id, clip.id, form); await api.renderClip(job.id, clip.id); setEditing(false); await onUpdate(); } catch (cause) { onError((cause as Error).message); } finally { setSaving(false); }
  }

  async function upload() {
    setSaving(true);
    try {
      await api.uploadYouTube(job.id, clip.id, uploadForm);
      setShowUpload(false);
      await onUpdate();
    } catch (cause) {
      onError((cause as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <article className={`clip-card ${active ? "active" : ""}`}>
      <button className="rank" onClick={onPreview}><span>#{clip.rank}</span><strong>{clip.score}</strong><small>SCORE</small></button>
      <div className="clip-main">
        <div className="clip-title-row"><div><span className="timecode">{formatTime(clip.start_seconds)} — {formatTime(clip.end_seconds)} · {Math.round(clip.end_seconds - clip.start_seconds)} DETIK</span><h4>{clip.title}</h4></div><span className={`clip-status ${clip.status}`}>{clip.status}</span></div>
        <p>{clip.hook}</p>
        <div className="score-chips"><span>Hook {clip.scores.hook}</span><span>Insight {clip.scores.insight}</span><span>Emosi {clip.scores.emotion}</span><span>Unik {clip.scores.uniqueness}</span></div>
        <details><summary>Mengapa clip ini dipilih?</summary><p>{clip.reason}</p></details>

        {editing && <div className="editor-grid">
          <label>Mulai (detik)<input type="number" step="0.1" value={form.start_seconds} onChange={(e) => setForm({ ...form, start_seconds: Number(e.target.value) })} /></label>
          <label>Selesai (detik)<input type="number" step="0.1" value={form.end_seconds} onChange={(e) => setForm({ ...form, end_seconds: Number(e.target.value) })} /></label>
          <label className="wide">Judul dalam video<input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
          <label className="wide">Headline thumbnail<input value={form.thumbnail_headline} onChange={(e) => setForm({ ...form, thumbnail_headline: e.target.value })} /></label>
          <label className="wide">Framing video<select value={form.framing_mode} onChange={(e) => setForm({ ...form, framing_mode: e.target.value as Clip["framing_mode"] })}><option value="auto">Auto — zoom mengikuti orang dan adegan</option><option value="left">Kiri — kunci pembicara kiri</option><option value="center">Tengah — kunci bagian tengah</option><option value="right">Kanan — kunci pembicara kanan</option><option value="fit_blur">Full + Blur — tampilkan frame lengkap</option></select><small>{framingHelp(form.framing_mode)}</small></label>
        </div>}

        {clip.error && <p className="inline-error">{clip.error}</p>}
        {clip.youtube_error && <p className="inline-error">Upload YouTube: {clip.youtube_error}</p>}
        <div className="clip-actions">
          <button className="text-button" onClick={onPreview}>▶ Preview dari sini</button>
          <button className="text-button" onClick={() => setEditing(!editing)}>{editing ? "Batal edit" : "✎ Edit"}</button>
          {editing && <button className="secondary" disabled={saving} onClick={save}>Simpan</button>}
          <button className="primary compact" disabled={saving || clip.status === "rendering"} onClick={render}>{clip.status === "rendering" ? "Merender…" : clip.status === "rendered" ? "Render ulang" : "Render clip"}<span>→</span></button>
        </div>
        {clip.output_url && <div className="result-row"><a href={clip.output_url} download>↓ Unduh MP4</a>{clip.thumbnail_url && <a href={clip.thumbnail_url} download>↓ Unduh thumbnail</a>}</div>}
        {clip.status === "rendered" && (
          <div className="youtube-upload-row">
            {clip.youtube_status === "uploaded" && clip.youtube_url ? <a className="youtube-result" href={clip.youtube_url} target="_blank" rel="noreferrer">✓ Lihat di YouTube</a> :
              clip.youtube_status === "uploading" ? <div className="youtube-progress"><span>Mengunggah ke YouTube… {clip.youtube_progress}%</span><i><b style={{ width: `${clip.youtube_progress}%` }} /></i></div> :
              youtube?.connected ? <button className="youtube-upload-button" onClick={() => setShowUpload(!showUpload)}>▶ Upload ke YouTube</button> :
              <button className="youtube-upload-button" disabled={!youtube?.configured} onClick={onConnectYoutube}>▶ Hubungkan YouTube untuk upload</button>}
          </div>
        )}
        {showUpload && youtube?.connected && (
          <div className="youtube-form">
            <div className="youtube-form-head"><strong>Upload ke {youtube.channel_title}</strong><small>Default private agar bisa dicek dulu</small></div>
            <label>Judul<input maxLength={100} value={uploadForm.title} onChange={(event) => setUploadForm({ ...uploadForm, title: event.target.value })} /></label>
            <label>Deskripsi<textarea maxLength={5000} rows={4} value={uploadForm.description} onChange={(event) => setUploadForm({ ...uploadForm, description: event.target.value })} /></label>
            <div className="youtube-form-grid">
              <label>Visibilitas<select value={uploadForm.privacy_status} onChange={(event) => setUploadForm({ ...uploadForm, privacy_status: event.target.value as YouTubeUpload["privacy_status"] })}><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select></label>
              <label className="kids-check"><input type="checkbox" checked={uploadForm.made_for_kids} onChange={(event) => setUploadForm({ ...uploadForm, made_for_kids: event.target.checked })} /><span>Dibuat untuk anak-anak</span></label>
            </div>
            <button className="primary" disabled={saving || !uploadForm.title.trim()} onClick={upload}>{saving ? "Menyiapkan…" : `Upload ${uploadForm.privacy_status}`}<span>→</span></button>
          </div>
        )}
      </div>
      {clip.thumbnail_url && <button className="thumb-preview-button" onClick={onRenderedPreview} title="Preview video hasil render" aria-label={`Preview video ${clip.title}`}><img className="thumb-preview" src={clip.thumbnail_url} alt="" /><span>▶</span></button>}
    </article>
  );
}

function formatTime(value: number) { const seconds = Math.max(0, Math.round(value)); const h = Math.floor(seconds / 3600); const m = Math.floor((seconds % 3600) / 60); const s = seconds % 60; return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`; }
function formatDate(value: string) { return new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value)); }
function statusLabel(status: Job["status"]) { return ({ queued: "Antre", downloading: "Mengunduh", analyzing: "Menganalisis", ready: "Siap direview", rendering: "Merender", completed: "Selesai", failed: "Gagal" })[status]; }
function framingHelp(mode: Clip["framing_mode"]) { return ({ auto: "Default: satu orang dicrop dekat; dua orang atau adegan lebar otomatis di-zoom out dengan latar blur.", left: "Gunakan jika pembicara utama selalu berada di sisi kiri video sumber.", center: "Gunakan untuk objek atau pembicara yang memang berada di tengah.", right: "Gunakan jika pembicara utama selalu berada di sisi kanan video sumber.", fit_blur: "Paling aman ketika semua bagian video sumber harus selalu terlihat." })[mode]; }
