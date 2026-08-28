import os
import json
import re
import urllib.parse
from typing import List, Dict, Set, Optional

from playwright.sync_api import sync_playwright


# =========================================================
# FACEBOOK SCRAPER
# =========================================================
#
# Public function used by main.py:
#
#     extract_fb_media(url)
#
# Returns:
#
# Video:
# [
#     {
#         "url": "...",
#         "type": "mp4",
#         "quality": "HD"
#     }
# ]
#
# Photos:
# [
#     {
#         "url": "...",
#         "type": "jpg"
#     }
# ]
#
# =========================================================


# =========================================================
# CONSTANTS
# =========================================================

FACEBOOK_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

MAX_VIEWER_STEPS = 300
NO_NEW_LIMIT = 15

PHOTO_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".avif"
)


# =========================================================
# URL CLEANING
# =========================================================

def clean_fb_cdn_url(raw_url: str) -> str:

    if not raw_url:
        return ""

    clean = str(raw_url).strip()

    # Decode escaped unicode when possible
    try:
        clean = clean.encode("utf-8").decode(
            "unicode-escape"
        )
    except Exception:
        pass

    # Facebook JSON escaping
    clean = clean.replace(r"\/", "/")
    clean = clean.replace("\\/", "/")
    clean = clean.replace(r"\u0026", "&")
    clean = clean.replace(r"\u003D", "=")
    clean = clean.replace(r"\u003d", "=")
    clean = clean.replace("&amp;", "&")

    # URL decoding
    try:
        clean = urllib.parse.unquote(clean)
    except Exception:
        pass

    clean = clean.strip(
        "\"'<> ,\\"
    )

    return clean


# =========================================================
# FACEBOOK PHOTO VALIDATION
# =========================================================

def is_valid_post_photo(url: str) -> bool:

    if not url:
        return False

    url = clean_fb_cdn_url(url)

    if not url.startswith("http"):
        return False

    lower = url.lower()

    # Must normally be Facebook CDN
    if (
        "fbcdn.net" not in lower
        and "scontent" not in lower
    ):
        return False

    # -----------------------------------------------------
    # Things we don't want
    # -----------------------------------------------------

    blocked = [

        # Profile/avatar sizes
        "p32x32",
        "p50x50",
        "p60x60",
        "p100x100",
        "p120x120",
        "p150x150",
        "p180x180",
        "p200x200",

        "s40x40",
        "s50x50",
        "s60x60",
        "s100x100",
        "s150x150",
        "s200x200",

        # Facebook UI
        "emoji.php",
        "safe_image.php",
        "rsrc.php",

        # Common unwanted assets
        "/static/",
        "/static",
        "sprite",
        "avatar",
        "profile",

        # Ads / sponsored assets
        "ads",
        "sponsor",
        "banner",

        # Facebook tracking / special assets
        "t39.1997-6",
        "t39.1998-6",
    ]

    if any(
        item in lower
        for item in blocked
    ):
        return False

    # -----------------------------------------------------
    # Thumbnail dimensions
    # -----------------------------------------------------

    thumbnail_patterns = [

        r"/p\d+x\d+/",

        r"/s\d+x\d+/",

        r"[?&]width=\d{1,3}(?:&|$)",

        r"[?&]height=\d{1,3}(?:&|$)",

    ]

    for pattern in thumbnail_patterns:

        if re.search(
            pattern,
            lower
        ):
            return False

    return True


# =========================================================
# PHOTO ID
# =========================================================

def get_photo_uid(url: str) -> str:

    if not url:
        return ""

    clean = clean_fb_cdn_url(url)

    patterns = [

        # Example:
        # 123456789_123456789_123456789_n.jpg
        r"/([0-9]{8,25})_[0-9]{8,25}_[no]\.",

        # Example:
        # 123456789_123456789_123456789
        r"/([0-9]{8,25})_[0-9]+_[0-9]+",

        # fbid
        r"[?&]fbid=([0-9]{8,30})",

        # photo id in URL
        r"/photo/([0-9]{8,30})",

        # Generic long numeric ID
        r"([0-9]{10,30})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            clean,
            re.IGNORECASE
        )

        if match:

            return match.group(1)

    # Final fallback
    parsed = urllib.parse.urlparse(clean)

    filename = os.path.basename(
        parsed.path
    )

    if filename:
        return filename.lower()

    return clean.split("?")[0]


# =========================================================
# PHOTO QUALITY SCORE
# =========================================================

def photo_quality_score(url: str) -> int:

    if not url:
        return 0

    lower = url.lower()

    score = 0

    # Larger Facebook image variants generally have
    # these markers.
    if "original" in lower:
        score += 100

    if "p2048" in lower:
        score += 90

    if "p1536" in lower:
        score += 80

    if "p1280" in lower:
        score += 70

    if "p960" in lower:
        score += 60

    if "p720" in lower:
        score += 50

    if "p600" in lower:
        score += 40

    # URL dimensions
    dimension_matches = re.findall(
        r"(\d{3,5})x(\d{3,5})",
        lower
    )

    for width, height in dimension_matches:

        try:

            score += min(
                int(width),
                5000
            ) // 10

            score += min(
                int(height),
                5000
            ) // 10

        except Exception:
            pass

    # Avoid tiny resources
    if "p320x320" in lower:
        score -= 50

    if "p360x360" in lower:
        score -= 50

    return score


# =========================================================
# COOKIE LOADING
# =========================================================

def load_cookies_to_context(context) -> bool:

    base_dir = os.path.dirname(
        os.path.abspath(__file__)
    )

    cookie_files = [

        os.path.join(
            base_dir,
            "facebook_cookies.json"
        ),

        os.path.join(
            base_dir,
            "cookies.json"
        ),

        "facebook_cookies.json",

        "cookies.json",
    ]

    for file_path in cookie_files:

        if not os.path.exists(file_path):
            continue

        try:

            with open(
                file_path,
                "r",
                encoding="utf-8"
            ) as f:

                cookies = json.load(f)

            # Some browser-export tools wrap
            # cookies inside another object.
            if isinstance(cookies, dict):

                if "cookies" in cookies:

                    cookies = cookies["cookies"]

                else:

                    cookies = []

            if not isinstance(
                cookies,
                list
            ):
                continue

            formatted = []

            for c in cookies:

                if not isinstance(
                    c,
                    dict
                ):
                    continue

                name = c.get("name")
                value = c.get("value")

                if not name or value is None:
                    continue

                cookie = {
                    "name": str(name),
                    "value": str(value),

                    "domain": c.get(
                        "domain",
                        ".facebook.com"
                    ),

                    "path": c.get(
                        "path",
                        "/"
                    ),
                }

                # Playwright expects expires
                if c.get("expirationDate"):

                    try:

                        cookie["expires"] = float(
                            c["expirationDate"]
                        )

                    except Exception:
                        pass

                elif c.get("expires"):

                    try:

                        cookie["expires"] = float(
                            c["expires"]
                        )

                    except Exception:
                        pass

                if "httpOnly" in c:

                    cookie["httpOnly"] = bool(
                        c["httpOnly"]
                    )

                if "secure" in c:

                    cookie["secure"] = bool(
                        c["secure"]
                    )

                # SameSite values accepted by Playwright
                same_site = c.get(
                    "sameSite"
                )

                if same_site in (
                    "Strict",
                    "Lax",
                    "None"
                ):

                    cookie["sameSite"] = same_site

                formatted.append(
                    cookie
                )

            if formatted:

                context.add_cookies(
                    formatted
                )

                print(
                    f"[Facebook] Loaded "
                    f"{len(formatted)} cookies "
                    f"from {file_path}"
                )

                return True

        except Exception as e:

            print(
                f"[Facebook] Cookie loading "
                f"error: {e}"
            )

    print(
        "[Facebook] No cookie file loaded."
    )

    return False


# =========================================================
# ADD / UPDATE PHOTO
# =========================================================

def add_photo(
    collected: List[Dict],
    photo_map: Dict[str, Dict],
    raw_url: str
) -> bool:

    clean_url = clean_fb_cdn_url(
        raw_url
    )

    if not is_valid_post_photo(
        clean_url
    ):
        return False

    uid = get_photo_uid(
        clean_url
    )

    if not uid:
        uid = clean_url.split("?")[0]

    existing = photo_map.get(uid)

    if existing:

        # If we find a better URL for the same photo,
        # replace the old thumbnail URL.
        old_score = photo_quality_score(
            existing["url"]
        )

        new_score = photo_quality_score(
            clean_url
        )

        if new_score > old_score:

            existing["url"] = clean_url

            return True

        return False

    item = {
        "url": clean_url,
        "type": "jpg"
    }

    photo_map[uid] = item
    collected.append(item)

    print(
        f"[Facebook] Photo #{len(collected)} found"
    )

    return True


# =========================================================
# EXTRACT URLS FROM TEXT / HTML
# =========================================================

def extract_urls_from_text(
    text: str
) -> List[str]:

    if not text:
        return []

    found = []

    patterns = [

        # Normal Facebook CDN URL
        r'https://[^"\'<>\s\\]+(?:fbcdn\.net|scontent)[^"\'<>\s\\]*',

        # Escaped URL
        r'https:\\?/\\?/[^"\'<>\s]+(?:fbcdn\.net|scontent)[^"\'<>\s]*',

        # JSON uri
        r'"uri"\s*:\s*"(https:[^"]+)"',

        # JSON src
        r'"src"\s*:\s*"(https:[^"]+)"',

        # image uri
        r'"image"\s*:\s*\{[^{}]*?"uri"\s*:\s*"(https:[^"]+)"',

        # photo_image
        r'"photo_image"\s*:\s*\{[^{}]*?"uri"\s*:\s*"(https:[^"]+)"',

        # image source
        r'"image_src"\s*:\s*"(https:[^"]+)"',

        # thumbnail / image source
        r'"thumbnail"\s*:\s*"(https:[^"]+)"',
    ]

    for pattern in patterns:

        try:

            matches = re.findall(
                pattern,
                text,
                re.IGNORECASE
            )

        except Exception:

            matches = []

        for match in matches:

            if isinstance(
                match,
                tuple
            ):

                for value in match:

                    if value:
                        found.append(
                            value
                        )

            elif match:

                found.append(
                    match
                )

    # -----------------------------------------------------
    # Clean + unique
    # -----------------------------------------------------

    result = []

    seen = set()

    for raw in found:

        clean = clean_fb_cdn_url(
            raw
        )

        if not clean:
            continue

        key = clean.split("?")[0]

        if key in seen:
            continue

        seen.add(key)

        result.append(clean)

    return result


# =========================================================
# COLLECT HTML PHOTOS
# =========================================================

def collect_html_photos(
    page,
    collected,
    photo_map
) -> int:

    count_before = len(
        collected
    )

    try:

        html = page.content()

    except Exception:

        return 0

    urls = extract_urls_from_text(
        html
    )

    # Sort larger URLs first where possible
    urls.sort(
        key=photo_quality_score,
        reverse=True
    )

    for url in urls:

        add_photo(
            collected,
            photo_map,
            url
        )

    return (
        len(collected)
        - count_before
    )


# =========================================================
# COLLECT DOM IMAGES
# =========================================================

def collect_dom_images(
    page,
    collected,
    photo_map
) -> int:

    count_before = len(
        collected
    )

    selectors = [

        "img",

        "source",

        '[role="img"]',

        'img[data-visualcompletion="media-vc-image"]',

        'div[role="dialog"] img',

        'div[role="dialog"] source',

        'div[data-visualcompletion="media-vc-image"] img',

        'div[data-visualcompletion="media-vc-image"] source',
    ]

    for selector in selectors:

        try:

            elements = page.eval_on_selector_all(
                selector,
                """
                els => els.map(e => ({
                    src: e.currentSrc || e.src || "",
                    srcset: e.srcset || "",
                    dataSrc: e.getAttribute("data-src") || "",
                    dataOriginal: e.getAttribute("data-original") || "",
                    dataLazy: e.getAttribute("data-lazy-src") || ""
                }))
                """
            )

        except Exception:

            continue

        for element in elements:

            candidates = []

            for key in [
                "src",
                "dataSrc",
                "dataOriginal",
                "dataLazy"
            ]:

                value = element.get(
                    key,
                    ""
                )

                if value:
                    candidates.append(
                        value
                    )

            # -------------------------------------------------
            # srcset
            # -------------------------------------------------

            srcset = element.get(
                "srcset",
                ""
            )

            if srcset:

                for part in srcset.split(","):

                    part = part.strip()

                    if not part:
                        continue

                    candidate = part.split(
                        " "
                    )[0].strip()

                    if candidate:

                        candidates.append(
                            candidate
                        )

            # -------------------------------------------------
            # Add
            # -------------------------------------------------

            for candidate in candidates:

                add_photo(
                    collected,
                    photo_map,
                    candidate
                )

    return (
        len(collected)
        - count_before
    )


# =========================================================
# COLLECT PHOTO LINKS
# =========================================================

def collect_photo_links(
    page
) -> List[str]:

    links = []

    try:

        data = page.eval_on_selector_all(
            "a[href]",
            """
            els => els.map(e => ({
                href: e.href || "",
                text: e.innerText || "",
                aria: e.getAttribute("aria-label") || ""
            }))
            """
        )

    except Exception as e:

        print(
            "[Facebook] Photo link "
            f"error: {e}"
        )

        return links

    for item in data:

        href = item.get(
            "href",
            ""
        )

        if not href:
            continue

        low = href.lower()

        if (
            "/photo/" in low
            or "/photos/" in low
            or "photo.php" in low
            or "fbid=" in low
        ):

            if href not in links:

                links.append(
                    href
                )

    return links


# =========================================================
# FIND PHOTO VIEWER
# =========================================================

def find_visible_photo_link(
    page
):

    selectors = [

        'a[href*="/photo/"]',

        'a[href*="/photos/"]',

        'a[href*="photo.php"]',

        'a[href*="fbid="]',
    ]

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            total = locator.count()

            for i in range(
                min(total, 20)
            ):

                try:

                    item = locator.nth(i)

                    if item.is_visible():

                        return item

                except Exception:

                    continue

        except Exception:

            continue

    return None


# =========================================================
# OPEN PHOTO VIEWER
# =========================================================

def open_photo_viewer(
    page
) -> bool:

    print(
        "[Facebook] Looking for "
        "photo viewer..."
    )

    photo_link = find_visible_photo_link(
        page
    )

    if photo_link is None:

        print(
            "[Facebook] No photo link "
            "found."
        )

        return False

    try:

        photo_link.click(
            force=True,
            timeout=5000
        )

        page.wait_for_timeout(
            2500
        )

        print(
            "[Facebook] Photo viewer "
            "opened."
        )

        return True

    except Exception as e:

        print(
            "[Facebook] Normal photo "
            f"click failed: {e}"
        )

    # -----------------------------------------------------
    # JavaScript click fallback
    # -----------------------------------------------------

    try:

        handle = photo_link.element_handle()

        if handle:

            page.evaluate(
                "(el) => el.click()",
                handle
            )

            page.wait_for_timeout(
                2500
            )

            print(
                "[Facebook] Photo viewer "
                "opened using JS."
            )

            return True

    except Exception as e:

        print(
            "[Facebook] JS photo click "
            f"failed: {e}"
        )

    return False


# =========================================================
# NEXT PHOTO BUTTON
# =========================================================

def click_next_photo(
    page
) -> bool:

    selectors = [

        # Modern Facebook
        'div[aria-label="Next photo"]',

        'button[aria-label="Next photo"]',

        '[aria-label="Next photo"]',

        '[aria-label="Next"]',

        '[data-testid="next-button"]',

        # Generic
        'button[aria-label*="Next"]',

        'div[role="button"][aria-label*="Next"]',
    ]

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            total = locator.count()

            for i in range(
                total - 1,
                -1,
                -1
            ):

                try:

                    button = locator.nth(i)

                    if not button.is_visible():
                        continue

                    disabled = button.get_attribute(
                        "disabled"
                    )

                    aria_disabled = button.get_attribute(
                        "aria-disabled"
                    )

                    if disabled is not None:
                        continue

                    if aria_disabled == "true":
                        continue

                    button.click(
                        force=True,
                        timeout=2000
                    )

                    return True

                except Exception:

                    continue

        except Exception:

            continue

    # -----------------------------------------------------
    # Keyboard fallback
    # -----------------------------------------------------

    try:

        page.keyboard.press(
            "ArrowRight"
        )

        return True

    except Exception:

        pass

    return False


# =========================================================
# VIEWER IMAGE SIGNATURE
# =========================================================

def get_viewer_signature(
    page
) -> str:

    selectors = [
        'div[role="dialog"] img',
        'div[role="dialog"] source',
        'img[data-visualcompletion="media-vc-image"]',
    ]

    values = []

    for selector in selectors:

        try:

            urls = page.eval_on_selector_all(
                selector,
                """
                els => els.map(e =>
                    e.currentSrc ||
                    e.src ||
                    e.getAttribute("src") ||
                    ""
                )
                """
            )

            values.extend(
                urls
            )

        except Exception:

            continue

    cleaned = []

    for value in values:

        if not value:
            continue

        clean = clean_fb_cdn_url(
            value
        )

        if is_valid_post_photo(
            clean
        ):

            cleaned.append(
                clean.split("?")[0]
            )

    if not cleaned:
        return ""

    cleaned = sorted(
        set(cleaned)
    )

    return "|".join(
        cleaned
    )


# =========================================================
# LIGHTBOX / VIEWER EXTRACTION
# =========================================================

def extract_lightbox_photos(
    page,
    collected,
    photo_map
):

    print(
        "[Facebook] Starting "
        "extended photo viewer extraction..."
    )

    opened = open_photo_viewer(
        page
    )

    if not opened:
        return

    no_new_rounds = 0
    previous_signature = ""

    for step in range(
        MAX_VIEWER_STEPS
    ):

        before = len(
            collected
        )

        # -------------------------------------------------
        # Current DOM
        # -------------------------------------------------

        collect_dom_images(
            page,
            collected,
            photo_map
        )

        # -------------------------------------------------
        # Current HTML
        # -------------------------------------------------

        collect_html_photos(
            page,
            collected,
            photo_map
        )

        after = len(
            collected
        )

        signature = get_viewer_signature(
            page
        )

        # -------------------------------------------------
        # Detect progress
        # -------------------------------------------------

        if after > before:

            no_new_rounds = 0

            print(
                f"[Facebook] Viewer step "
                f"{step + 1}: "
                f"{after} photos"
            )

        elif (
            signature
            and signature != previous_signature
        ):

            # Viewer changed even though
            # current DOM didn't reveal
            # a new URL yet.
            no_new_rounds = 0

        else:

            no_new_rounds += 1

        previous_signature = signature

        # -------------------------------------------------
        # Don't quit immediately.
        #
        # Facebook often needs several
        # rounds before lazy images appear.
        # -------------------------------------------------

        if no_new_rounds >= NO_NEW_LIMIT:

            print(
                "[Facebook] Viewer appears "
                "to have reached the end."
            )

            break

        # -------------------------------------------------
        # Next photo
        # -------------------------------------------------

        moved = click_next_photo(
            page
        )

        if not moved:

            print(
                "[Facebook] Could not "
                "move to next photo."
            )

            break

        page.wait_for_timeout(
            850
        )

        # -------------------------------------------------
        # Small scroll helps lazy loading
        # -------------------------------------------------

        try:

            page.mouse.wheel(
                0,
                450
            )

        except Exception:

            pass

    print(
        "[Facebook] Viewer extraction "
        f"finished with {len(collected)} photos."
    )


# =========================================================
# VIDEO EXTRACTION
# =========================================================

def extract_video_urls(
    content: str
) -> List[Dict]:

    results = []

    seen = set()

    patterns = [

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

        # Some Facebook responses use videoURL
        (
            r'"videoURL"\s*:\s*"(https:[^"]+?)"',
            "SD"
        ),

        (
            r'"video_url"\s*:\s*"(https:[^"]+?)"',
            "SD"
        ),
    ]

    for pattern, quality in patterns:

        try:

            matches = re.findall(
                pattern,
                content,
                re.IGNORECASE
            )

        except Exception:

            matches = []

        for raw in matches:

            url = clean_fb_cdn_url(
                raw
            )

            if not url:
                continue

            if url in seen:
                continue

            seen.add(url)

            results.append({
                "url": url,
                "type": "mp4",
                "quality": quality
            })

    # -----------------------------------------------------
    # Prefer HD
    # -----------------------------------------------------

    results.sort(
        key=lambda x:
            0
            if x.get("quality") == "HD"
            else 1
    )

    return results


# =========================================================
# MAIN EXTRACTOR
# =========================================================

def extract_fb_media(
    target_url: str
):

    collected = []

    # uid -> item
    photo_map = {}

    # URLs of returned media
    seen_media_urls: Set[str] = set()

    api_key = os.getenv(
        "BROWSERLESS_API_KEY",
        ""
    ).strip()

    browser = None

    with sync_playwright() as p:

        try:

            # =================================================
            # BROWSERLESS
            # =================================================

            if api_key:

                ws_endpoint = (
                    "wss://production-sfo.browserless.io"
                    f"?token={api_key}"
                )

                try:

                    print(
                        "[Facebook] Connecting "
                        "to Browserless..."
                    )

                    browser = (
                        p.chromium.connect_over_cdp(
                            ws_endpoint
                        )
                    )

                    print(
                        "[Facebook] Browserless "
                        "connected."
                    )

                except Exception as e:

                    print(
                        "[Facebook] Browserless "
                        f"connection failed: {e}"
                    )

                    browser = None

            # =================================================
            # LOCAL CHROMIUM FALLBACK
            # =================================================

            if browser is None:

                print(
                    "[Facebook] Starting "
                    "local Chromium..."
                )

                browser = p.chromium.launch(

                    headless=True,

                    args=[

                        "--no-sandbox",

                        "--disable-setuid-sandbox",

                        "--disable-dev-shm-usage",

                        "--disable-blink-features="
                        "AutomationControlled",

                        "--disable-gpu",

                        "--disable-notifications",

                        "--disable-popup-blocking",
                    ]
                )

            # =================================================
            # CONTEXT
            # =================================================

            context = browser.new_context(

                user_agent=FACEBOOK_USER_AGENT,

                viewport={
                    "width": 1366,
                    "height": 768
                },

                locale="en-US",

                timezone_id="Asia/Karachi",

                color_scheme="light",

            )

            # =================================================
            # COOKIES
            # =================================================

            load_cookies_to_context(
                context
            )

            # =================================================
            # PAGE
            # =================================================

            page = context.new_page()

            try:

                page.set_extra_http_headers({
                    "Accept-Language":
                        "en-US,en;q=0.9"
                })

            except Exception:
                pass

            # =================================================
            # URL NORMALIZATION
            # =================================================

            desktop_url = (
                target_url
                .strip()
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
                "======================================"
            )

            print(
                "[Facebook] Target:",
                desktop_url
            )

            print(
                "======================================"
            )

            # =================================================
            # NAVIGATE
            # =================================================

            try:

                page.goto(
                    desktop_url,
                    wait_until="domcontentloaded",
                    timeout=45000
                )

            except Exception as e:

                print(
                    "[Facebook] Navigation "
                    f"warning: {e}"
                )

            # Give Facebook JS enough time
            page.wait_for_timeout(
                5000
            )

            # =================================================
            # FIRST HTML
            # =================================================

            try:

                content = page.content()

            except Exception:

                content = ""

            # =================================================
            # VIDEO FIRST
            # =================================================

            video_results = extract_video_urls(
                content
            )

            if video_results:

                print(
                    "[Facebook] Video found:",
                    len(video_results)
                )

                return video_results

            # =================================================
            # FIRST PHOTO SCAN
            # =================================================

            collect_html_photos(
                page,
                collected,
                photo_map
            )

            collect_dom_images(
                page,
                collected,
                photo_map
            )

            # =================================================
            # PHOTO LINKS
            # =================================================

            photo_links = collect_photo_links(
                page
            )

            print(
                "[Facebook] Photo links:",
                len(photo_links)
            )

            # =================================================
            # OPEN VIEWER
            # =================================================

            if photo_links:

                extract_lightbox_photos(
                    page,
                    collected,
                    photo_map
                )

            else:

                # Even when photo links aren't
                # obvious, Facebook may already
                # have the image in the page.
                if not collected:

                    extract_lightbox_photos(
                        page,
                        collected,
                        photo_map
                    )

            # =================================================
            # FINAL PAGE SCAN
            # =================================================

            collect_html_photos(
                page,
                collected,
                photo_map
            )

            collect_dom_images(
                page,
                collected,
                photo_map
            )

            # =================================================
            # FINAL DEDUPLICATION
            # =================================================

            final_items = []

            final_seen = set()

            for item in collected:

                url = item.get(
                    "url",
                    ""
                )

                if not url:
                    continue

                key = url.split("?")[0]

                if key in final_seen:
                    continue

                final_seen.add(
                    key
                )

                final_items.append(
                    item
                )

            # =================================================
            # Sort photos by discovery order.
            # Do NOT sort alphabetically because Facebook
            # carousel order is meaningful.
            # =================================================

            print(
                "======================================"
            )

            print(
                "[Facebook] FINAL PHOTOS:",
                len(final_items)
            )

            print(
                "======================================"
            )

            return final_items

        except Exception as e:

            print(
                "[Facebook] Fatal scraper error:",
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
