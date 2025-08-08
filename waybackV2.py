from flask import Flask, request, Response
from urllib.parse import urlparse, quote_plus
from bs4 import BeautifulSoup
import requests, json, os, re


app = Flask(__name__)
CACHE_DIR = "page_cache"
CONFIG_FILE = "wayback_config.json"


os.makedirs(CACHE_DIR, exist_ok=True)


def get_target_date():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f).get("date", "2002")
    except:
        return "2002"


def sanitize_path(path):
    path = path.replace("http://", "").replace("https://", "")
    path = re.sub(r"(www\.)+", "www.", path)
    path = re.sub(r"(\.\w+)(\.\w+)+", r"\1", path)
    return path.strip("/")


def get_closest_capture_url(original_url, date):
    api = "http://archive.org/wayback/available"
    params = {"url": original_url, "timestamp": date}
    try:
        r = requests.get(api, params=params, timeout=10).json()
        snapshot = r.get("archived_snapshots", {}).get("closest", {})
        ts = snapshot.get("timestamp")
        if ts:
            return f"https://web.archive.org/web/{ts}id_/{original_url}"
        return None
    except Exception as e:
        print(f"[Wayback ERROR] {e}")
        return None




def cache_path(url):
    return os.path.join(CACHE_DIR, quote_plus(url))


def rewrite_html_links(content, base_url):
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup.find_all(["a", "link", "script", "img", "iframe"]):
        attr = "href" if tag.name in ["a", "link"] else "src"
        if not tag.has_attr(attr):
            continue


        original = tag[attr]


        # CASO 1: Link do tipo Wayback /web/yyyy.../http://site.com/path
        m = re.match(r"^/web/\d+(?:[a-z_]+)?/(https?://[^\"\'\s]+)", original)
        if m:
            rewritten = "/" + m.group(1).replace("https://", "").replace("http://", "")
            tag[attr] = rewritten
            continue


        # CASO 2: Link absoluto normal
        if original.startswith("http://") or original.startswith("https://"):
            rewritten = "/" + original.replace("https://", "").replace("http://", "")
            tag[attr] = rewritten
            continue


        # CASO 3: Caminho relativo
        if original.startswith("/"):
            parsed = urlparse(base_url)
            tag[attr] = "/" + parsed.netloc + original


    # REMOVER SCRIPTS E CSS da Wayback
    for tag in soup.find_all("script"):
        if "playback" in str(tag) or "wombat.js" in str(tag): tag.decompose()
    for tag in soup.find_all("link"):
        if "archive.css" in str(tag) or "iconochive" in str(tag): tag.decompose()
    for tag in soup.find_all("div"):
        if "wm-ipp" in tag.get("id", ""): tag.decompose()


    return str(soup)




@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def proxy(path):
    # Reconstrói a URL original com base na linha completa da requisição
    raw_url = request.environ.get('RAW_URI', request.full_path)


    # Remove sufixos ? e etc
    raw_url = raw_url.split('?')[0]


    # Tenta extrair a URL original real
    if raw_url.startswith("http://") or raw_url.startswith("https://"):
        full_url = raw_url
    else:
        host = request.headers.get('Host', '')
        full_url = f"http://{host}/{path}"


    print(f"[Request] Incoming: {full_url}")


    cache_file = cache_path(full_url)
    if os.path.exists(cache_file):
        print("[Cache] HIT")
        with open(cache_file, "rb") as f:
            return Response(f.read(), content_type="text/html")


    date = get_target_date()
    wayback_url = get_closest_capture_url(full_url, date)
    if not wayback_url:
        return f"<h1>No snapshot found for <code>{full_url}</code> on {date}</h1>", 404


    try:
        r = requests.get(wayback_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        content_type = r.headers.get("Content-Type", "text/html")
        content = r.content


        if "text/html" in content_type:
            content = rewrite_html_links(content.decode("utf-8", errors="ignore"), wayback_url).encode()


        with open(cache_file, "wb") as f:
            f.write(content)


        return Response(content, status=r.status_code, content_type=content_type)
    except Exception as e:
        return f"<h1>Error: {e}</h1>", 502




if __name__ == "__main__":
    import socket
    ip = socket.gethostbyname(socket.gethostname())
    print(f"[Proxy Ready] Wayback Proxy running at http://{ip}:8080")
    app.run(host="0.0.0.0", port=8080)
