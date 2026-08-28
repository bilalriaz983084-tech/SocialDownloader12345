import os
import re
import json
import urllib.parse
from typing import List, Dict, Set

from playwright.sync_api import sync_playwright


# =========================================================
# FACEBOOK SCRAPER
# =========================================================

FACEBOOK_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

MAX_VIEWER_STEPS = 300
NO_NEW_LIMIT = 15


# =========================================================
# CLEAN FACEBOOK URL
# =========================================================

def clean_fb_cdn_url(raw_url: str) -> str:

    if not raw_url:
        return ""

    clean = str(raw_url).strip()

    try:
        clean = clean.encode(
            "utf-8"
        ).decode(
            "unicode-escape"
        )
    except Exception:
        pass

    clean = clean.replace(
        r"\/",
        "/"
    )

    clean = clean.replace(
        "\\/",
        "/"
    )

    clean = clean.replace(
        r"\u0026",
        "&"
    )

    clean = clean.replace(
        r"\u003D",
        "="
    )

    clean = clean.replace(
        r"\u003d",
        "="
    )

    clean = clean.replace(
        "&amp;",
        "&"
    )

    try:
        clean = urllib.parse.unquote(
            clean
        )
    except Exception:
        pass

    return clean.strip(
        "\"'<> ,\\"
    )


# =========================================================
# VALID PHOTO CHECK
# =========================================================

def is_valid_post_photo(
    url: str
) -> bool:

    if not url:
        return False

    url = clean_fb_cdn_url(
        url
    )

    if not url.startswith(
        "https://"
    ):
        return False

    lower = url.lower()

    if (
        "fbcdn.net" not in lower
        and "scontent" not in lower
    ):
        return False

    blocked = [

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

        "emoji.php",
        "safe_image.php",
        "rsrc.php",

        "/static/",
        "/static",
        "sprite",
        "avatar",
        "profile",

        "ads",
        "sponsor",
        "banner",

        "t39.1997-6",
        "t39.1998-6",
    ]

    if any(
        item in lower
        for item in blocked
    ):
        return False

    # Small Facebook thumbnail variants
    thumbnail_patterns = [

        r"/p\d+x\d+/",

        r"/s\d+x\d+/",

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

def get_photo_uid(
    url: str
) -> str:

    clean = clean_fb_cdn_url(
        url
    )

    patterns = [

        r"/([0-9]{8,25})_[0-9]{8,25}_[no]\.",

        r"/([0-9]{8,25})_[0-9]+_[0-9]+",

        r"[?&]fbid=([0-9]{8,30})",

        r"/photo/([0-9]{8,30})",

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

    parsed = urllib.parse.urlparse(
        clean
    )

    filename = os.path.basename(
        parsed.path
    )

    if filename:
        return filename.lower()

    return clean.split("?")[0]


# =========================================================
# PHOTO QUALITY SCORE
# =========================================================

def photo_quality_score(
    url: str
) -> int:

    if not url:
        return 0

    lower = url.lower()

    score = 0

    quality_markers = {
        "original": 100,
        "p2048": 90,
        "p1536": 80,
        "p1280": 70,
        "p960": 60,
        "p720": 50,
        "p600": 40,
    }

    for marker, value in quality_markers.items():

        if marker in lower:
            score += value

    dimensions = re.findall(
        r"(\d{3,5})x(\d{3,5})",
        lower
    )

    for width, height in dimensions:

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

    return score


# =========================================================
# LOAD FACEBOOK COOKIES
# =========================================================

def load_cookies_to_context(
    context
) -> bool:

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

        if not os.path.exists(
            file_path
        ):
            continue

        try:

            with open(
                file_path,
                "r",
                encoding="utf-8"
            ) as f:

                cookies = json.load(f)

            if isinstance(
                cookies,
                dict
            ):

                cookies = cookies.get(
                    "cookies",
                    []
                )

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

                name = c.get(
                    "name"
                )

                value = c.get(
                    "value"
                )

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

                expires = (
                    c.get("expirationDate")
                    or c.get("expires")
                )

                if expires:

                    try:
                        cookie["expires"] = float(
                            expires
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
                    "[Facebook] Cookies loaded:",
                    len(formatted)
                )

                return True

        except Exception as e:

            print(
                "[Facebook] Cookie error:",
                repr(e)
            )

    print(
        "[Facebook] No cookies loaded."
    )

    return False


# =========================================================
# ADD PHOTO
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

    existing = photo_map.get(
        uid
    )

    if existing:

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

    collected.append(
        item
    )

    print(
        f"[Facebook] PHOTO #{len(collected)}"
    )

    return True


# =========================================================
# EXTRACT FACEBOOK CDN URLS FROM TEXT
# =========================================================

def extract_urls_from_text(
    text: str
) -> List[str]:

    if not text:
        return []

    found = []

    patterns = [

        # Normal CDN
        r'https://[^"\'<>\s\\]+(?:fbcdn\.net|scontent)[^"\'<>\s\\]*',

        # Escaped CDN
        r'https:\\?/\\?/[^"\'<>\s]+(?:fbcdn\.net|scontent)[^"\'<>\s]*',

        # JSON URI
        r'"uri"\s*:\s*"(https:[^"]+)"',

        # JSON SRC
        r'"src"\s*:\s*"(https:[^"]+)"',

        # image.uri
        r'"image"\s*:\s*\{[^{}]*?"uri"\s*:\s*"(https:[^"]+)"',

        # photo_image.uri
        r'"photo_image"\s*:\s*\{[^{}]*?"uri"\s*:\s*"(https:[^"]+)"',

        # image source
        r'"image_src"\s*:\s*"(https:[^"]+)"',

        # thumbnail
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

        seen.add(
            key
        )

        result.append(
            clean
        )

    return result


# =========================================================
# HTML PHOTO SCAN
# =========================================================

def collect_html_photos(
    page,
    collected,
    photo_map
) -> int:

    before = len(
        collected
    )

    try:

        html = page.content()

    except Exception:

        return 0

    urls = extract_urls_from_text(
        html
    )

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

    return len(
        collected
    ) - before


# =========================================================
# DOM PHOTO SCAN
# =========================================================

def collect_dom_images(
    page,
    collected,
    photo_map
) -> int:

    before = len(
        collected
    )

    selectors = [

        "img",

        "source",

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
                    original: e.getAttribute("data-original") || "",
                    lazy: e.getAttribute("data-lazy-src") || ""
                }))
                """
            )

        except Exception:

            continue

        for element in elements:

            candidates = [

                element.get(
                    "src",
                    ""
                ),

                element.get(
                    "dataSrc",
                    ""
                ),

                element.get(
                    "original",
                    ""
                ),

                element.get(
                    "lazy",
                    ""
                ),
            ]

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
                    )[0]

                    if candidate:
                        candidates.append(
                            candidate
                        )

            for candidate in candidates:

                if candidate:

                    add_photo(
                        collected,
                        photo_map,
                        candidate
                    )

    return len(
        collected
    ) - before


# =========================================================
# FIND PHOTO LINKS
# =========================================================

def collect_photo_links(
    page
) -> List[str]:

    result = []

    try:

        links = page.eval_on_selector_all(
            "a[href]",
            """
            els => els.map(e => ({
                href: e.href || "",
                aria: e.getAttribute("aria-label") || ""
            }))
            """
        )

    except Exception:

        return result

    for item in links:

        href = item.get(
            "href",
            ""
        )

        if not href:
            continue

        lower = href.lower()

        if (
            "/photo/" in lower
            or "/photos/" in lower
            or "photo.php" in lower
            or "fbid=" in lower
        ):

            if href not in result:

                result.append(
                    href
                )

    return result


# =========================================================
# FIND VISIBLE PHOTO LINK
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

            for index in range(
                min(total, 30)
            ):

                try:

                    element = locator.nth(
                        index
                    )

                    if element.is_visible():

                        return element

                except Exception:

                    continue

        except Exception:

            continue

    return None


# =========================================================
# OPEN FACEBOOK PHOTO VIEWER
# =========================================================

def open_photo_viewer(
    page
) -> bool:

    print(
        "[Facebook] Opening photo viewer..."
    )

    photo_link = find_visible_photo_link(
        page
    )

    if photo_link is None:

        print(
            "[Facebook] Photo link not found."
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

        return True

    except Exception as e:

        print(
            "[Facebook] Click failed:",
            repr(e)
        )

    # JS fallback
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

            return True

    except Exception as e:

        print(
            "[Facebook] JS click failed:",
            repr(e)
        )

    return False


# =========================================================
# NEXT PHOTO
# =========================================================

def click_next_photo(
    page
) -> bool:

    selectors = [

        'div[aria-label="Next photo"]',

        'button[aria-label="Next photo"]',

        '[aria-label="Next photo"]',

        '[aria-label="Next"]',

        '[data-testid="next-button"]',

        'button[aria-label*="Next"]',

        'div[role="button"][aria-label*="Next"]',
    ]

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            total = locator.count()

            for index in range(
                total - 1,
                -1,
                -1
            ):

                try:

                    button = locator.nth(
                        index
                    )

                    if not button.is_visible():
                        continue

                    if (
                        button.get_attribute(
                            "disabled"
                        )
                        is not None
                    ):
                        continue

                    if (
                        button.get_attribute(
                            "aria-disabled"
                        )
                        == "true"
                    ):
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

    # Keyboard fallback
    try:

        page.keyboard.press(
            "ArrowRight"
        )

        return True

    except Exception:

        return False


# =========================================================
# VIEWER SIGNATURE
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

    clean_values = []

    for value in values:

        clean = clean_fb_cdn_url(
            value
        )

        if is_valid_post_photo(
            clean
        ):

            clean_values.append(
                clean.split("?")[0]
            )

    return "|".join(
        sorted(
            set(clean_values)
        )
    )


# =========================================================
# EXTENDED LIGHTBOX EXTRACTION
# =========================================================

def extract_lightbox_photos(
    page,
    collected,
    photo_map
):

    print(
        "[Facebook] Extended "
        "photo extraction started."
    )

    if not open_photo_viewer(
        page
    ):

        return

    no_new = 0
    last_signature = ""

    for step in range(
        MAX_VIEWER_STEPS
    ):

        before = len(
            collected
        )

        # Current visible images
        collect_dom_images(
            page,
            collected,
            photo_map
        )

        # Current HTML / React payload
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

        # New photo discovered
        if after > before:

            no_new = 0

            print(
                f"[Facebook] Viewer "
                f"{step + 1}: "
                f"{after} photos"
            )

        elif (
            signature
            and signature != last_signature
        ):

            no_new = 0

        else:

            no_new += 1

        last_signature = signature

        # Give lazy images time
        page.wait_for_timeout(
            450
        )

        # Try next
        moved = click_next_photo(
            page
        )

        if not moved:

            print(
                "[Facebook] Next photo "
                "button unavailable."
            )

            break

        page.wait_for_timeout(
            850
        )

        # Help lazy loading
        try:

            page.mouse.wheel(
                0,
                500
            )

        except Exception:

            pass

        # Facebook reached end
        if no_new >= NO_NEW_LIMIT:

            print(
                "[Facebook] No new photos "
                "for several rounds."
            )

            break

    print(
        "[Facebook] Extended extraction "
        f"finished: {len(collected)} photos"
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

            seen.add(
                url
            )

            results.append({

                "url": url,

                "type": "mp4",

                "quality": quality
            })

    # HD first
    results.sort(
        key=lambda x:
        0
        if x.get("quality") == "HD"
        else 1
    )

    return results


# =========================================================
# MAIN PUBLIC FUNCTION
# =========================================================

def extract_fb_media(
    target_url: str
):

    collected = []

    photo_map = {}

    browser = None

    # -----------------------------------------------------
    # Browserless API key
    # -----------------------------------------------------

    api_key = os.getenv(
        "BROWSERLESS_API_KEY",
        ""
    ).strip()

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
                        "Browserless..."
                    )

                    browser = (
                        p.chromium.connect_over_cdp(
                            ws_endpoint
                        )
                    )

                    print(
                        "[Facebook] Browserless connected."
                    )

                except Exception as e:

                    print(
                        "[Facebook] Browserless failed:",
                        repr(e)
                    )

                    browser = None

            # =================================================
            # LOCAL PLAYWRIGHT
            # =================================================

            if browser is None:

                print(
                    "[Facebook] Starting local Chromium..."
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
            # NORMALIZE URL
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
                "[Facebook] URL:",
                desktop_url
            )

            print(
                "======================================"
            )

            # =================================================
            # LOAD PAGE
            # =================================================

            try:

                page.goto(
                    desktop_url,
                    wait_until="domcontentloaded",
                    timeout=45000
                )

            except Exception as e:

                print(
                    "[Facebook] Navigation warning:",
                    repr(e)
                )

            # Allow Facebook JS
            page.wait_for_timeout(
                5000
            )

            # =================================================
            # GET HTML
            # =================================================

            try:

                content = page.content()

            except Exception:

                content = ""

            # =================================================
            # VIDEO CHECK FIRST
            # =================================================

            video_results = extract_video_urls(
                content
            )

            if video_results:

                print(
                    "[Facebook] VIDEO FOUND:",
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
                "[Facebook] PHOTO LINKS:",
                len(photo_links)
            )

            # =================================================
            # VIEWER
            # =================================================

            if photo_links:

                extract_lightbox_photos(
                    page,
                    collected,
                    photo_map
                )

            elif not collected:

                extract_lightbox_photos(
                    page,
                    collected,
                    photo_map
                )

            # =================================================
            # FINAL SCAN
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
            # FINAL DEDUP
            # =================================================

            final = []

            seen = set()

            for item in collected:

                url = item.get(
                    "url",
                    ""
                )

                if not url:
                    continue

                key = url.split("?")[0]

                if key in seen:
                    continue

                seen.add(
                    key
                )

                final.append(
                    item
                )

            print(
                "======================================"
            )

            print(
                "[Facebook] FINAL PHOTO COUNT:",
                len(final)
            )

            print(
                "======================================"
            )

            return final

        except Exception as e:

            print(
                "[Facebook] Scraper error:",
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
