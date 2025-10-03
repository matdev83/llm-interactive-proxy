import os
import shutil
import unittest

from src.core.domain.replacement_rule import ReplacementMode
from src.core.services.content_rewriter_service import ContentRewriterService


class TestContentRewriterService(unittest.TestCase):
    def setUp(self):
        self.test_config_dir = "test_config"
        # Clean up any previous test directories
        if os.path.exists(self.test_config_dir):
            shutil.rmtree(self.test_config_dir)

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
        shutil.rmtree(self.test_config_dir)

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
        rewritten = service.rewrite_prompt(system_prompt, "system")
        # The order of execution is not guaranteed, so we check for both possibilities
        self.assertIn(
            rewritten,
            [
                "This is an prepended system: rewritten system prompt.",
                "This is an rewritten system prompt.",
            ],
        )

        # User prompt with REPLACE and APPEND
        user_prompt = "This is an original user prompt."
        rewritten = service.rewrite_prompt(user_prompt, "user")
        self.assertEqual(rewritten, "This is an rewritten user prompt.")

    def test_rewrite_reply(self):
        service = ContentRewriterService(config_path=self.test_config_dir)
        reply = "This is an original reply."
        rewritten = service.rewrite_reply(reply)
        self.assertEqual(rewritten, "This is an rewritten reply.")

    def test_rules_ignore_trailing_newlines_in_files(self):
        """Ensure rule files ending with newlines are applied correctly."""

        os.makedirs(
            os.path.join(
                self.test_config_dir,
                "prompts",
                "user",
                "003_newline",
            ),
            exist_ok=True,
        )

        with open(
            os.path.join(
                self.test_config_dir,
                "prompts",
                "user",
                "003_newline",
                "SEARCH.txt",
            ),
            "w",
        ) as file:
            file.write("newline marker\n")

        with open(
            os.path.join(
                self.test_config_dir,
                "prompts",
                "user",
                "003_newline",
                "REPLACE.txt",
            ),
            "w",
        ) as file:
            file.write("updated marker\n")

        service = ContentRewriterService(config_path=self.test_config_dir)

        prompt = "The newline marker should be replaced."
        rewritten_prompt = service.rewrite_prompt(prompt, "user")

        self.assertEqual(
            rewritten_prompt,
            "The updated marker should be replaced.",
        )


if __name__ == "__main__":
    unittest.main()

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
        self.assertEqual(len(rewriter.prompt_user_rules), 1)

        # The rule with the short search pattern should be ignored
        prompt = "This is a short test."
        rewritten_prompt = rewriter.rewrite_prompt(prompt, "user")
        self.assertEqual(rewritten_prompt, "This is a short test.")
