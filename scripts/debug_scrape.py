"""Debug script: see what Google Maps actually shows in the browser"""

import asyncio
from playwright.async_api import async_playwright


async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ],
    )
    context = await browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="id-ID",
        timezone_id="Asia/Jakarta",
    )
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    """)

    page = await context.new_page()

    origin = "-6.225,106.77"
    dest = "-6.222,106.78"
    url = f"https://www.google.com/maps/dir/{origin}/{dest}"

    print(f"Navigating to: {url}")
    try:
        await page.goto(url, wait_until="commit", timeout=20000)
    except Exception as e:
        print(f"Navigation error (partial load): {e}")

    # Wait a bit for whatever loads
    await asyncio.sleep(5)

    # Take screenshot immediately
    await page.screenshot(path="data/debug_screenshot.png", full_page=False)
    print("Screenshot 1 saved to data/debug_screenshot.png")

    # Get page title and url
    title = await page.title()
    print(f"Page title: {title}")
    print(f"Current URL: {page.url}")

    # Check for consent/cookie dialogs
    consent_buttons = await page.query_selector_all('button')
    print(f"\nFound {len(consent_buttons)} buttons:")
    for btn in consent_buttons[:15]:
        try:
            text = (await btn.inner_text()).strip()
            if text:
                print(f"  Button: '{text[:80]}'")
        except:
            pass

    # Try clicking consent/accept buttons
    clicked = False
    for btn in consent_buttons:
        try:
            text = (await btn.inner_text()).strip().lower()
            if any(w in text for w in ['accept', 'terima', 'setuju', 'accept all', 'agree']):
                print(f"\n>>> CLICKING CONSENT BUTTON: '{text}'")
                await btn.click()
                clicked = True
                await asyncio.sleep(3)
                break
        except:
            pass

    if clicked:
        await page.screenshot(path="data/debug_screenshot_after_consent.png", full_page=False)
        print("Screenshot 2 (after consent) saved")

    # Wait more for route data  
    await asyncio.sleep(5)
    await page.screenshot(path="data/debug_screenshot_final.png", full_page=False)
    print("Final screenshot saved")

    # Look for duration/distance text
    print("\n--- Searching for duration/distance text ---")
    all_text = await page.evaluate("""
        () => {
            const results = [];
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT, null, false
            );
            let node;
            while (node = walker.nextNode()) {
                const text = node.textContent.trim();
                if (text && (
                    text.match(/\\d+\\s*(min|mnt|jam|hr|menit)/i) ||
                    text.match(/\\d+[.,]?\\d*\\s*km/i)
                )) {
                    results.push(text.substring(0, 150));
                }
            }
            return results;
        }
    """)
    for t in all_text[:20]:
        print(f"  Found: '{t}'")

    if not all_text:
        print("  NO duration/distance text found on page")

    # Get page HTML length
    html = await page.content()
    print(f"\nPage HTML length: {len(html)} chars")
    # Save it
    with open("data/debug_page.html", "w") as f:
        f.write(html)

    await browser.close()
    await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
