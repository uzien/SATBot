import asyncio
import json
import logging
from config import PORT, get_next_test, get_next_score_release
from database import get_subscriber_stats

logger = logging.getLogger(__name__)


def generate_html_status(stats: dict, next_test: dict | None, next_scores: dict | None) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>SAT Notify Telegram Bot</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem; max-width: 600px; margin: 0 auto; }}
        .card {{ background: #1e293b; border-radius: 12px; padding: 1.5rem; margin-top: 1rem; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }}
        .status {{ color: #4ade80; font-weight: bold; }}
        h1 {{ color: #38bdf8; font-size: 1.8rem; margin-bottom: 0.5rem; }}
        .stat-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-top: 1rem; }}
        .stat-box {{ background: #334155; padding: 1rem; border-radius: 8px; text-align: center; }}
        .stat-val {{ font-size: 1.5rem; font-weight: bold; color: #38bdf8; }}
    </style>
</head>
<body>
    <h1>🎓 SAT Notify Bot</h1>
    <p>Status: <span class="status">● Bot Running</span></p>
    
    <div class="card">
        <h3>📊 Subscriber Stats</h3>
        <div class="stat-grid">
            <div class="stat-box">
                <div class="stat-val">{stats.get('active', 0)}</div>
                <div>Active Subscribers</div>
            </div>
            <div class="stat-box">
                <div class="stat-val">{stats.get('total', 0)}</div>
                <div>Total Users</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h3>📅 Next SAT Exam</h3>
        <p><strong>{next_test['name'] if next_test else 'None'}</strong>: {next_test['test_date'] if next_test else 'N/A'}</p>
        <h3 style="margin-top: 1rem;">📢 Next Score Release</h3>
        <p><strong>{next_scores['name'] if next_scores else 'None'}</strong>: {next_scores['score_release_date'] if next_scores else 'N/A'}</p>
    </div>
</body>
</html>"""


# Global reference to Telegram Application for webhook dispatching
_TELEGRAM_APP = None


def set_telegram_app(app):
    global _TELEGRAM_APP
    _TELEGRAM_APP = app


# Built-in lightweight async HTTP server (Zero external dependencies needed)
async def handle_http_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        request_line = await reader.readline()
        if not request_line:
            return

        parts = request_line.decode("utf-8", errors="ignore").strip().split(" ")
        if len(parts) < 2:
            return

        method, path = parts[0].upper(), parts[1]

        # Read remaining headers
        headers = {}
        content_length = 0
        while True:
            line = await reader.readline()
            if not line or line == b"\r\n":
                break
            header_str = line.decode("utf-8", errors="ignore").strip()
            if ":" in header_str:
                k, v = header_str.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        if "content-length" in headers:
            try:
                content_length = int(headers["content-length"])
            except ValueError:
                content_length = 0

        body = b""
        if content_length > 0:
            body = await reader.readexactly(content_length)

        stats = await get_subscriber_stats()
        next_test = get_next_test()
        next_scores = get_next_score_release()

        # Handle Webhook Updates from Telegram
        if method == "POST" and path.startswith("/webhook"):
            if _TELEGRAM_APP and body:
                try:
                    payload_str = body.decode("utf-8", errors="ignore")
                    logger.info("Telegram Webhook Update: %s", payload_str)
                    from telegram import Update
                    data = json.loads(payload_str)
                    if isinstance(data, dict) and "update_id" in data:
                        update = Update.de_json(data, _TELEGRAM_APP.bot)
                        asyncio.create_task(_TELEGRAM_APP.process_update(update))
                    else:
                        logger.debug("Received empty or non-update payload: %s", payload_str)
                except Exception as e:
                    logger.error("Error processing webhook update: %s", e)

            response = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK"
        elif path.startswith("/health"):
            data = json.dumps({
                "status": "healthy",
                "service": "sat-telegram-notify-bot",
                "subscribers": stats
            }).encode("utf-8")
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(data)).encode("ascii") + b"\r\n"
                b"Connection: close\r\n\r\n" + data
            )
        else:
            html = generate_html_status(stats, next_test, next_scores).encode("utf-8")
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/html; charset=utf-8\r\n"
                b"Content-Length: " + str(len(html)).encode("ascii") + b"\r\n"
                b"Connection: close\r\n\r\n" + html
            )

        writer.write(response)
        await writer.drain()
    except Exception as e:
        logger.error("Error handling HTTP request: %s", e)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def start_web_server(port: int = PORT):
    """Starts the HTTP health check server."""
    server = await asyncio.start_server(handle_http_connection, "0.0.0.0", port)
    logger.info("Health check & webhook server running on http://0.0.0.0:%d", port)
    return server
