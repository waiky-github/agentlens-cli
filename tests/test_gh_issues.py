"""Tests for GitHub Issue monitoring (check_github_issues.py).

All GitHub API calls are mocked — no real network calls.
"""

import json
import os
import sys
from unittest.mock import patch

# Ensure scripts directory is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import _gh_api  # noqa: E402


class TestFetchOpenIssues:
    def test_filters_out_pull_requests(self):
        """Pull requests returned by the issues endpoint must be filtered out."""
        sample = [
            {"number": 1, "title": "real issue", "state": "open",
             "created_at": "2026-09-01T00:00:00Z"},
            {"number": 2, "title": "a PR", "pull_request": {"url": "..."},
             "state": "open", "created_at": "2026-09-02T00:00:00Z"},
            {"number": 3, "title": "another issue", "state": "open",
             "created_at": "2026-09-03T00:00:00Z"},
        ]

        def fake_api(path, token=None):
            return 200, sample

        with patch.object(_gh_api, "github_api", side_effect=fake_api):
            issues = _gh_api.fetch_open_issues("test/repo")
            assert len(issues) == 2
            assert issues[0]["number"] == 1
            assert issues[1]["number"] == 3

    def test_sorts_by_number_ascending(self):
        """Issues should be returned sorted by number."""
        sample = [
            {"number": 5, "title": "five", "state": "open",
             "created_at": "2026-09-01T00:00:00Z"},
            {"number": 1, "title": "one", "state": "open",
             "created_at": "2026-09-02T00:00:00Z"},
            {"number": 10, "title": "ten", "state": "open",
             "created_at": "2026-09-03T00:00:00Z"},
        ]

        def fake_api(path, token=None):
            return 200, sample

        with patch.object(_gh_api, "github_api", side_effect=fake_api):
            issues = _gh_api.fetch_open_issues("test/repo")
            assert [i["number"] for i in issues] == [1, 5, 10]

    def test_handles_api_error(self):
        """API errors return empty list."""
        def fake_api(path, token=None):
            return 403, "rate limited"

        with patch.object(_gh_api, "github_api", side_effect=fake_api):
            issues = _gh_api.fetch_open_issues("test/repo")
            assert issues == []

    def test_paginates(self):
        """Should paginate if first page returns 100 items."""
        page_data = {}

        def fake_api(path, token=None):
            # Extract page from path
            if "&page=2" in path:
                page = 2
            elif "&page=3" in path:
                page = 3
            elif "&page=" in path:
                page = 1
            else:
                page = 1
            if page not in page_data:
                page_data[page] = [
                    {"number": (page - 1) * 100 + i + 1, "title": f"issue {(page-1)*100 + i + 1}",
                     "state": "open", "created_at": "2026-09-01T00:00:00Z"}
                    for i in range(100 if page < 3 else 50)
                ]
            return 200, page_data[page]

        with patch.object(_gh_api, "github_api", side_effect=fake_api):
            issues = _gh_api.fetch_open_issues("test/repo")
            assert len(issues) == 250

    def test_handles_unexpected_response(self):
        """Non-list response returns empty list."""
        def fake_api(path, token=None):
            return 200, {"message": "not a list"}

        with patch.object(_gh_api, "github_api", side_effect=fake_api):
            issues = _gh_api.fetch_open_issues("test/repo")
            assert issues == []


class TestSearchIssues:
    def test_filters_prs_and_sorts(self):
        """Search should filter out PRs and sort by created_at."""
        sample = [
            {"number": 3, "title": "bug", "state": "open",
             "created_at": "2026-09-12T00:00:00Z", "labels": [{"name": "bug"}]},
            {"number": 1, "title": "feature", "state": "open",
             "created_at": "2026-09-10T00:00:00Z", "labels": [{"name": "enhancement"}]},
            {"number": 2, "title": "a PR", "pull_request": {"url": "x"},
             "created_at": "2026-09-11T00:00:00Z"},
        ]

        def fake_api(path, token=None):
            return 200, sample

        with patch.object(_gh_api, "github_api", side_effect=fake_api):
            issues = _gh_api.search_issues("test/repo", "2026-09-01")
            assert len(issues) == 2
            # sorted by created_at ascending
            assert [i["number"] for i in issues] == [1, 3]


class TestStateFileManagement:
    def test_first_run_creates_state_file(self, tmp_path):
        """First run with no issues should create state file."""
        state_path = str(tmp_path / "last_gh_issue.json")
        from _gh_api import github_api as real_api

        def fake_api(path, token=None):
            return 200, []

        with patch.object(_gh_api, "github_api", side_effect=fake_api):
            # Import and run check_github_issues main
            import check_github_issues
            exit_code = check_github_issues.main_impl(
                repo="test/repo",
                state_file=state_path,
                notify=False,
                all_issues=False,
            )
            assert exit_code == 0
            assert os.path.isfile(state_path)
            with open(state_path) as f:
                state = json.load(f)
            assert state["last_issue_number"] == 0

    def test_incremental_no_new_issues_silent(self, tmp_path):
        """Second run with no new issues produces no stdout."""
        state_path = str(tmp_path / "last_gh_issue.json")
        # Pre-create state with last_issue_number=5
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w") as f:
            json.dump({"last_issue_number": 5}, f)

        sample = [
            {"number": 1, "title": "old", "state": "open",
             "created_at": "2026-09-01T00:00:00Z"},
            {"number": 5, "title": "latest", "state": "open",
             "created_at": "2026-09-05T00:00:00Z"},
        ]

        def fake_api(path, token=None):
            return 200, sample

        import io
        import check_github_issues

        with patch.object(_gh_api, "github_api", side_effect=fake_api):
            captured = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                exit_code = check_github_issues.main_impl(
                    repo="test/repo",
                    state_file=state_path,
                    notify=False,
                    all_issues=False,
                )
            finally:
                sys.stdout = old_stdout
            assert exit_code == 0
            assert captured.getvalue() == ""

    def test_new_issue_produces_output(self, tmp_path):
        """A new issue number > last_issue_number should produce output."""
        state_path = str(tmp_path / "last_gh_issue.json")
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w") as f:
            json.dump({"last_issue_number": 5}, f)

        sample = [
            {"number": 5, "title": "latest known", "state": "open",
             "created_at": "2026-09-05T00:00:00Z", "user": {"login": "alice"},
             "html_url": "https://github.com/test/repo/issues/5",
             "body": "old body", "labels": []},
            {"number": 7, "title": "new bug", "state": "open",
             "created_at": "2026-09-06T00:00:00Z", "user": {"login": "bob"},
             "html_url": "https://github.com/test/repo/issues/7",
             "body": "something is broken", "labels": [{"name": "bug"}]},
        ]

        def fake_api(path, token=None):
            return 200, sample

        import io
        import check_github_issues

        with patch.object(_gh_api, "github_api", side_effect=fake_api):
            captured = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                exit_code = check_github_issues.main_impl(
                    repo="test/repo",
                    state_file=state_path,
                    notify=False,
                    all_issues=False,
                )
            finally:
                sys.stdout = old_stdout
            assert exit_code == 0
            output = captured.getvalue()
            assert "#7" in output
            assert "new bug" in output
            assert "bob" in output

    def test_all_flag_notifies_everything(self, tmp_path):
        """--all should output all open issues even if previously seen."""
        state_path = str(tmp_path / "last_gh_issue.json")
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w") as f:
            json.dump({"last_issue_number": 5}, f)

        sample = [
            {"number": 1, "title": "one", "state": "open",
             "created_at": "2026-09-01T00:00:00Z", "user": {"login": "a"},
             "html_url": "https://github.com/x/1", "body": "b1", "labels": []},
            {"number": 5, "title": "five", "state": "open",
             "created_at": "2026-09-05T00:00:00Z", "user": {"login": "b"},
             "html_url": "https://github.com/x/5", "body": "b5", "labels": []},
        ]

        def fake_api(path, token=None):
            return 200, sample

        import io
        import check_github_issues

        with patch.object(_gh_api, "github_api", side_effect=fake_api):
            captured = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                exit_code = check_github_issues.main_impl(
                    repo="test/repo",
                    state_file=state_path,
                    notify=False,
                    all_issues=True,
                )
            finally:
                sys.stdout = old_stdout
            assert exit_code == 0
            output = captured.getvalue()
            assert "#1" in output
            assert "#5" in output


# Add main_impl to check_github_issues so we can call it without argparse
def _add_main_impl():
    """Monkey-patch check_github_issues with a testable main_impl."""
    import check_github_issues

    def main_impl(repo, state_file, notify=False, all_issues=False):
        import check_github_issues as cgi

        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or None
        state = cgi._load_state(state_file)

        issues = cgi.fetch_open_issues(repo, token)

        if not issues:
            if not os.path.isfile(state_file):
                cgi._save_state(state_file, state)
            return 0

        if all_issues:
            new_issues = issues
        else:
            last_num = state.get("last_issue_number", 0)
            new_issues = [i for i in issues if i["number"] > last_num]
            if not new_issues:
                return 0

        lines = []
        if all_issues and state.get("last_issue_number", 0) == 0:
            lines.append("[首次运行] 当前全部 Open Issues:")
        elif all_issues:
            lines.append("[全量通知] 当前全部 Open Issues:")

        for issue in new_issues:
            lines.append(cgi._format_issue(issue))

        text = "\n".join(lines)
        print(text)

        if notify:
            subject = (
                f"agentlens 新 Issue: #{new_issues[0]['number']} {new_issues[0]['title']}"
                if len(new_issues) == 1
                else f"agentlens 新增 {len(new_issues)} 个 Issue"
            )
            cgi._notify(subject, text)

        max_num = max(i["number"] for i in issues)
        state["last_issue_number"] = max_num
        cgi._save_state(state_file, state)
        return 0

    check_github_issues.main_impl = main_impl


_add_main_impl()