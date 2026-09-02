from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from google import genai
from google.genai import types

from backend.config import settings
from backend.schemas import GeminiAnalysis


ANALYSIS_PROMPT = """
Anda adalah editor short-form senior untuk podcast Indonesia. Analisis SATU video ini dari
audio, transkrip, ekspresi wajah, perubahan energi suara, dan konteks percakapan.

Pilih 5 kandidat clip terbaik yang masing-masing berdurasi 25–90 detik. Kandidat harus:
- memiliki hook yang kuat dalam 1–3 detik pertama;
- dapat dipahami tanpa menonton podcast penuh;
- tidak memotong kalimat atau kesimpulan penting;
- mengutamakan insight, emosi, humor, konflik sehat, atau sudut pandang unik;
- tidak saling tumpang tindih lebih dari 5 detik;
- memakai timestamp detik yang akurat dari awal video.

Beri skor 0–100 untuk hook, insight, emotion, uniqueness, standalone, dan short_form_fit.
Skor total mengikuti bobot: hook 25%, insight 20%, emotion 15%, uniqueness 15%,
standalone 15%, short_form_fit 10%.

Judul dan thumbnail_headline harus menarik dalam Bahasa Indonesia, tetapi tidak boleh
menyatakan sesuatu yang tidak benar-benar ada pada segmen. Keywords berisi maksimal
8 kata/frasa penting dari ucapan untuk disorot pada subtitle.

Untuk setiap kandidat, transkripsikan dialog segmen menjadi subtitles. Gunakan timestamp
absolut dari awal video, potong menjadi frasa pendek maksimal 8 kata, dan jangan mengarang
ucapan. Subtitle ini menjadi fallback bila subtitle YouTube tidak tersedia.

Urutkan kandidat dari skor total tertinggi. Keluarkan hanya JSON tanpa markdown dengan
struktur persis berikut. Semua key wajib ada pada setiap kandidat dan subtitle:

{
  "video_summary": "ringkasan video",
  "clips": [
    {
      "start_seconds": 0.0,
      "end_seconds": 30.0,
      "score": 90,
      "scores": {
        "hook": 90,
        "insight": 90,
        "emotion": 90,
        "uniqueness": 90,
        "standalone": 90,
        "short_form_fit": 90
      },
      "title": "judul clip",
      "thumbnail_headline": "headline thumbnail",
      "hook": "alasan hook menarik",
      "reason": "alasan kandidat dipilih",
      "keywords": ["kata penting"],
      "subtitles": [
        {"start_seconds": 0.0, "end_seconds": 2.0, "text": "ucapan"}
      ]
    }
  ]
}
"""


def analyze_youtube(url: str) -> GeminiAnalysis:
    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY belum diatur. Salin .env.example menjadi .env lalu isi API key."
        )

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=types.Content(
            parts=[
                types.Part(file_data=types.FileData(file_uri=_canonical_youtube_url(url))),
                types.Part(text=ANALYSIS_PROMPT),
            ]
        ),
        config=_generation_config(),
    )
    if isinstance(response.parsed, GeminiAnalysis):
        analysis = response.parsed
    else:
        analysis = GeminiAnalysis.model_validate_json(response.text)
    analysis.clips = _deduplicate_and_rank(analysis.clips)
    if len(analysis.clips) < 5:
        raise RuntimeError("Gemini tidak menghasilkan lima kandidat clip yang valid")
    return analysis


def _generation_config() -> types.GenerateContentConfig:
    # Gemini 3.6 Flash tidak menerima parameter sampling lama seperti
    # temperature, top_p, dan top_k. Schema kompleks juga ditolak oleh
    # generateContent, sehingga format diarahkan melalui prompt lalu hasilnya
    # divalidasi ketat dengan GeminiAnalysis di bawah.
    return types.GenerateContentConfig(
        response_mime_type="application/json",
    )


def _canonical_youtube_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
    else:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else url


def _deduplicate_and_rank(clips):
    ranked = sorted(clips, key=lambda clip: clip.score, reverse=True)
    selected = []
    for clip in ranked:
        overlap = False
        for existing in selected:
            intersection = max(
                0,
                min(clip.end_seconds, existing.end_seconds)
                - max(clip.start_seconds, existing.start_seconds),
            )
            if intersection > 5:
                overlap = True
                break
        if not overlap:
            selected.append(clip)
        if len(selected) == 5:
            break
    return selected
