import os
import re
import json
from fastapi import FastAPI
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from yt_dlp import YoutubeDL
from bs4 import BeautifulSoup

app = FastAPI()

def _clean_vtt_text(vtt_text: str) -> str:
    lines = []
    for line in vtt_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper() == "WEBVTT":
            continue
        if "-->" in stripped:
            continue
        if re.match(r"^\d+$", stripped):
            continue
        if stripped.lower().startswith("kind:"):
            continue
        if stripped.lower().startswith("language:"):
            continue
        stripped = re.sub(r"<[^>]+>", " ", stripped)
        lines.append(stripped)
    return " ".join(lines).replace("  ", " ").strip()


def _fetch_video_info(video_id: str, cookies_path: str | None, cookies_browser: str | None):
    """Fetch video info including description using yt-dlp"""
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "cookiefile": cookies_path or None,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }
    if cookies_browser and not cookies_path:
        ydl_opts["cookiesfrombrowser"] = (cookies_browser,)

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

    return info


def _fetch_via_ytdlp(video_id: str, lang: str, cookies_path: str | None, cookies_browser: str | None, info: dict | None = None):
    if info is None:
        info = _fetch_video_info(video_id, cookies_path, cookies_browser)

    captions = info.get("subtitles") or {}
    auto_captions = info.get("automatic_captions") or {}

    def pick_caption_url(store):
        entries = store.get(lang) or []
        for entry in entries:
            if entry.get("ext") == "vtt" and entry.get("url"):
                return entry["url"]
        for entry in entries:
            if entry.get("url"):
                return entry["url"]
        return None

    caption_url = pick_caption_url(captions) or pick_caption_url(auto_captions)
    if not caption_url:
        raise RuntimeError("No captions found for requested language")

    response = requests.get(caption_url, timeout=30)
    response.raise_for_status()
    return _clean_vtt_text(response.text), info


@app.get("/api/transcript")
def transcript(videoId: str, lang: str = "en"):
    cookies_path = os.getenv("TRANSCRIPT_COOKIES_PATH")
    cookies_browser = os.getenv("TRANSCRIPT_COOKIES_BROWSER")

    # First, fetch video info to get description (we'll use it as fallback)
    video_info = None
    description = None
    title = None

    try:
        video_info = _fetch_video_info(videoId, cookies_path, cookies_browser)
        description = video_info.get("description")
        title = video_info.get("title")
    except Exception:
        pass  # We'll try to get transcript anyway

    # Try primary transcript API first
    try:
        transcript_items = YouTubeTranscriptApi.get_transcript(
            videoId,
            languages=[lang],
            cookies=cookies_path,
        )
        text = " ".join([item.get("text", "") for item in transcript_items]).strip()
        if not text:
            raise RuntimeError("Empty transcript from primary API")
        return {
            "success": True,
            "videoId": videoId,
            "transcript": text,
            "description": description,
            "title": title,
        }
    except Exception as exc:
        # Fallback to yt-dlp for transcript
        try:
            text, info = _fetch_via_ytdlp(videoId, lang, cookies_path, cookies_browser, video_info)
            # Update description if we got it from fallback
            if info and not description:
                description = info.get("description")
                title = info.get("title")
            return {
                "success": True,
                "videoId": videoId,
                "transcript": text,
                "description": description,
                "title": title,
            }
        except Exception as fallback_exc:
            # No transcript available - return description as fallback for recipe extraction
            return {
                "success": False,
                "videoId": videoId,
                "error": f"{exc} | fallback: {fallback_exc}",
                "transcript": None,
                "description": description,
                "title": title,
            }


@app.get("/api/scrape-recipe")
def scrape_recipe(url: str):
    """Scrape a webpage for recipe data using JSON-LD structured data or page text."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Extract page title
        page_title = soup.title.string.strip() if soup.title and soup.title.string else None

        # Extract og:image for thumbnail
        og_image = None
        og_tag = soup.find("meta", property="og:image")
        if og_tag and og_tag.get("content"):
            og_image = og_tag["content"]

        # Look for JSON-LD structured data with Recipe schema
        recipe_data = None
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                recipe_data = _find_recipe_in_jsonld(data)
                if recipe_data:
                    break
            except (json.JSONDecodeError, TypeError):
                continue

        # Always extract body text as fallback
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        body_text = soup.get_text(separator="\n", strip=True)
        # Limit text length to avoid sending too much to AI
        if len(body_text) > 8000:
            body_text = body_text[:8000]

        if recipe_data:
            # Extract image from recipe data if not already found
            if not og_image and recipe_data.get("image"):
                img = recipe_data["image"]
                if isinstance(img, str):
                    og_image = img
                elif isinstance(img, list) and img:
                    og_image = img[0] if isinstance(img[0], str) else img[0].get("url", "")
                elif isinstance(img, dict):
                    og_image = img.get("url", "")

            # Check if recipe data is incomplete (missing instructions)
            has_instructions = recipe_data.get("recipeInstructions")

            return {
                "success": True,
                "recipe_data": recipe_data,
                "page_text": body_text if not has_instructions else None,
                "title": recipe_data.get("name") or page_title,
                "image_url": og_image,
            }

        return {
            "success": True,
            "recipe_data": None,
            "page_text": body_text,
            "title": page_title,
            "image_url": og_image,
        }

    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out"}
    except requests.exceptions.RequestException as exc:
        return {"success": False, "error": f"Failed to fetch page: {exc}"}
    except Exception as exc:
        return {"success": False, "error": f"Scraping failed: {exc}"}


def _find_recipe_in_jsonld(data):
    """Recursively search JSON-LD data for a Recipe schema object."""
    if isinstance(data, dict):
        schema_type = data.get("@type", "")
        # @type can be a string or list
        if isinstance(schema_type, list):
            types = schema_type
        else:
            types = [schema_type]

        if "Recipe" in types:
            return data

        # Check @graph array
        if "@graph" in data:
            result = _find_recipe_in_jsonld(data["@graph"])
            if result:
                return result

    elif isinstance(data, list):
        for item in data:
            result = _find_recipe_in_jsonld(item)
            if result:
                return result

    return None
