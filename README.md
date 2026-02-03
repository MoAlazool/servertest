# Transcript API (Self-Hosted)

Minimal FastAPI wrapper around `youtube-transcript-api`.

## Local run
```bash
cd server/transcript-api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Optional: Cookies for restricted videos
Some videos require YouTube cookies to fetch transcripts. Export a cookies file
in Netscape format (e.g. using the "Get cookies.txt" browser extension), then:
```bash
export TRANSCRIPT_COOKIES_PATH=/path/to/cookies.txt
```

If you prefer not to export cookies, you can read them directly from your browser:
```bash
export TRANSCRIPT_COOKIES_BROWSER=chrome
```
Supported values depend on `yt-dlp` (e.g. `chrome`, `firefox`, `safari`).

You can also pass `lang`:
```
http://localhost:8000/api/transcript?videoId=VIDEO_ID&lang=en
```

## Render deploy (quick)
- Create a new Web Service from this repo.
- Root directory: `server/transcript-api`
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port 10000`

## App configuration
Set in `.env`:
```
EXPO_PUBLIC_TRANSCRIPT_API_URL=https://YOUR-SERVICE.onrender.com/api/transcript
```
