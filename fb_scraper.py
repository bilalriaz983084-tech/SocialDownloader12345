import os
import json
import re
import urllib.parse
from playwright.sync_api import sync_playwright


# =========================================================
# FACEBOOK URL CLEANER
# =========================================================

def clean_fb_cdn_url(raw_url: str) -> str:
    if not raw_url:
        return ""

    clean = str(raw_url).strip()

    try:
        clean = clean.encode("utf-8").decode("unicode-escape")
    except Exception:
        pass

    clean = clean.replace(r"\/", "/")
    clean = clean.replace("\\/", "/")
    clean = clean.replace(r"\u0026", "&")
    clean = clean.replace("&amp;", "&")

    try:
        clean = urllib.parse.unquote(clean)
    except Exception:
        pass

    return clean.strip("\"'<> ,\\")


# =========================================================
# CHECK FACEBOOK PHOTO
# =========================================================

def is_valid_post_photo(url: str) -> bool:
    if not url:
        return False

    lower = url.lower()

    if not url.startswith("https://"):
        return False

    if "fbcdn.net" not in lower and "scontent" not in lower:
        return False

    blocked = [
        "p50x50",
        "p100x100",
        "p60x60",
        "s40x40",
        "s50x50",
        "s100x100",
        "s150x150",
        "s200x200",
        "p32x32",
        "p180x180",

        "profile",
        "avatar",
        "emoji",
        "emoji.php",
        "safe_image.php",
        "rsrc.php",

        "static",
        "sprite",

        "ads",
        "sponsor",
        "banner",
        "external",

        "t39.1997-6",
        "t39.1998-6",
    ]

    if any(x in lower for x in blocked):
        return False

    # Facebook thumbnails
    thumbnail_patterns = [
        r"/p\d+x\d+/",
        r"/s\d+x\d+/",
        r"_s\.",
        r"_n\.",
    ]

    for pattern in thumbnail_patterns:
        if re.search(pattern, lower):
            return False

    return True


# =========================================================
# PHOTO UID
# =========================================================

def get_photo_uid(url: str) -> str:
    if not url:
        return ""

    clean = clean_fb_cdn_url(url)

    patterns = [
        r"/([0-9]{8,25})_[0-9]+_[0-9]+",
        r"/([0-9]{8,25})_[0-9]{8,25}_[no]\.",
        r"fbid=([0-9]{8,25})",
        r"photo\.php\?[^#]*fbid=([0-9]{8,25})",
    ]

    for pattern in patterns:
        match = re.search(pattern, clean, re.IGNORECASE)
        if match:
            return match.group(1)

    parsed = urllib.parse.urlparse(clean)

    filename = os.path.basename(parsed.path)

    if filename:
        return filename

    return clean.split("?")[0]


# =========================================================
# COOKIE LOADER
# =========================================================

def load_cookies_to_context(context):

    base_dir = os.path.dirname(os.path.abspath(__file__))

    cookie_files = [
        os.path.join(base_dir, "facebook_cookies.json"),
        os.path.join(base_dir, "cookies.json"),
        "facebook_cookies.json",
        "cookies.json",
    ]

    for file_path in cookie_files:

        if not os.path.exists(file_path):
            continue

        try:

            with open(file_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)

            formatted_cookies = []

            for c in cookies:

                name = c.get("name")
                value = c.get("value")

                if not name or value is None:
                    continue

                cookie_dict = {
                    "name": name,
                    "value": value,
                    "domain": c.get("domain", ".facebook.com"),
                    "path": c.get("path", "/"),
                }

                if "expirationDate" in c:
                    try:
                        cookie_dict["expires"] = float(c["expirationDate"])
                    except Exception:
                        pass

                elif "expires" in c:
                    try:
                        cookie_dict["expires"] = float(c["expires"])
                    except Exception:
                        pass

                if "httpOnly" in c:
                    cookie_dict["httpOnly"] = bool(c["httpOnly"])

                if "secure" in c:
                    cookie_dict["secure"] = bool(c["secure"])

                formatted_cookies.append(cookie_dict)

            if formatted_cookies:
                context.add_cookies(formatted_cookies)

                print(
                    f"Successfully loaded cookies from {file_path} "
                    f"({len(formatted_cookies)} cookies)"
                )

                return True

        except Exception as e:
            print(f"Cookie loading error {file_path}: {e}")

    print("No Facebook cookie file found.")
    return False


# =========================================================
# ADD PHOTO
# =========================================================

def add_photo(collected, seen_ids, raw_url):

    clean_img = clean_fb_cdn_url(raw_url)

    if not is_valid_post_photo(clean_img):
        return False

    uid = get_photo_uid(clean_img)

    if not uid:
        uid = clean_img.split("?")[0]

    if uid in seen_ids:
        return False

    seen_ids.add(uid)

    collected.append({
        "url": clean_img,
        "type": "jpg"
    })

    print(f"Facebook photo found #{len(collected)}")

    return True


# =========================================================
# EXTRACT PHOTO URLS FROM HTML
# =========================================================

def extract_photo_urls_from_text(text):

    results = []

    if not text:
        return results

    # -----------------------------------------------------
    # Direct https scontent URLs
    # -----------------------------------------------------

    patterns = [

        r'https:\\?/\\?/[^"\'\\ ]*scontent[^"\'\\ ]*fbcdn\.net[^"\'\\ ]+',

        r'"(https://[^"]*scontent[^"]*fbcdn\.net[^"]+)"',

        r"'(https://[^']*scontent[^']*fbcdn\.net[^']+)'",

        r'"uri"\s*:\s*"(https:[^"]+?fbcdn\.net[^"]+)"',

        r'"image"\s*:\s*\{[^}]*?"uri"\s*:\s*"(https:[^"]+?fbcdn\.net[^"]+)"',

        r'"src"\s*:\s*"(https:[^"]+?scontent[^"]+?fbcdn\.net[^"]+)"',
    ]

    for pattern in patterns:

        try:
            matches = re.findall(
                pattern,
                text,
                flags=re.IGNORECASE
            )
        except Exception:
            matches = []

        for match in matches:

            if isinstance(match, tuple):
                match = match[0]

            clean = clean_fb_cdn_url(match)

            if clean and clean not in results:
                results.append(clean)

    return results


# =========================================================
# FACEBOOK PHOTO LINK EXTRACTOR
# =========================================================

def collect_photo_links(page):

    urls = []

    try:

        links = page.eval_on_selector_all(
            'a[href]',
            """
            els => els.map(e => ({
                href: e.href || "",
                text: e.innerText || ""
            }))
            """
        )

        for item in links:

            href = item.get("href", "")

            if not href:
                continue

            low = href.lower()

            if (
                "/photo/" in low
                or "photo.php" in low
                or "/photos/" in low
            ):
                if href not in urls:
                    urls.append(href)

    except Exception as e:
        print("Photo link collection error:", e)

    return urls


# =========================================================
# COLLECT CURRENT DOM IMAGES
# =========================================================

def collect_dom_images(page, collected, seen_ids):

    count = 0

    selectors = [
        "img",
        'img[data-visualcompletion="media-vc-image"]',
        'div[role="dialog"] img',
        'div[data-visualcompletion="media-vc-image"] img',
    ]

    for selector in selectors:

        try:

            images = page.eval_on_selector_all(
                selector,
                """
                els => els.map(e => ({
                    src: e.currentSrc || e.src || "",
                    srcset: e.srcset || "",
                    dataSrc: e.getAttribute("data-src") || ""
                }))
                """
            )

        except Exception:
            continue

        for image in images:

            candidates = []

            src = image.get("src", "")
            srcset = image.get("srcset", "")
            data_src = image.get("dataSrc", "")

            if src:
                candidates.append(src)

            if data_src:
                candidates.append(data_src)

            if srcset:

                for part in srcset.split(","):

                    part = part.strip()

                    if part:
                        candidate = part.split(" ")[0]

                        if candidate:
                            candidates.append(candidate)

            for candidate in candidates:

                if add_photo(
                    collected,
                    seen_ids,
                    candidate
                ):
                    count += 1

    return count


# =========================================================
# COLLECT HTML PHOTOS
# =========================================================

def collect_html_photos(page, collected, seen_ids):

    count = 0

    try:
        html = page.content()
    except Exception:
        return 0

    urls = extract_photo_urls_from_text(html)

    for url in urls:

        if add_photo(
            collected,
            seen_ids,
            url
        ):
            count += 1

    return count


# =========================================================
# LIGHTBOX PHOTO EXTRACTION
# =========================================================

def extract_lightbox_photos(
    page,
    collected,
    seen_ids
):

    print("Opening Facebook photo viewer...")

    # -----------------------------------------------------
    # Find first photo
    # -----------------------------------------------------

    selectors = [
        'a[href*="/photo/"]',
        'a[href*="photo.php"]',
        'a[href*="/photos/"]',
    ]

    clicked = False

    for selector in selectors:

        try:

            locator = page.locator(selector)

            if locator.count() > 0:

                for index in range(
                    min(locator.count(), 10)
                ):

                    try:

                        element = locator.nth(index)

                        if element.is_visible():

                            element.click(
                                force=True,
                                timeout=5000
                            )

                            clicked = True
                            break

                    except Exception:
                        continue

            if clicked:
                break

        except Exception:
            continue

    if not clicked:
        print("Facebook photo viewer could not be opened.")
        return

    page.wait_for_timeout(2500)

    # -----------------------------------------------------
    # Keep extracting until Facebook stops giving new
    # photos.
    # -----------------------------------------------------

    no_new_rounds = 0
    max_rounds = 500

    for round_no in range(max_rounds):

        before = len(collected)

        # DOM images
        collect_dom_images(
            page,
            collected,
            seen_ids
        )

        # HTML source
        collect_html_photos(
            page,
            collected,
            seen_ids
        )

        after = len(collected)

        if after > before:

            no_new_rounds = 0

            print(
                f"Facebook viewer round {round_no + 1}: "
                f"{after} photos total"
            )

        else:

            no_new_rounds += 1

        # -------------------------------------------------
        # Try multiple navigation methods
        # -------------------------------------------------

        moved = False

        # ArrowRight
        try:

            page.keyboard.press("ArrowRight")

            moved = True

        except Exception:
            pass

        # Facebook next buttons
        next_selectors = [
            'div[aria-label="Next photo"]',
            'button[aria-label="Next photo"]',
            '[aria-label="Next"]',
            '[data-visualcompletion="ignore-dynamic"]',
        ]

        for selector in next_selectors:

            try:

                btn = page.locator(selector)

                if btn.count() > 0:

                    visible_btn = btn.last

                    if visible_btn.is_visible():

                        visible_btn.click(
                            force=True,
                            timeout=1500
                        )

                        moved = True
                        break

            except Exception:
                continue

        page.wait_for_timeout(700)

        # -------------------------------------------------
        # Facebook may need scrolling inside viewer
        # -------------------------------------------------

        try:

            page.mouse.wheel(0, 500)

        except Exception:
            pass

        # -------------------------------------------------
        # Don't stop too quickly.
        # -------------------------------------------------

        if no_new_rounds >= 12:
            break

    print(
        f"Facebook lightbox extraction complete: "
        f"{len(collected)} photos"
    )


# =========================================================
# MAIN FACEBOOK EXTRACTOR
# =========================================================

def extract_fb_media(target_url: str):

    collected = []
    seen_urls = set()
    seen_ids = set()

    # -----------------------------------------------------
    # Browserless
    # -----------------------------------------------------

    api_key = os.getenv(
        "BROWSERLESS_API_KEY",
        ""
    )

    ws_endpoint = ""

    if api_key:

        ws_endpoint = (
            "wss://production-sfo.browserless.io"
            f"?token={api_key}"
        )

    with sync_playwright() as p:

        browser = None

        try:

            # -------------------------------------------------
            # Browserless first
            # -------------------------------------------------

            if ws_endpoint:

                try:

                    browser = p.chromium.connect_over_cdp(
                        ws_endpoint
                    )

                    print(
                        "Connected to Browserless."
                    )

                except Exception as e:

                    print(
                        "Browserless connection failed:",
                        e
                    )

                    browser = None

            # -------------------------------------------------
            # Local Chromium fallback
            # -------------------------------------------------

            if browser is None:

                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ]
                )

                print(
                    "Using local Chromium."
                )

            # -------------------------------------------------
            # Context
            # -------------------------------------------------

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                viewport={
                    "width": 1366,
                    "height": 768
                },
                locale="en-US",
                timezone_id="Asia/Karachi",
            )

            # Cookies
            load_cookies_to_context(context)

            page = context.new_page()

            # -------------------------------------------------
            # Request headers
            # -------------------------------------------------

            try:

                page.set_extra_http_headers({
                    "Accept-Language":
                        "en-US,en;q=0.9",
                    "Upgrade-Insecure-Requests":
                        "1",
                })

            except Exception:
                pass

            # -------------------------------------------------
            # Normalize URL
            # -------------------------------------------------

            desktop_url = (
                target_url
                .replace(
                    "mbasic.facebook.com",
                    "www.facebook.com"
                )
                .replace(
                    "m.facebook.com",
                    "www.facebook.com"
                )
            )

            print(
                "Opening Facebook:",
                desktop_url
            )

            # -------------------------------------------------
            # Open page
            # -------------------------------------------------

            try:

                page.goto(
                    desktop_url,
                    wait_until="domcontentloaded",
                    timeout=45000
                )

            except Exception as e:

                print(
                    "Facebook page goto warning:",
                    e
                )

            page.wait_for_timeout(5000)

            # -------------------------------------------------
            # First collect HTML
            # -------------------------------------------------

            collect_html_photos(
                page,
                collected,
                seen_ids
            )

            # -------------------------------------------------
            # Collect visible DOM photos
            # -------------------------------------------------

            collect_dom_images(
                page,
                collected,
                seen_ids
            )

            # =================================================
            # VIDEO EXTRACTION
            # =================================================

            content = page.content()

            video_patterns = [

                (
                    r'\\"playable_url_quality_hd\\":\s*\\"(https:[^"]+?)\\"',
                    "HD"
                ),

                (
                    r'\\"browser_native_hd_url\\":\s*\\"(https:[^"]+?)\\"',
                    "HD"
                ),

                (
                    r'\\"playable_url\\":\s*\\"(https:[^"]+?)\\"',
                    "SD"
                ),

                (
                    r'\\"browser_native_sd_url\\":\s*\\"(https:[^"]+?)\\"',
                    "SD"
                ),

                (
                    r'"playable_url_quality_hd"\s*:\s*"(https:[^"]+?)"',
                    "HD"
                ),

                (
                    r'"browser_native_hd_url"\s*:\s*"(https:[^"]+?)"',
                    "HD"
                ),

                (
                    r'"playable_url"\s*:\s*"(https:[^"]+?)"',
                    "SD"
                ),

                (
                    r'"browser_native_sd_url"\s*:\s*"(https:[^"]+?)"',
                    "SD"
                ),
            ]

            video_found = []

            for pattern, quality in video_patterns:

                try:

                    matches = re.findall(
                        pattern,
                        content,
                        re.IGNORECASE
                    )

                except Exception:
                    matches = []

                for raw_vid in matches:

                    clean_vid = clean_fb_cdn_url(
                        raw_vid
                    )

                    if (
                        clean_vid
                        and clean_vid not in seen_urls
                    ):

                        seen_urls.add(clean_vid)

                        video_found.append({
                            "url": clean_vid,
                            "type": "mp4",
                            "quality": quality
                        })

            # -------------------------------------------------
            # If video found, return video only
            # -------------------------------------------------

            if video_found:

                print(
                    f"Facebook video found: "
                    f"{len(video_found)}"
                )

                return video_found

            # =================================================
            # PHOTO LINKS
            # =================================================

            photo_links = collect_photo_links(page)

            print(
                f"Facebook photo links found: "
                f"{len(photo_links)}"
            )

            # =================================================
            # LIGHTBOX
            # =================================================

            if photo_links or not collected:

                extract_lightbox_photos(
                    page,
                    collected,
                    seen_ids
                )

            # =================================================
            # FINAL HTML SCAN
            # =================================================

            collect_html_photos(
                page,
                collected,
                seen_ids
            )

            collect_dom_images(
                page,
                collected,
                seen_ids
            )

            # -------------------------------------------------
            # Remove duplicate URLs
            # -------------------------------------------------

            final = []

            final_seen = set()

            for item in collected:

                url = item.get("url", "")

                if not url:
                    continue

                key = url.split("?")[0]

                if key in final_seen:
                    continue

                final_seen.add(key)

                final.append(item)

            collected = final

            print(
                "===================================="
            )

            print(
                f"Facebook FINAL media count: "
                f"{len(collected)}"
            )

            print(
                "===================================="
            )

            return collected

        except Exception as e:

            print(
                "Facebook scraper error:",
                repr(e)
            )

            return collected

        finally:

            if browser:

                try:
                    browser.close()
                except Exception:
                    pass


# =========================================================
# COMPATIBILITY ALIAS
# =========================================================

extract_all_fb_photos_sync = extract_fb_media
