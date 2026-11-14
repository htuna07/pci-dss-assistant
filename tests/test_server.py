"""Web server: started as a subprocess with a fake `claude` command, so no real model call is made."""

import json
import os
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from conftest import PROJECT_ROOT

SERVER_SCRIPT = PROJECT_ROOT / "src" / "server.py"

FAKE_CLAUDE = f"""#!{sys.executable}
import json, sys

prompt = sys.stdin.read()
if prompt.startswith("Question: "):
    result = json.dumps({{"queries": ["multi-factor authentication for remote access"]}})
elif "BREAK" in prompt:
    print(json.dumps({{"is_error": True, "result": "Not logged in"}}))
    sys.exit(1)
else:
    result = "MFA is required [8.4.2]. Logs are kept 12 months [10.5.1]."
print(json.dumps({{"result": result}}))
"""


def chunk(requirement_id, text):
    return {
        "chunk_id": f"{requirement_id}/requirement/1",
        "record_type": "requirement",
        "requirement_id": requirement_id,
        "header": f"header {requirement_id}",
        "text": text,
    }


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(port, path, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    directory = tmp_path_factory.mktemp("server")
    chunks_path = directory / "chunks.jsonl"
    rows = [
        chunk("8.4.2", "MFA is implemented for all non-console access into the CDE."),
        chunk("8.4.3", "MFA is implemented for all remote access."),
        chunk("10.5.1", "Retain audit log history for at least 12 months."),
        chunk("3.2.1", "Account data storage is kept to a minimum."),
    ]
    chunks_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    bin_dir = directory / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text(FAKE_CLAUDE, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)

    index_dir = directory / "index"
    port = free_port()
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    process = subprocess.Popen(
        [
            sys.executable, str(SERVER_SCRIPT),
            "--port", str(port), "--chunks", str(chunks_path), "--index-dir", str(index_dir),
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=PROJECT_ROOT,
    )
    deadline = time.time() + 180
    while True:
        if process.poll() is not None:
            pytest.fail(f"server exited early: {process.stderr.read()}")
        try:
            if request(port, "/")[0] == 200:
                break
        except (urllib.error.URLError, ConnectionError):
            pass
        if time.time() > deadline:
            process.kill()
            pytest.fail("server did not start in time")
        time.sleep(0.5)

    yield {"port": port, "index": index_dir}
    process.terminate()
    process.wait(timeout=10)


def test_page_is_served(server):
    status, body = request(server["port"], "/")

    assert status == 200
    assert "<title>PCI DSS Assistant</title>" in body


def test_question_gets_a_cited_answer_with_its_sources(server):
    status, body = request(
        server["port"], "/api/ask", {"question": "What must remote users use to log in?"}
    )
    data = json.loads(body)

    assert status == 200
    assert data["answer"].startswith("MFA is required [8.4.2]")
    assert data["check"]["cited"] == ["8.4.2", "10.5.1"]
    assert data["check"]["not_found"] is False
    assert data["queries"] == ["multi-factor authentication for remote access"]
    assert {source["id"] for source in data["sources"]} == set(data["retrieved"])
    assert all(source["text"] for source in data["sources"])


@pytest.mark.parametrize(
    "body",
    [{"question": ""}, {"question": "   "}, {"question": "x" * 1001}, {}, {"question": 5}],
)
def test_invalid_questions_are_rejected(server, body):
    status, _ = request(server["port"], "/api/ask", body)

    assert status == 422


def test_generation_failure_is_a_bad_gateway_with_a_message(server):
    status, body = request(server["port"], "/api/ask", {"question": "BREAK please"})

    assert status == 502
    detail = json.loads(body)["detail"]
    assert "Generation failed" in detail
    # The CLI reports its reason on stdout as JSON; the user needs to see it, not an empty stderr.
    assert "Not logged in" in detail


def test_questions_are_not_stored_on_disk(server):
    request(server["port"], "/api/ask", {"question": "My card 4111111111111111 leaked"})

    stored = [path for path in server["index"].rglob("*") if path.is_file() and path.suffix == ".json"]
    for path in stored:
        assert "4111111111111111" not in path.read_text(encoding="utf-8")
    assert not (server["index"] / "rewrites.json").exists()
