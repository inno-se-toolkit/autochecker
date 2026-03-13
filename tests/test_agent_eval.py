"""Integration tests for agent_eval flow.

Tests the full eval pipeline by mocking the relay SSH layer.
Catches regressions like:
  - server_ip not passed → eval never runs via SSH
  - CRLF in .env.agent.secret → agent crashes
  - stdout truncation breaking JSON parsing
  - question filtering (bot_only_exclusively, include_bot_only, sampling)
  - grading logic (match_answer, source checks, tool checks)

Run:  pytest tests/test_agent_eval.py -v
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autochecker.engine import CheckEngine, _sample_eval_questions

SPECS_DIR = ROOT / "specs"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_engine():
    """Create a CheckEngine with mocked GitHub client and server_ip set."""
    client = MagicMock()
    client._owner = "test-student"
    reader = MagicMock()
    engine = CheckEngine(
        client=client,
        reader=reader,
        server_ip="10.93.24.100",
        lms_api_key="test-api-key",
        vm_username="autochecker",
    )
    return engine


@pytest.fixture
def eval_questions():
    """Load the lab-06 eval questions."""
    eval_file = SPECS_DIR / "lab-06-eval.yaml"
    if not eval_file.exists():
        pytest.skip("lab-06-eval.yaml not found")
    with open(eval_file) as f:
        return yaml.safe_load(f) or []


def _make_ssh_response(stdout="", stderr="", exit_code=0, error=""):
    """Helper to build relay SSH response dicts."""
    return True, {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "error": error,
    }


# ---------------------------------------------------------------------------
# Question filtering & sampling
# ---------------------------------------------------------------------------

class TestQuestionFiltering:
    def test_eval_file_has_20_questions(self, eval_questions):
        assert len(eval_questions) == 20

    def test_local_questions_are_0_to_9(self, eval_questions):
        local = [q for q in eval_questions if not q.get("bot_only")]
        assert len(local) == 10
        assert all(q["index"] < 10 for q in local)

    def test_bot_only_questions_are_10_to_19(self, eval_questions):
        hidden = [q for q in eval_questions if q.get("bot_only")]
        assert len(hidden) == 10
        assert all(q["index"] >= 10 for q in hidden)

    def test_five_classes_two_per_class(self, eval_questions):
        """Each class (A-E) has exactly 2 local + 2 bot_only questions."""
        def class_of(idx):
            return chr(ord("A") + (idx % 10) // 2)

        for label in "ABCDE":
            local = [q for q in eval_questions
                     if class_of(q["index"]) == label and not q.get("bot_only")]
            hidden = [q for q in eval_questions
                      if class_of(q["index"]) == label and q.get("bot_only")]
            assert len(local) == 2, f"Class {label}: expected 2 local, got {len(local)}"
            assert len(hidden) == 2, f"Class {label}: expected 2 hidden, got {len(hidden)}"

    def test_bot_only_exclusively_filters_local(self, eval_questions):
        """bot_only_exclusively=True should keep only bot_only questions."""
        filtered = [q for q in eval_questions
                    if q.get("bot_only", False)]
        assert len(filtered) == 10
        assert all(q["index"] >= 10 for q in filtered)

    def test_include_bot_only_false_filters_hidden(self, eval_questions):
        """include_bot_only=False should keep only local questions."""
        filtered = [q for q in eval_questions
                    if not q.get("bot_only", False)]
        assert len(filtered) == 10
        assert all(q["index"] < 10 for q in filtered)

    def test_sample_per_class_1_gives_5(self, eval_questions):
        # Sample from local only
        local = [q for q in eval_questions if not q.get("bot_only")]
        sampled = _sample_eval_questions(local, sample_per_class=1)
        assert len(sampled) == 5

    def test_sample_per_class_1_hidden_gives_5(self, eval_questions):
        hidden = [q for q in eval_questions if q.get("bot_only")]
        sampled = _sample_eval_questions(hidden, sample_per_class=1)
        assert len(sampled) == 5

    def test_sample_covers_all_classes(self, eval_questions):
        """Sampling 1 per class should cover all 5 classes."""
        def class_of(idx):
            return chr(ord("A") + (idx % 10) // 2)

        sampled = _sample_eval_questions(eval_questions, sample_per_class=1)
        classes = {class_of(q["index"]) for q in sampled}
        assert classes == {"A", "B", "C", "D", "E"}


# ---------------------------------------------------------------------------
# Answer matching
# ---------------------------------------------------------------------------

class TestAnswerMatching:
    def test_contains(self, mock_engine):
        assert mock_engine._match_answer("FastAPI is great", {"contains": "fastapi"})
        assert not mock_engine._match_answer("Django", {"contains": "fastapi"})

    def test_contains_all(self, mock_engine):
        assert mock_engine._match_answer(
            "items, interactions, analytics, pipeline",
            {"contains_all": ["items", "interactions", "analytics", "pipeline"]},
        )
        assert not mock_engine._match_answer(
            "items and interactions",
            {"contains_all": ["items", "interactions", "analytics"]},
        )

    def test_any_of(self, mock_engine):
        assert mock_engine._match_answer("uses FastAPI", {"any_of": ["FastAPI", "flask"]})
        assert not mock_engine._match_answer("uses Django", {"any_of": ["FastAPI", "flask"]})

    def test_numeric_gt(self, mock_engine):
        assert mock_engine._match_answer("There are 42 items", {"numeric_gt": 0})
        assert not mock_engine._match_answer("There are 0 items", {"numeric_gt": 0})

    def test_regex(self, mock_engine):
        assert mock_engine._match_answer("ZeroDivisionError", {"regex": r"zero.*error|division"})


# ---------------------------------------------------------------------------
# SSH eval end-to-end (mocked relay)
# ---------------------------------------------------------------------------

class TestAgentEvalSSH:
    """Integration tests for check_agent_eval_ssh with mocked SSH relay."""

    def _setup_ssh_mock(self, mock_engine, agent_response, env_file="SECRET"):
        """Configure mock SSH responses for a standard eval run.

        Returns the mock so tests can inspect calls.
        """
        call_count = [0]
        agent_json = json.dumps(agent_response)

        def fake_ssh(host, port, username, command, timeout):
            call_count[0] += 1
            cmd = command

            # Step 1: find agent.py
            if "find" in cmd and "agent.py" in cmd:
                return _make_ssh_response("/home/student/se-toolkit-lab-6/agent.py")

            # Step 2: check env file
            if ".env.agent.secret" in cmd and "echo SECRET" in cmd:
                return _make_ssh_response(env_file)

            # Step 3: git pull + uv sync
            if "git pull" in cmd and "uv sync" in cmd:
                return _make_ssh_response("/home/student/.local/bin/uv\nResolved 10 packages")

            # Step 4: read cache (if requested)
            if "_eval_cache.json" in cmd:
                return _make_ssh_response("{}")

            # Step 5+: agent.py runs
            if "uv run agent.py" in cmd:
                return _make_ssh_response(agent_json)

            # Fallback
            return _make_ssh_response("ok")

        mock_engine._ssh_check_via_relay = MagicMock(side_effect=fake_ssh)
        return mock_engine._ssh_check_via_relay

    @patch.dict(os.environ, {"RELAY_TOKEN": "test-token"})
    def test_passing_eval_local_questions(self, mock_engine, eval_questions):
        """Agent that answers all local questions correctly should pass."""
        # Build an agent response that passes class A (wiki question)
        agent_response = {
            "answer": "To protect a branch on GitHub, go to Settings > Branches > "
                      "Add branch protection rule. Enable require pull request reviews.",
            "tool_calls": [{"tool": "read_file", "args": {"path": "wiki/github.md"}}],
            "source": "wiki/github.md",
        }
        self._setup_ssh_mock(mock_engine, agent_response)

        passed, details = mock_engine.check_agent_eval_ssh(
            eval_lab="lab-06",
            include_bot_only=False,
            sample_per_class=1,
            min_pass_rate=0.0,  # don't fail on content mismatch
        )

        assert "Agent eval:" in details
        assert "/5" in details  # should have 5 questions

    @patch.dict(os.environ, {"RELAY_TOKEN": "test-token"})
    def test_no_server_ip_returns_error(self, eval_questions):
        """Without server_ip, eval should fail with clear message."""
        client = MagicMock()
        client._owner = "test-student"
        engine = CheckEngine(
            client=client,
            reader=MagicMock(),
            server_ip="",  # <-- no server IP
        )

        passed, details = engine.check_agent_eval_ssh(eval_lab="lab-06")

        assert not passed
        assert "SERVER_IP" in details

    @patch.dict(os.environ, {"RELAY_TOKEN": "test-token"})
    def test_agent_timeout_reported(self, mock_engine, eval_questions):
        """Timed-out agent runs should be reported per-question."""
        def timeout_ssh(host, port, username, command, timeout):
            if "find" in command and "agent.py" in command:
                return _make_ssh_response("/home/s/se-toolkit-lab-6/agent.py")
            if "echo SECRET" in command:
                return _make_ssh_response("SECRET")
            if "git pull" in command:
                return _make_ssh_response("/home/s/.local/bin/uv")
            if "_eval_cache" in command:
                return _make_ssh_response("{}")
            if "uv run agent.py" in command:
                return False, {"exit_code": -1, "stdout": "", "stderr": "",
                               "error": "timeout"}
            return _make_ssh_response("ok")

        mock_engine._ssh_check_via_relay = MagicMock(side_effect=timeout_ssh)

        passed, details = mock_engine.check_agent_eval_ssh(
            eval_lab="lab-06",
            bot_only_exclusively=True,
            sample_per_class=1,
        )

        assert not passed
        assert "timed out" in details

    @patch.dict(os.environ, {"RELAY_TOKEN": "test-token"})
    def test_invalid_json_output_reported(self, mock_engine, eval_questions):
        """Agent that prints non-JSON should get clear error."""
        def bad_json_ssh(host, port, username, command, timeout):
            if "find" in command and "agent.py" in command:
                return _make_ssh_response("/home/s/se-toolkit-lab-6/agent.py")
            if ".env.agent.secret" in command:
                return _make_ssh_response("SECRET")
            if "git pull" in command:
                return _make_ssh_response("/home/s/.local/bin/uv")
            if "_eval_cache" in command:
                return _make_ssh_response("{}")
            if "uv run agent.py" in command:
                return _make_ssh_response("Error: something went wrong\nNot JSON")
            return _make_ssh_response("ok")

        mock_engine._ssh_check_via_relay = MagicMock(side_effect=bad_json_ssh)

        passed, details = mock_engine.check_agent_eval_ssh(
            eval_lab="lab-06",
            include_bot_only=False,
            sample_per_class=1,
        )

        assert not passed
        assert "No JSON" in details

    @patch.dict(os.environ, {"RELAY_TOKEN": "test-token"})
    def test_missing_answer_field_reported(self, mock_engine, eval_questions):
        """Agent JSON without 'answer' field should be flagged."""
        agent_response = {"tool_calls": [], "source": "something.py"}
        self._setup_ssh_mock(mock_engine, agent_response)

        passed, details = mock_engine.check_agent_eval_ssh(
            eval_lab="lab-06",
            include_bot_only=False,
            sample_per_class=1,
        )

        assert not passed
        assert "Missing 'answer'" in details

    @patch.dict(os.environ, {"RELAY_TOKEN": "test-token"})
    def test_agent_exit_code_1_reported(self, mock_engine, eval_questions):
        """Agent that crashes (exit code 1) should show the error."""
        def crash_ssh(host, port, username, command, timeout):
            if "find" in command and "agent.py" in command:
                return _make_ssh_response("/home/s/se-toolkit-lab-6/agent.py")
            if "echo SECRET" in command:
                return _make_ssh_response("SECRET")
            if "git pull" in command:
                return _make_ssh_response("/home/s/.local/bin/uv")
            if "_eval_cache" in command:
                return _make_ssh_response("{}")
            if "uv run agent.py" in command:
                return True, {"exit_code": 1, "stdout": "",
                              "stderr": "ModuleNotFoundError: No module named 'openai'"}
            return _make_ssh_response("ok")

        mock_engine._ssh_check_via_relay = MagicMock(side_effect=crash_ssh)

        passed, details = mock_engine.check_agent_eval_ssh(
            eval_lab="lab-06",
            include_bot_only=False,
            sample_per_class=1,
        )

        assert not passed
        assert "exited with code 1" in details

    @patch.dict(os.environ, {"RELAY_TOKEN": "test-token"})
    def test_env_file_missing_triggers_auto_detect(self, mock_engine, eval_questions):
        """When .env.agent.secret is missing, eval should try proxy auto-detect."""
        detect_calls = []

        def missing_env_ssh(host, port, username, command, timeout):
            if "find" in command and "agent.py" in command:
                return _make_ssh_response("/home/s/se-toolkit-lab-6/agent.py")
            if ".env.agent.secret" in command and "echo SECRET" in command:
                return _make_ssh_response("MISSING")
            if "qwen-code-oai-proxy" in command:
                detect_calls.append(command)
                return _make_ssh_response("NO_PROXY_ENV")
            return _make_ssh_response("ok")

        mock_engine._ssh_check_via_relay = MagicMock(side_effect=missing_env_ssh)

        passed, details = mock_engine.check_agent_eval_ssh(
            eval_lab="lab-06",
            include_bot_only=False,
            sample_per_class=1,
        )

        assert not passed
        assert "No LLM credentials" in details
        assert len(detect_calls) > 0  # Should have tried auto-detect


# ---------------------------------------------------------------------------
# Spec structure validation
# ---------------------------------------------------------------------------

class TestLabSpecIntegrity:
    """Validate that lab-06.yaml spec is internally consistent."""

    @pytest.fixture
    def spec(self):
        spec_file = SPECS_DIR / "lab-06.yaml"
        if not spec_file.exists():
            pytest.skip("lab-06.yaml not found")
        with open(spec_file) as f:
            return yaml.safe_load(f)

    def test_all_check_ids_unique(self, spec):
        ids = [c["id"] for c in spec["checks"]]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {[x for x in ids if ids.count(x) > 1]}"

    def test_depends_on_references_exist(self, spec):
        all_ids = {c["id"] for c in spec["checks"]}
        for c in spec["checks"]:
            for dep in c.get("depends_on", []):
                assert dep in all_ids, f"Check {c['id']} depends on non-existent {dep}"

    def test_agent_eval_checks_have_required_params(self, spec):
        for c in spec["checks"]:
            if c.get("type") == "agent_eval":
                params = c.get("params", {})
                assert "eval_lab" in params, f"{c['id']} missing eval_lab"
                assert "min_pass_rate" in params, f"{c['id']} missing min_pass_rate"
                assert "sample_per_class" in params, f"{c['id']} missing sample_per_class"

    def test_task3_local_eval_before_hidden(self, spec):
        """Verify local eval runs before hidden eval (dependency chain)."""
        checks_by_id = {c["id"]: c for c in spec["checks"]}
        assert "task3_local_eval" in checks_by_id, "Missing task3_local_eval check"
        assert "task3_eval" in checks_by_id, "Missing task3_eval check"

        hidden_eval = checks_by_id["task3_eval"]
        assert "task3_local_eval" in hidden_eval.get("depends_on", []), \
            "task3_eval must depend on task3_local_eval"

    def test_local_eval_excludes_hidden_questions(self, spec):
        checks_by_id = {c["id"]: c for c in spec["checks"]}
        local_eval = checks_by_id.get("task3_local_eval", {})
        params = local_eval.get("params", {})
        assert params.get("include_bot_only") is False, \
            "task3_local_eval must set include_bot_only: false"

    def test_hidden_eval_uses_bot_only_exclusively(self, spec):
        checks_by_id = {c["id"]: c for c in spec["checks"]}
        hidden_eval = checks_by_id.get("task3_eval", {})
        params = hidden_eval.get("params", {})
        assert params.get("bot_only_exclusively") is True, \
            "task3_eval must set bot_only_exclusively: true"


# ---------------------------------------------------------------------------
# Bot handler: server_ip fetch logic
# ---------------------------------------------------------------------------

class TestServerIpFetch:
    """Verify that agent_eval tasks trigger server_ip fetch."""

    @patch.dict(os.environ, {"BOT_TOKEN": "fake", "GITHUB_TOKEN": "fake"})
    def test_agent_eval_task_needs_lms_key(self):
        """get_tasks_needing_lms_key should return task-3 for lab-06."""
        # bot.config raises on missing BOT_TOKEN at import time
        import importlib
        import bot.config
        importlib.reload(bot.config)
        tasks = bot.config.get_tasks_needing_lms_key("lab-06")
        assert "task-3" in tasks, \
            "task-3 must be in get_tasks_needing_lms_key('lab-06') — " \
            "otherwise server_ip won't be fetched and eval breaks"

    @patch.dict(os.environ, {"BOT_TOKEN": "fake", "GITHUB_TOKEN": "fake"})
    def test_agent_eval_task_triggers_ip_or_lms(self):
        """The check handler must fetch server_ip for tasks in get_tasks_needing_lms_key."""
        import importlib
        import bot.config
        importlib.reload(bot.config)
        ip_tasks = bot.config.get_tasks_needing_ip("lab-06")
        lms_tasks = bot.config.get_tasks_needing_lms_key("lab-06")
        # task-3 might not be in ip_tasks, but MUST be in lms_tasks
        assert "task-3" in (ip_tasks | lms_tasks), \
            "task-3 must be discoverable for server_ip fetch"
