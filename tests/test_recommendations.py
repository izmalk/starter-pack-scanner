"""Tests for per-check recommendations ("How to fix this?" guidance)."""

from __future__ import annotations

from pathlib import Path

from starter_pack_scanner.base import (
    RECOMMENDATION_HARD_LIMIT,
    RECOMMENDATION_SOFT_LIMIT,
    BaseCheck,
    CheckResult,
    set_show_recommendations,
)
from starter_pack_scanner.checks import ALL_CHECKS
from starter_pack_scanner.site import SiteContext


class TestRecommendationPresence:
    def test_every_check_has_a_recommendation(self):
        missing = [cls().id for cls in ALL_CHECKS if not cls().recommendation]
        assert not missing, f"Checks without a recommendation: {missing}"

    def test_every_recommendation_within_hard_limit(self):
        over = [
            (cls().id, len(cls().recommendation))
            for cls in ALL_CHECKS
            if len(cls().recommendation) > RECOMMENDATION_HARD_LIMIT
        ]
        assert not over, f"Recommendations over {RECOMMENDATION_HARD_LIMIT} chars: {over}"

    def test_soft_limit_reported_not_enforced(self):
        """Soft limit is a guideline; just report violations for visibility."""
        over = [
            (cls().id, len(cls().recommendation))
            for cls in ALL_CHECKS
            if len(cls().recommendation) > RECOMMENDATION_SOFT_LIMIT
        ]
        if over:
            print(f"NOTE: recommendations over soft limit ({RECOMMENDATION_SOFT_LIMIT}): {over}")


class TestExecuteStampsRecommendation:
    def test_execute_fills_class_recommendation(self):
        class _Check(BaseCheck):
            id = "test-stamp"
            name = "Test"
            description = "Test check."
            recommendation = "Fix it like this."

            def run(self, repo_root, docs_dir, site_ctx=None):
                return CheckResult(
                    check_id=self.id, check_name=self.name,
                    passed=False, message="failed",
                )

        result = _Check().execute(Path("."), None)
        assert result.recommendation == "Fix it like this."

    def test_execute_does_not_overwrite_result_recommendation(self):
        class _Check(BaseCheck):
            id = "test-keep"
            name = "Test"
            description = "Test check."
            recommendation = "Generic advice."

            def run(self, repo_root, docs_dir, site_ctx=None):
                return CheckResult(
                    check_id=self.id, check_name=self.name,
                    passed=False, message="failed",
                    recommendation="Specific advice.",
                )

        result = _Check().execute(Path("."), None)
        assert result.recommendation == "Specific advice."

    def test_execute_on_passing_result(self):
        class _Check(BaseCheck):
            id = "test-pass"
            name = "Test"
            description = "Test check."
            recommendation = "Advice."

            def run(self, repo_root, docs_dir, site_ctx=None):
                return CheckResult(
                    check_id=self.id, check_name=self.name,
                    passed=True, message="ok",
                )

        result = _Check().execute(Path("."), None)
        # Recommendation is stored even on passes; display layers gate on `passed`.
        assert result.recommendation == "Advice."


class TestSharedHelperRecommendations:
    def test_site_unavailable_has_setup_recommendation(self):
        from starter_pack_scanner.base import site_unavailable

        class _Check(BaseCheck):
            id = "test-unavail"
            name = "Test"
            description = "Test check."
            recommendation = "Check-specific advice."

            def run(self, repo_root, docs_dir, site_ctx=None):  # pragma: no cover
                raise NotImplementedError

        result = site_unavailable(_Check(), None)
        # The helper's own recommendation wins over the check's (the fix is
        # about scan setup, not the check's subject); execute() preserves it
        # because it only fills in empty recommendations.
        assert "--docs-url" in result.recommendation
        assert result.recommendation != "Check-specific advice."

    def test_no_pages_has_setup_recommendation(self):
        from starter_pack_scanner.base import no_pages

        class _Check(BaseCheck):
            id = "test-nopages"
            name = "Test"
            description = "Test check."
            recommendation = "Check-specific advice."

            def run(self, repo_root, docs_dir, site_ctx=None):  # pragma: no cover
                raise NotImplementedError

        ctx = SiteContext(base_url="https://canonical.com/example/docs/")
        result = no_pages(_Check(), ctx)
        assert "sphinx_sitemap" in result.recommendation


class TestSerialization:
    def test_to_dict_includes_recommendation(self):
        r = CheckResult(
            check_id="x", check_name="X", passed=False,
            message="m", recommendation="do this",
        )
        assert r.to_dict()["recommendation"] == "do this"

    def test_from_dict_with_recommendation(self):
        r = CheckResult.from_dict({
            "check_id": "x", "check_name": "X", "passed": False,
            "message": "m", "details": [], "recommendation": "do this",
        })
        assert r.recommendation == "do this"

    def test_from_dict_without_recommendation_key(self):
        """Regression: reports cached before the recommendation field existed
        have no 'recommendation' key and must still deserialise."""
        r = CheckResult.from_dict({
            "check_id": "x", "check_name": "X", "passed": True,
            "message": "m", "details": [],
        })
        assert r.recommendation == ""


class TestCliRendering:
    def test_str_shows_fix_on_failure(self):
        r = CheckResult(
            check_id="x", check_name="X", passed=False,
            message="broken", recommendation="repair it",
        )
        set_show_recommendations(True)
        try:
            assert "Fix:" in str(r)
            assert "repair it" in str(r)
        finally:
            set_show_recommendations(True)

    def test_str_hides_fix_on_pass(self):
        r = CheckResult(
            check_id="x", check_name="X", passed=True,
            message="fine", recommendation="advice",
        )
        assert "Fix:" not in str(r)

    def test_str_hides_fix_when_disabled(self):
        r = CheckResult(
            check_id="x", check_name="X", passed=False,
            message="broken", recommendation="repair it",
        )
        set_show_recommendations(False)
        try:
            assert "Fix:" not in str(r)
        finally:
            set_show_recommendations(True)
