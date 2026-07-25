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
    best_image_url = get_high_res_image(news["link"]) or news["image_url"]
    image_path = build_image(best_image_url, news["title"])
    result = send_photo(image_path, caption)

    print("Posted successfully:", result.get("ok"), "-", news["title"])

    posted.add(news["id"])
    save_posted(posted)


if name == "main":
    main()
