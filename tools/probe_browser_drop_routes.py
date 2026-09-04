import json
from pathlib import Path

from PySide6.QtCore import QEventLoop, QUrl
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWidgets import QApplication
from shiboken6 import delete as shiboken_delete


COOKIE_PATH = Path.home() / ".twitch-drop-farmer" / "cookies.json"


def main() -> None:
    data = json.loads(COOKIE_PATH.read_text(encoding="utf-8"))
    app = QApplication([])
    profile = QWebEngineProfile(app)
    page = QWebEnginePage(profile, app)
    cookie_store = profile.cookieStore()

    for cookie in data.get("cookies", []):
        name = str(cookie.get("name", "")).strip()
        value = str(cookie.get("value", ""))
        domain = str(cookie.get("domain") or ".twitch.tv")
        if not name or not value:
            continue
        qt_cookie = QNetworkCookie()
        qt_cookie.setName(name.encode("utf-8"))
        qt_cookie.setValue(value.encode("utf-8"))
        qt_cookie.setDomain(domain)
        qt_cookie.setPath("/")
        qt_cookie.setSecure(True)
        cookie_store.setCookie(qt_cookie, QUrl("https://www.twitch.tv/"))

    loop = QEventLoop()

    def completed(ok: bool) -> None:
        print("LOAD_OK", ok)
        print("URL", page.url().toString())
        print("TITLE", page.title())
        page.runJavaScript(
            """
            (() => {
                const text = (document.body && document.body.innerText) ? document.body.innerText : '';
                const entries = Array.from(window.performance.getEntriesByType('resource') || []).map((r) => r.name || '');
                const relevant = entries.filter((u) => /gql|graphql|drop|campaign|inventory|reward/i.test(u));
                const scripts = Array.from(document.scripts || []).map((s) => s.src || '').filter(Boolean).slice(0, 30);
                return JSON.stringify({
                    textPreview: text.slice(0, 2000),
                    textLength: text.length,
                    resourceCount: entries.length,
                    relevantResources: relevant.slice(0, 50),
                    scripts: scripts.slice(0, 20),
                });
            })();
            """,
            lambda result: (print(result if isinstance(result, str) else str(result)), loop.quit()),
        )

    page.loadFinished.connect(completed)
    page.load(QUrl("https://www.twitch.tv/drops/campaigns"))
    loop.exec()

    delete_page = page
    delete_profile = profile
    shiboken_delete(delete_page)
    shiboken_delete(delete_profile)
    app.quit()


if __name__ == "__main__":
    main()
