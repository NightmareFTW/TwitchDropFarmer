import json
from pathlib import Path

from PySide6.QtCore import QEventLoop, QUrl
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
from PySide6.QtWidgets import QApplication
from shiboken6 import delete as shiboken_delete

COOKIE_PATH = Path.home() / ".twitch-drop-farmer" / "cookies.json"

INTERCEPT_JS = r"""
(() => {
  if (window.__tdf_probe_installed) return;
  window.__tdf_probe_installed = true;
  window.__tdf_probe = { requests: [] };

  function capture(label, data) {
    try {
      const entry = { label, at: new Date().toISOString() };
      if (typeof data === 'string') entry.text = data.slice(0, 2000);
      else if (data && typeof data === 'object') entry.text = JSON.stringify(data).slice(0, 2000);
      window.__tdf_probe.requests.push(entry);
    } catch (e) {}
  }

  const origFetch = window.fetch.bind(window);
  window.fetch = function(input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.includes('/gql') || url.includes('gql')) {
      try {
        const body = init && init.body ? String(init.body) : '';
        capture('fetch-request', { url, body: body.slice(0, 2000) });
      } catch (e) {}
    }
    return origFetch(input, init).then(async (resp) => {
      try {
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        if (url.includes('/gql') || url.includes('gql')) {
          const cloned = resp.clone();
          const text = await cloned.text();
          capture('fetch-response', { url, status: resp.status, body: text.slice(0, 2000) });
        }
      } catch (e) {}
      return resp;
    });
  };

  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url) {
    this.__tdf_probe_url = String(url || '');
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function(body) {
    if (this.__tdf_probe_url && /\/gql|gql/i.test(this.__tdf_probe_url)) {
      capture('xhr-request', { url: this.__tdf_probe_url, body: String(body || '').slice(0, 2000) });
      const self = this;
      const origOnLoad = this.onload;
      this.onload = function(evt) {
        try {
          capture('xhr-response', { url: self.__tdf_probe_url, status: self.status, body: String(self.responseText || '').slice(0, 2000) });
        } catch (e) {}
        if (origOnLoad) origOnLoad.call(this, evt);
      };
    }
    return origSend.call(this, body);
  };
})();
"""


def main() -> None:
    payload = json.loads(COOKIE_PATH.read_text(encoding="utf-8"))
    app = QApplication([])
    profile = QWebEngineProfile(app)
    page = QWebEnginePage(profile, app)
    cookie_store = profile.cookieStore()

    for cookie in payload.get("cookies", []):
        name = str(cookie.get("name", "")).strip()
        value = str(cookie.get("value", ""))
        domain = str(cookie.get("domain") or ".twitch.tv")
        if not name or not value:
            continue
        q = QNetworkCookie()
        q.setName(name.encode("utf-8"))
        q.setValue(value.encode("utf-8"))
        q.setDomain(domain)
        q.setPath("/")
        q.setSecure(True)
        cookie_store.setCookie(q, QUrl("https://www.twitch.tv/"))

    script = QWebEngineScript()
    script.setName("tdf_probe_gql")
    script.setSourceCode(INTERCEPT_JS)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    profile.scripts().insert(script)

    loop = QEventLoop()
    finished = {"done": False}

    def on_loaded(ok: bool) -> None:
        print("LOAD_OK", ok)
        print("URL", page.url().toString())
        page.runJavaScript(
            """
            (() => {
              const reqs = (window.__tdf_probe && Array.isArray(window.__tdf_probe.requests)) ? window.__tdf_probe.requests : [];
              return JSON.stringify(reqs.slice(-12));
            })();
            """,
            lambda result: (print(result if isinstance(result, str) else str(result)), loop.quit()),
        )

    page.loadFinished.connect(on_loaded)
    page.load(QUrl("https://www.twitch.tv/drops/campaigns"))
    loop.exec()

    shiboken_delete(page)
    shiboken_delete(profile)
    app.quit()


if __name__ == "__main__":
    main()
