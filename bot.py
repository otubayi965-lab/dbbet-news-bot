"""
DBbet World - Football News Auto-Poster
----------------------------------------
This script:
  1. Fetches the latest football news from free RSS feeds
  2. Rewrites the text in a punchy, branded style (using Claude if an API key is set,
     otherwise a simple template)
  3. Downloads the article image and overlays a headline + logo/text band on it
  4. Posts the result (photo + caption) to your Telegram channel
  5. Reacts to the posted message with a random premium (custom) emoji from
     emoji_ids.json in the repo root
  6. Remembers what it already posted (state/posted.json) so it never repeats a story

Run manually with:  python bot.py
Runs automatically via .github/workflows/post.yml on a schedule.
"""

import os
import io
import re
import json
import random
import requests
import feedparser
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

RSS_FEEDS = [
    "http://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.espn.com/espn/rss/soccer/news",
    "https://www.theguardian.com/football/rss",
    "https://www.skysports.com/rss/12040",
]

STATE_FILE = "state/posted.json"
EMOJI_IDS_FILE = "emoji_ids.json"  # root of the repo
CHANNEL_HANDLE = "@DBbetWorld"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")  # optional

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
    raise SystemExit(
        "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID environment variables. "
        "Set them as GitHub Secrets (see README.md)."
    )


# ---------------------------------------------------------------------------
# STATE (avoid posting the same story twice)
# ---------------------------------------------------------------------------

def load_posted():
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        try:
            return set(json.load(f))
        except json.JSONDecodeError:
            return set()


def save_posted(posted):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(posted)[-500:], f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# PREMIUM EMOJI IDS
# ---------------------------------------------------------------------------

def load_emoji_ids():
    """Reads the list of premium (custom) emoji IDs from emoji_ids.json.

    Supports two possible formats:
      1. A flat list:            ["5368324170671202286", "5368...", ...]
      2. A list of objects:      [{"id": "5368...", "name": "fire"}, ...]
    Returns a flat list of ID strings either way.
    """
    if not os.path.exists(EMOJI_IDS_FILE):
        print(f"No {EMOJI_IDS_FILE} found, skipping reactions.")
        return []

    with open(EMOJI_IDS_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Could not parse {EMOJI_IDS_FILE}:", e)
            return []

    ids = []
    if isinstance(data, dict):
        # Format: {"🥇": "5301075711644153578", "🔥": "5317058732356542197", ...}
        # We want the VALUES (the numeric custom_emoji_id), not the emoji keys.
        for value in data.values():
            if isinstance(value, str) and value.isdigit():
                ids.append(value)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict) and "id" in item:
                ids.append(str(item["id"]))

    print(f"Loaded {len(ids)} premium emoji IDs from {EMOJI_IDS_FILE}.")
    return ids


# ---------------------------------------------------------------------------
# FETCH NEWS
# ---------------------------------------------------------------------------

def extract_image(entry):
    if "media_content" in entry and entry.media_content:
        return entry.media_content[0].get("url")
    if "media_thumbnail" in entry and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url")
    for link in entry.get("links", []):
        if link.get("type", "").startswith("image"):
            return link.get("href")
    return None


def get_high_res_image(article_url):
    """Fetch the article page and pull its og:image (full-resolution photo)
    instead of the tiny RSS thumbnail, which is what caused blurry posts."""
    try:
        resp = requests.get(
            article_url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; DBbetBot/1.0)"},
        )
        resp.raise_for_status()
        match = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            resp.text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1)
    except Exception as e:
        print("Could not fetch high-res image, falling back to thumbnail:", e)
    return None


def get_latest_news(posted):
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            uid = entry.get("id", entry.get("link"))
            if uid in posted:
                continue
            image_url = extract_image(entry)
            if not image_url:
                continue  # skip stories without an image
            return {
                "id": uid,
                "title": entry.title,
                "summary": getattr(entry, "summary", ""),
                "link": entry.link,
                "image_url": image_url,
            }
    return None


# ---------------------------------------------------------------------------
# REWRITE TEXT (Claude, optional)
# ---------------------------------------------------------------------------

def rewrite_text(title, summary):
    fallback = f"\u26bd {title}\n\n{summary}\n\n{CHANNEL_HANDLE}"

    if not ANTHROPIC_API_KEY:
        return fallback

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 300,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Rewrite this football news into a punchy, exclusive-sounding "
                            "Telegram post for a football/betting channel called DBbet World. "
                            "Use 1-2 relevant emojis, keep it under 80 words, no hashtags, "
                            f"and end with {CHANNEL_HANDLE}.\n\n"
                            f"Title: {title}\nSummary: {summary}"
                        ),
                    }
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"].strip()
    except Exception as e:
        print("AI rewrite failed, using fallback template:", e)
        return fallback


# ---------------------------------------------------------------------------
# BUILD BRANDED IMAGE
# ---------------------------------------------------------------------------

def escape_html(text):
    """Escapes special characters so the caption is safe to send with parse_mode=HTML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_caption_with_premium_emoji(caption, emoji_ids, fallback_emoji="\U0001F525"):
    """Builds an HTML-formatted caption that embeds one premium (custom) emoji
    INSIDE the message text itself (not as a reaction).

    Uses Telegram's special <tg-emoji emoji-id="..."> tag, which requires
    parse_mode="HTML" on the send call. The visible character inside the tag
    (fallback_emoji) is what shows up for clients/users that can't render
    custom emoji (e.g. non-Telegram-Premium accounts on some platforms) --
    Telegram Premium users will see the actual premium/animated emoji instead.
    """
    safe_caption = escape_html(caption)

    if not emoji_ids:
        # No premium emoji available, just return the plain (escaped) caption.
        return safe_caption

    emoji_id = random.choice(emoji_ids)
    premium_tag = f'<tg-emoji emoji-id="{emoji_id}">{fallback_emoji}</tg-emoji>'

    return f"{safe_caption} {premium_tag}"


def add_logo_watermark(img, logo_path="logo.png", size_ratio=0.16, margin=24):
    """Paste the channel logo (cropped to a circle) in the top-right corner."""
    if not os.path.exists(logo_path):
        return img  # no logo file committed yet, skip silently

    try:
        logo = Image.open(logo_path).convert("RGBA")
        logo_size = int(img.width * size_ratio)
        logo = logo.resize((logo_size, logo_size))

        # Crop to a circle regardless of the source image's shape
        mask = Image.new("L", logo.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, logo.size[0], logo.size[1]), fill=255)
        logo.putalpha(mask)

        base = img.convert("RGBA")
        position = (base.width - logo_size - margin, margin)
        base.paste(logo, position, logo)
        return base.convert("RGB")
    except Exception as e:
        print("Could not add logo watermark:", e)
        return img


def build_image(image_url, headline):
    resp = requests.get(image_url, timeout=30)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content)).convert("RGBA")

    # Dark gradient band at the bottom for legible text
    band_height = 260
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle(
        [(0, img.height - band_height), (img.width, img.height)],
        fill=(0, 0, 0, 175),
    )
    img = Image.alpha_composite(img, overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Font: put a .ttf file in assets/font.ttf for full Persian/Latin support.
    # Falls back to a basic font if none is provided.
    font_path = "assets/font.ttf"
    try:
        font = ImageFont.truetype(font_path, 42)
        small_font = ImageFont.truetype(font_path, 28)
    except Exception:
        font = ImageFont.load_default()
        small_font = font

    # Word-wrap headline to fit image width
    max_width = img.width - 80
    words = headline.split()
    lines, line = [], ""
    for w in words:
        test = f"{line} {w}".strip()
        if draw.textlength(test, font=font) > max_width:
            lines.append(line)
            line = w
        else:
            line = test
    if line:
        lines.append(line)
    lines = lines[:4]  # cap at 4 lines so it never overflows the band

    y = img.height - band_height + 25
    for line in lines:
        draw.text((40, y), line, font=font, fill="white")
        y += 50

    draw.text((40, img.height - 40), CHANNEL_HANDLE, font=small_font, fill="#e63946")

    img = add_logo_watermark(img)

    out_path = "output.jpg"
    img.save(out_path, "JPEG", quality=92)
    return out_path


# ---------------------------------------------------------------------------
# POST TO TELEGRAM
# ---------------------------------------------------------------------------

def send_photo(photo_path, caption, parse_mode=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    data = {"chat_id": TELEGRAM_CHANNEL_ID, "caption": caption}
    if parse_mode:
        data["parse_mode"] = parse_mode
    with open(photo_path, "rb") as f:
        resp = requests.post(
            url,
            data=data,
            files={"photo": f},
            timeout=60,
        )
    result = resp.json()
    if not result.get("ok"):
        print(
            f"sendPhoto failed: error_code={result.get('error_code')} "
            f"description={result.get('description')}"
        )
    resp.raise_for_status()
    return result


def react_with_standard_emoji(message_id, emoji="\U0001F525"):
    """Diagnostic helper: reacts with a plain, non-premium emoji (default: fire).
    If THIS fails too, the problem is permissions/settings, not the emoji IDs.
    If THIS succeeds but the premium/custom one fails, the problem is specifically
    with the values inside emoji_ids.json (they are probably not reaction-eligible)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMessageReaction"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "message_id": message_id,
        "reaction": json.dumps([{"type": "emoji", "emoji": emoji}]),
        "is_big": False,
    }
    try:
        resp = requests.post(url, data=payload, timeout=15)
        result = resp.json()
        if result.get("ok"):
            print(f"[DIAGNOSTIC] Standard emoji reaction succeeded with {emoji}.")
            return True
        else:
            print(
                f"[DIAGNOSTIC] Standard emoji reaction FAILED: "
                f"error_code={result.get('error_code')} description={result.get('description')}"
            )
            return False
    except Exception as e:
        print("[DIAGNOSTIC] Standard emoji reaction request failed:", e)
        return False


def react_with_premium_emoji(message_id, emoji_ids):
    """Reacts to the given message with one random premium (custom) emoji
    from the provided list of custom_emoji_id values."""
    if not emoji_ids:
        print("No premium emoji IDs available, skipping reaction.")
        return

    # Try a few different random IDs in case some are invalid/expired,
    # instead of giving up after the very first failure.
    attempts = emoji_ids[:]
    random.shuffle(attempts)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMessageReaction"

    for emoji_id in attempts[:5]:  # try up to 5 candidates
        payload = {
            "chat_id": TELEGRAM_CHANNEL_ID,
            "message_id": message_id,
            "reaction": json.dumps(
                [{"type": "custom_emoji", "custom_emoji_id": emoji_id}]
            ),
            "is_big": False,
        }

        try:
            resp = requests.post(url, data=payload, timeout=15)
            result = resp.json()  # parse body BEFORE raising, so we can see the real reason
            if result.get("ok"):
                print(f"Reacted with premium emoji {emoji_id}.")
                return
            else:
                print(
                    f"Telegram rejected emoji {emoji_id}: "
                    f"error_code={result.get('error_code')} "
                    f"description={result.get('description')}"
                )
        except Exception as e:
            print(f"Request failed for emoji {emoji_id}:", e)

    print("All reaction attempts failed. See per-attempt errors above.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    posted = load_posted()
    news = get_latest_news(posted)

    if not news:
        print("No new news found this run.")
        return

    caption = rewrite_text(news["title"], news["summary"])

    emoji_ids = load_emoji_ids()
    final_caption = build_caption_with_premium_emoji(caption, emoji_ids)

    best_image_url = get_high_res_image(news["link"]) or news["image_url"]
    image_path = build_image(best_image_url, news["title"])
    result = send_photo(image_path, final_caption, parse_mode="HTML")

    print("Posted successfully:", result.get("ok"), "-", news["title"])

    posted.add(news["id"])
    save_posted(posted)


if __name__ == "__main__":
    main()
