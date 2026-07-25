"""
One-time helper: fetch every custom emoji ID from a list of Telegram
emoji packs, using the bot's own getStickerSet API call.

Run manually via the "Fetch Emoji IDs" GitHub Action.
Prints results to the Actions log - copy them from there.
"""

import os
import requests

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

PACK_NAMES = [
    "PROFIT_MAFIA_II",
    "Decoration_Pack2",
    "FlagsByKoylli",
    "MovingIcons",
    "emoji_fan40_by_TgEmodziBot",
    "Advokat_Emoji",
    "Football_wc",
    "InlineuzFlags",
    "Proxy_PJ2",
    "IslomjonAnimeEmoji",
    "emojiuzbek",
    "NewsEmoji",
    "PaymentMethodsEmoji",
    "TgAndroidIcons",
    "vector_icons_by_fStikBot",
    "FlagsEmoji2024",
]


def main():
    for pack_name in PACK_NAMES:
        print(f"\n{'=' * 60}")
        print(f"PACK: {pack_name}")
        print("=" * 60)
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getStickerSet",
                params={"name": pack_name},
                timeout=20,
            )
            data = resp.json()
            if not data.get("ok"):
                print(f"  Could not fetch this pack: {data.get('description')}")
                continue

            stickers = data["result"].get("stickers", [])
            if not stickers:
                print("  (no emoji found in this pack)")
                continue

            for sticker in stickers:
                emoji_char = sticker.get("emoji", "?")
                custom_emoji_id = sticker.get("custom_emoji_id", "?")
                print(f"  {emoji_char}  ->  {custom_emoji_id}")

        except Exception as e:
            print(f"  Error fetching pack: {e}")


if __name__ == "__main__":
    main()
