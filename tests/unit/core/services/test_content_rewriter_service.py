import os
import shutil
import tempfile
import unittest

from src.core.config.app_config import RewritingConfig
from src.core.domain.replacement_rule import ReplacementMode
from src.core.services.content_rewriter_service import ContentRewriterService


class TestContentRewriterService(unittest.TestCase):
    def setUp(self):
        # Use a temporary directory to avoid Windows permission issues
        self.test_config_dir = tempfile.mkdtemp(prefix="test_config_")

        # Create directories for different rule types
        os.makedirs(
            os.path.join(self.test_config_dir, "prompts", "system", "001_replace"),
            exist_ok=True,
        )
        os.makedirs(
            os.path.join(self.test_config_dir, "prompts", "system", "002_prepend"),
            exist_ok=True,
        )
        os.makedirs(
            os.path.join(self.test_config_dir, "prompts", "user", "001_replace"),
            exist_ok=True,
        )
        os.makedirs(
            os.path.join(self.test_config_dir, "prompts", "user", "002_append"),
            exist_ok=True,
        )
        os.makedirs(
            os.path.join(self.test_config_dir, "replies", "001_replace"), exist_ok=True
        )

        # Rule 1: System prompt - REPLACE
        with open(
            os.path.join(
                self.test_config_dir,
                "prompts",
                "system",
                "001_replace",
                "SEARCH.txt",
            ),
            "w",
        ) as f:
            f.write("original system")
        with open(
            os.path.join(
                self.test_config_dir,
                "prompts",
                "system",
                "001_replace",
                "REPLACE.txt",
            ),
            "w",
        ) as f:
            f.write("rewritten system")

        # Rule 2: System prompt - PREPEND
        with open(
            os.path.join(
                self.test_config_dir,
                "prompts",
                "system",
                "002_prepend",
                "SEARCH.txt",
            ),
            "w",
        ) as f:
            f.write("original system")
        with open(
            os.path.join(
                self.test_config_dir,
                "prompts",
                "system",
                "002_prepend",
                "PREPEND.txt",
            ),
            "w",
        ) as f:
            f.write("prepended system: ")

        # Rule 3: User prompt - REPLACE
        with open(
            os.path.join(
                self.test_config_dir, "prompts", "user", "001_replace", "SEARCH.txt"
            ),
            "w",
        ) as f:
            f.write("original user")
        with open(
            os.path.join(
                self.test_config_dir, "prompts", "user", "001_replace", "REPLACE.txt"
            ),
            "w",
        ) as f:
            f.write("rewritten user")

        # Rule 4: User prompt - APPEND
        with open(
            os.path.join(
                self.test_config_dir, "prompts", "user", "002_append", "SEARCH.txt"
            ),
            "w",
        ) as f:
            f.write("original user")
        with open(
            os.path.join(
                self.test_config_dir, "prompts", "user", "002_append", "APPEND.txt"
            ),
            "w",
        ) as f:
            f.write(" :appended user")

        # Rule 5: Reply - REPLACE
        with open(
            os.path.join(self.test_config_dir, "replies", "001_replace", "SEARCH.txt"),
            "w",
        ) as f:
            f.write("original reply")
        with open(
            os.path.join(self.test_config_dir, "replies", "001_replace", "REPLACE.txt"),
            "w",
        ) as f:
            f.write("rewritten reply")

    def tearDown(self):
        # More robust cleanup for Windows file systems
        try:
            shutil.rmtree(self.test_config_dir, ignore_errors=True)
        except (OSError, PermissionError):
            # Windows file system cleanup issues - try multiple times
            # Use retry without sleep - file system operations don't need time delays
            for attempt in range(3):
                try:
                    shutil.rmtree(self.test_config_dir, ignore_errors=True)
                    break
                except (OSError, PermissionError):
                    if attempt == 2:
                        # Final attempt - try to remove as much as possible
                        try:
                            import atexit

                            atexit.register(
                                lambda: shutil.rmtree(
                                    self.test_config_dir, ignore_errors=True
                                )
                            )
                        except Exception:
                            pass

    def test_load_rules(self):
        service = ContentRewriterService(config_path=self.test_config_dir)

        # System rules
        self.assertEqual(len(service.prompt_system_rules), 2)
        replace_rule = next(
            r for r in service.prompt_system_rules if r.mode == ReplacementMode.REPLACE
        )
        self.assertEqual(replace_rule.search, "original system")
        self.assertEqual(replace_rule.replace, "rewritten system")
        prepend_rule = next(
            r for r in service.prompt_system_rules if r.mode == ReplacementMode.PREPEND
        )
        self.assertEqual(prepend_rule.search, "original system")
        self.assertEqual(prepend_rule.prepend, "prepended system: ")

        # User rules
        self.assertEqual(len(service.prompt_user_rules), 2)
        replace_rule = next(
            r for r in service.prompt_user_rules if r.mode == ReplacementMode.REPLACE
        )
        self.assertEqual(replace_rule.search, "original user")
        self.assertEqual(replace_rule.replace, "rewritten user")
        append_rule = next(
            r for r in service.prompt_user_rules if r.mode == ReplacementMode.APPEND
        )
        self.assertEqual(append_rule.search, "original user")
        self.assertEqual(append_rule.append, " :appended user")

        # Reply rules
        self.assertEqual(len(service.reply_rules), 1)
        self.assertEqual(service.reply_rules[0].mode, ReplacementMode.REPLACE)
        self.assertEqual(service.reply_rules[0].search, "original reply")
        self.assertEqual(service.reply_rules[0].replace, "rewritten reply")

    def test_rewrite_prompt(self):
        service = ContentRewriterService(config_path=self.test_config_dir)

        # System prompt with REPLACE and PREPEND
        system_prompt = "This is an original system prompt."
        rewritten_system = service.rewrite_prompt(system_prompt, "system")
        self.assertIn(
            rewritten_system,
            [
                "This is an prepended system: rewritten system prompt.",
                "This is an rewritten system prompt.",
            ],
        )

        # User prompt with REPLACE and APPEND
        user_prompt = "This is an original user prompt."
        rewritten_user = service.rewrite_prompt(user_prompt, "user")
        self.assertEqual(rewritten_user, "This is an rewritten user prompt.")

    def test_rewrite_prompt_for_developer_role(self):
        """Developer role prompts should reuse system rewrite rules."""

        service = ContentRewriterService(config_path=self.test_config_dir)

        developer_prompt = "This is an original system prompt."
        rewritten = service.rewrite_prompt(developer_prompt, "developer")

        self.assertIn(
            rewritten,
            [
                "This is an prepended system: rewritten system prompt.",
                "This is an rewritten system prompt.",
            ],
        )

    def test_rewrite_reply(self):
        service = ContentRewriterService(config_path=self.test_config_dir)
        reply = "This is an original reply."
        rewritten = service.rewrite_reply(reply)
        self.assertEqual(rewritten, "This is an rewritten reply.")

    def test_app_config_overrides_default_config_path(self):
        alternate_dir = os.path.join(self.test_config_dir, "app_config_rules")
        os.makedirs(
            os.path.join(alternate_dir, "replies", "010_replace"), exist_ok=True
        )

        with open(
            os.path.join(alternate_dir, "replies", "010_replace", "SEARCH.txt"),
            "w",
        ) as handle:
            handle.write("custom reply")

        with open(
            os.path.join(alternate_dir, "replies", "010_replace", "REPLACE.txt"),
            "w",
        ) as handle:
            handle.write("rewritten custom reply")

        from src.core.config.app_config import AppConfig

        app_config = AppConfig(
            rewriting=RewritingConfig(enabled=True, config_path=alternate_dir)
        )

        service = ContentRewriterService(app_config=app_config)

        self.assertEqual(service.config_path, alternate_dir)
        self.assertEqual(
            service.rewrite_reply("custom reply"),
            "rewritten custom reply",
        )

    def test_rewrite_prompt_ignores_trailing_newline_in_search_rule(self):
        """Trailing newlines in SEARCH.txt should not prevent matches."""

        os.makedirs(
            os.path.join(self.test_config_dir, "prompts", "system", "003"),
            exist_ok=True,
        )
        with open(
            os.path.join(
                self.test_config_dir,
                "prompts",
                "system",
                "003",
                "SEARCH.txt",
            ),
            "w",
        ) as f:
            f.write("newline sensitive\n")
        with open(
            os.path.join(
                self.test_config_dir,
                "prompts",
                "system",
                "003",
                "REPLACE.txt",
            ),
            "w",
        ) as f:
            f.write("newline resilient")

        service = ContentRewriterService(config_path=self.test_config_dir)

        rewritten = service.rewrite_prompt(
            "This is newline sensitive content.", "system"
        )

        self.assertEqual(rewritten, "This is newline resilient content.")

    def test_ignore_rule_with_short_search_pattern(self):
        """Verify that a rule with a short search pattern is ignored."""
        # Create a rule with a search pattern shorter than 8 characters
        os.makedirs(
            os.path.join(self.test_config_dir, "prompts", "user", "002"),
            exist_ok=True,
        )
        with open(
            os.path.join(self.test_config_dir, "prompts", "user", "002", "SEARCH.txt"),
            "w",
        ) as f:
            f.write("short")
        with open(
            os.path.join(self.test_config_dir, "prompts", "user", "002", "REPLACE.txt"),
            "w",
        ) as f:
            f.write("rewritten")

        rewriter = ContentRewriterService(config_path=self.test_config_dir)
        self.assertEqual(len(rewriter.prompt_user_rules), 2)

        # The rule with the short search pattern should be ignored
        prompt = "This is a short test."
        rewritten_prompt = rewriter.rewrite_prompt(prompt, "user")
        self.assertEqual(rewritten_prompt, "This is a short test.")

    def test_ignore_rule_when_search_file_missing(self):
        """Verify that a rule without a SEARCH.txt file is ignored."""
        os.makedirs(
            os.path.join(self.test_config_dir, "prompts", "system", "003_missing"),
            exist_ok=True,
        )
        with open(
            os.path.join(
                self.test_config_dir,
                "prompts",
                "system",
                "003_missing",
                "REPLACE.txt",
            ),
            "w",
        ) as f:
            f.write("unreachable")

        # Should not raise and should ignore the rule without SEARCH.txt
        service = ContentRewriterService(config_path=self.test_config_dir)
        self.assertEqual(len(service.prompt_system_rules), 2)


if __name__ == "__main__":
    unittest.main()
