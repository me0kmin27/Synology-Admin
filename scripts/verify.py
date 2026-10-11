"""Local/CI verification only: disposable DB and loopback HTTP, never NAS."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ["DJANGO_SECRET_KEY"] = secrets.token_urlsafe(64)
os.environ["DJANGO_ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"
os.environ.pop("DJANGO_LOCAL_HTTP", None)
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
runtime = ROOT / ".runtime"
runtime.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=runtime) as directory:
    os.environ["DJANGO_DB_PATH"] = str(Path(directory) / "verify.sqlite3")
    for args in (("check", "--deploy", "--fail-level", "WARNING"), ("test", "-v", "2"), ("migrate", "--noinput"), ("makemigrations", "--check", "--dry-run")):
        subprocess.run([sys.executable, "manage.py", *args], check=True)
    os.environ["DJANGO_LOCAL_HTTP"] = "1"
    from config.wsgi import application
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM django_migrations")
        migrations = cursor.fetchone()[0]
    from django.db.migrations.executor import MigrationExecutor
    executor = MigrationExecutor(connection)
    assert not executor.migration_plan(executor.loader.graph.leaf_nodes()), "Unapplied migrations"
    executor.loader.check_consistent_history(connection)
    assert set(executor.loader.disk_migrations).issubset(executor.loader.applied_migrations), "Missing migration records"
    with make_server("127.0.0.1", 0, application) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/health/", timeout=5) as response:
                health = json.load(response)
                assert response.status == 200 and health == {"status": "ok", "database": "ok", "nas": "not_configured"}
                assert "no-store" in response.headers["Cache-Control"]
            with urlopen(base + "/", timeout=5) as response:
                assert response.status == 200 and "NAS 연결 안 됨" in response.read().decode()
            try:
                urlopen(Request(base + "/", headers={"Host": "untrusted.invalid"}), timeout=5)
                raise AssertionError("Invalid host accepted")
            except HTTPError as error:
                assert error.code == 400
            print(json.dumps({"http_smoke": {"landing": 200, "health": 200, "invalid_host": 400}, "health_body": health, "applied_migrations": migrations, "deployment": "not_performed", "nas_access": "not_performed"}))
        finally:
            server.shutdown()
            thread.join(timeout=5)
            connection.close()
