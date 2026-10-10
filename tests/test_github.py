from __future__ import annotations

import subprocess
from typing import Any

import pytest

from dejabuilt.github import (
    API_BASE,
    Client,
    GitHubError,
    Response,
    build_url,
    discover_token,
)
from tests.helpers import TOKEN, FakeClock, FakeTransport, Seq, json_response, make_client


def completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class TestDiscoverToken:
    def test_gh_token_wins(self) -> None:
        env = {"GH_TOKEN": "first", "GITHUB_TOKEN": "second"}
        assert discover_token(env, which=lambda _: None) == "first"

    def test_github_token_is_second(self) -> None:
        assert discover_token({"GITHUB_TOKEN": " second "}, which=lambda _: None) == "second"

    def test_blank_variables_are_ignored(self) -> None:
        assert discover_token({"GH_TOKEN": "  "}, which=lambda _: None) is None

    def test_falls_back_to_the_github_cli(self) -> None:
        calls: list[Any] = []

        def run(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
            calls.append((command, options))
            return completed("from-cli\n")

        token = discover_token({}, which=lambda _: r"C:\Program Files\GitHub CLI\gh.exe", run=run)
        assert token == "from-cli"
        command, options = calls[0]
        assert command == [
            r"C:\Program Files\GitHub CLI\gh.exe",
            "auth",
            "token",
            "--hostname",
            "github.com",
        ]
        assert options["shell"] is False
        assert options["timeout"] == 5

    def test_cli_failure_means_no_token(self) -> None:
        run = lambda *a, **k: completed("not logged in", returncode=1)  # noqa: E731
        assert discover_token({}, which=lambda _: "gh", run=run) is None

    @pytest.mark.parametrize(
        "error", [FileNotFoundError(), subprocess.TimeoutExpired("gh", 5), PermissionError()]
    )
    def test_cli_that_cannot_run_means_no_token(self, error: Exception) -> None:
        def run(*args: Any, **options: Any) -> subprocess.CompletedProcess[str]:
            raise error

        assert discover_token({}, which=lambda _: "gh", run=run) is None

    def test_no_cli_installed(self) -> None:
        assert discover_token({}, which=lambda _: None) is None


class TestBuildUrl:
    def test_joins_path_and_encodes_parameters(self) -> None:
        url = build_url("/search/repositories", {"q": "a b&c=d", "per_page": 5})
        assert url == f"{API_BASE}/search/repositories?q=a+b%26c%3Dd&per_page=5"

    @pytest.mark.parametrize(
        "path",
        [
            "repos/a/b",
            "//evil.example/x",
            "/x://evil.example",
            "https://evil.example/x",
            "/repos/a/b?x=1",
            "/repos/a/b#frag",
            "/repos/a b",
            "/repos/a\\b",
            "/repos/a\nb",
        ],
    )
    def test_rejects_paths_that_could_leave_the_host(self, path: str) -> None:
        with pytest.raises(GitHubError) as caught:
            build_url(path)
        assert caught.value.kind == "invalid"


class TestRequests:
    def test_sends_the_token_only_in_the_authorization_header(self) -> None:
        client, transport, _ = make_client({"/user": {"login": "x"}})
        assert client.get_json("/user") == {"login": "x"}
        url, headers = transport.calls[0]
        assert headers["Authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in url
        assert url.startswith(API_BASE + "/")

    def test_unauthenticated_client_sends_no_authorization(self) -> None:
        client, transport, _ = make_client({"/user": {}}, token=None)
        client.get_json("/user")
        assert "Authorization" not in transport.calls[0][1]
        assert client.authenticated is False

    def test_get_text_returns_at_most_max_chars(self) -> None:
        client, _, _ = make_client({"/readme": Response(200, {}, "héllo wörld".encode())})
        assert client.get_text("/readme", 5) == "héllo"

    def test_body_that_is_not_json_is_a_server_error(self) -> None:
        client, _, _ = make_client({"/x": Response(200, {}, b"<html>")})
        with pytest.raises(GitHubError) as caught:
            client.get_json("/x")
        assert caught.value.kind == "server"


class TestErrors:
    @pytest.mark.parametrize(
        ("status", "headers", "body", "kind"),
        [
            (401, {}, {"message": "Bad credentials"}, "auth"),
            (404, {}, {"message": "Not Found"}, "not_found"),
            (422, {}, {"message": "Validation Failed"}, "invalid"),
            (500, {}, {}, "server"),
            (503, {}, {}, "server"),
            (302, {"Location": "https://evil.example/"}, {}, "redirect"),
            (403, {}, {"message": "Resource not accessible"}, "forbidden"),
            (418, {}, {}, "http"),
        ],
    )
    def test_status_maps_to_kind(
        self, status: int, headers: dict[str, str], body: Any, kind: str
    ) -> None:
        client, transport, clock = make_client({"/x": json_response(body, status, headers)})
        with pytest.raises(GitHubError) as caught:
            client.get_json("/x")
        assert caught.value.kind == kind
        assert caught.value.status == status
        assert len(transport.calls) == 1
        assert clock.sleeps == []

    def test_redirect_is_never_followed(self) -> None:
        redirect = json_response({}, 302, {"Location": "https://evil.example/steal"})
        client, transport, _ = make_client({"/x": redirect})
        with pytest.raises(GitHubError):
            client.get_json("/x")
        assert all(url.startswith(API_BASE) for url, _ in transport.calls)

    def test_network_failure_from_the_transport_propagates(self) -> None:
        client, _, _ = make_client({"/x": GitHubError("network", "could not reach GitHub")})
        with pytest.raises(GitHubError) as caught:
            client.get_json("/x")
        assert caught.value.kind == "network"


class TestRateLimits:
    def test_primary_limit_waits_for_the_reset_then_succeeds(self) -> None:
        clock = FakeClock(start=1000.0)
        limited = json_response(
            {"message": "API rate limit exceeded"},
            403,
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1010"},
        )
        client, transport, _ = make_client({"/x": Seq(limited, {"ok": True})}, clock=clock)
        assert client.get_json("/x") == {"ok": True}
        assert clock.sleeps == [11.0]
        assert len(transport.calls) == 2

    def test_retry_after_is_honoured_for_secondary_limits(self) -> None:
        limited = json_response({"message": "slow down"}, 429, {"Retry-After": "7"})
        client, _, clock = make_client({"/x": Seq(limited, {"ok": True})})
        assert client.get_json("/x") == {"ok": True}
        assert clock.sleeps == [7.0]

    def test_secondary_limit_without_headers_is_recognised_by_its_message(self) -> None:
        limited = json_response({"message": "You have exceeded a secondary rate limit."}, 403)
        client, _, _ = make_client({"/x": limited})
        with pytest.raises(GitHubError) as caught:
            client.get_json("/x")
        assert caught.value.kind == "secondary_rate_limit"

    def test_gives_up_after_two_retries(self) -> None:
        limited = json_response({}, 429, {"Retry-After": "1"})
        client, transport, clock = make_client({"/x": limited})
        with pytest.raises(GitHubError) as caught:
            client.get_json("/x")
        assert caught.value.kind == "secondary_rate_limit"
        assert len(transport.calls) == 3
        assert clock.sleeps == [1.0, 1.0]

    def test_does_not_wait_longer_than_the_bound(self) -> None:
        clock = FakeClock(start=1000.0)
        limited = json_response(
            {}, 403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "5000"}
        )
        client, transport, _ = make_client({"/x": limited}, clock=clock)
        with pytest.raises(GitHubError) as caught:
            client.get_json("/x")
        assert caught.value.kind == "rate_limit"
        assert clock.sleeps == []
        assert len(transport.calls) == 1

    def test_limit_without_reset_header_fails_instead_of_guessing(self) -> None:
        limited = json_response({}, 403, {"X-RateLimit-Remaining": "0"})
        client, _, clock = make_client({"/x": limited})
        with pytest.raises(GitHubError):
            client.get_json("/x")
        assert clock.sleeps == []

    def test_unauthenticated_limit_suggests_logging_in(self) -> None:
        limited = json_response({}, 403, {"X-RateLimit-Remaining": "0"})
        client, _, _ = make_client({"/x": limited}, token=None)
        with pytest.raises(GitHubError, match="gh auth login"):
            client.get_json("/x")


class TestStopsAfterRepeatingFailures:
    def test_no_request_is_sent_after_an_exhausted_rate_limit(self) -> None:
        limited = json_response({}, 429, {"Retry-After": "30"})
        client, transport, clock = make_client({"/a": limited, "/b": {"ok": True}})
        with pytest.raises(GitHubError):
            client.get_json("/a")
        calls, slept = len(transport.calls), sum(clock.sleeps)
        with pytest.raises(GitHubError) as caught:
            client.get_json("/b")
        assert str(caught.value) == "skipped after secondary_rate_limit: request not sent"
        assert len(transport.calls) == calls == 3
        assert sum(clock.sleeps) == slept == 60.0

    @pytest.mark.parametrize(
        "failure",
        [json_response({}, 401), GitHubError("network", "could not reach GitHub")],
    )
    def test_auth_and_network_failures_also_stop(self, failure: object) -> None:
        client, transport, _ = make_client({"/a": failure, "/b": {"ok": True}})
        with pytest.raises(GitHubError):
            client.get_json("/a")
        with pytest.raises(GitHubError, match="skipped after"):
            client.get_json("/b")
        assert len(transport.calls) == 1

    @pytest.mark.parametrize("status", [404, 422, 500])
    def test_other_failures_do_not_stop(self, status: int) -> None:
        client, _, _ = make_client({"/a": json_response({}, status), "/b": {"ok": True}})
        with pytest.raises(GitHubError):
            client.get_json("/a")
        assert client.get_json("/b") == {"ok": True}


class TestTokenNeverLeaks:
    @pytest.mark.parametrize("status", [401, 403, 404, 422, 429, 500, 302])
    def test_not_in_error_text_even_if_github_echoes_it(self, status: int) -> None:
        body = {"message": f"bad token {TOKEN} supplied"}
        headers = {"Authorization": f"Bearer {TOKEN}", "Location": f"https://x/?t={TOKEN}"}
        client, _, _ = make_client({"/x": json_response(body, status, headers)})
        with pytest.raises(GitHubError) as caught:
            client.get_json("/x")
        assert TOKEN not in str(caught.value)
        assert TOKEN not in repr(caught.value)

    def test_not_in_the_client_repr(self) -> None:
        client = Client(token=TOKEN, transport=FakeTransport())
        assert TOKEN not in repr(client)
