import logging
import os

from src.core.domain.replacement_rule import ReplacementMode, ReplacementRule

logger = logging.getLogger(__name__)


class ContentRewriterService:
    """Loads and applies content replacement rules."""

    def __init__(self, config_path: str = "config/replacements"):
        self.config_path = config_path
        self.prompt_system_rules: list[ReplacementRule] = []
        self.prompt_user_rules: list[ReplacementRule] = []
        self.reply_rules: list[ReplacementRule] = []
        self.load_rules()

    def load_rules(self) -> None:
        """Loads all replacement rules from the config path."""
        self.prompt_system_rules = self._load_rules_from_dir(
            os.path.join(self.config_path, "prompts", "system")
        )
        self.prompt_user_rules = self._load_rules_from_dir(
            os.path.join(self.config_path, "prompts", "user")
        )
        self.reply_rules = self._load_rules_from_dir(
            os.path.join(self.config_path, "replies")
        )

    def _load_rules_from_dir(self, directory: str) -> list[ReplacementRule]:
        """Loads rules from a specific directory."""
        rules: list[ReplacementRule] = []
        if not os.path.isdir(directory):
            return rules

        for subdir in sorted(os.listdir(directory)):
            subdir_path = os.path.join(directory, subdir)
            if not os.path.isdir(subdir_path):
                continue

            search_file = os.path.join(subdir_path, "SEARCH.txt")
            replace_file = os.path.join(subdir_path, "REPLACE.txt")
            prepend_file = os.path.join(subdir_path, "PREPEND.txt")
            append_file = os.path.join(subdir_path, "APPEND.txt")

            mode_files = {
                "REPLACE.txt": replace_file,
                "PREPEND.txt": prepend_file,
                "APPEND.txt": append_file,
            }

            found_modes = [
                mode for mode, path in mode_files.items() if os.path.exists(path)
            ]

            if len(found_modes) > 1:
                logger.warning(
                    f"Multiple replacement mode files found in {subdir_path}. "
                    f"Skipping this rule."
                )
                continue

            if not found_modes:
                continue

            mode_file_name = found_modes[0]
            mode_file_path = mode_files[mode_file_name]

            if not os.path.exists(search_file):
                logger.warning(
                    "Missing SEARCH.txt for replacement rule in %s. Skipping this rule.",
                    subdir_path,
                )
                continue

            with open(search_file, encoding="utf-8") as f:
                search_text = f.read()

            if len(search_text) < 8:
                logger.warning(
                    f"Search pattern in {search_file} is too short. "
                    f"Skipping this rule."
                )
                continue

            with open(mode_file_path, encoding="utf-8") as f:
                action_text = f.read()

            if not search_text:
                continue

            if mode_file_name == "REPLACE.txt":
                rules.append(
                    ReplacementRule(
                        mode=ReplacementMode.REPLACE,
                        search=search_text,
                        replace=action_text,
                    )
                )
            elif mode_file_name == "PREPEND.txt":
                rules.append(
                    ReplacementRule(
                        mode=ReplacementMode.PREPEND,
                        search=search_text,
                        prepend=action_text,
                    )
                )
            elif mode_file_name == "APPEND.txt":
                rules.append(
                    ReplacementRule(
                        mode=ReplacementMode.APPEND,
                        search=search_text,
                        append=action_text,
                    )
                )

        return rules

    def _apply_rules(self, content: str, rules: list[ReplacementRule]) -> str:
        """Applies a list of replacement rules to a string."""
        for rule in rules:
            if rule.mode == ReplacementMode.REPLACE:
                if rule.search and rule.replace is not None:
                    content = content.replace(rule.search, rule.replace)
            elif (
                rule.mode == ReplacementMode.PREPEND
                and rule.search
                and rule.prepend is not None
            ):
                content = content.replace(rule.search, rule.prepend + rule.search)
            elif (
                rule.mode == ReplacementMode.APPEND
                and rule.search
                and rule.append is not None
            ):
                content = content.replace(rule.search, rule.search + rule.append)
        return content

    def rewrite_prompt(self, prompt: str, prompt_type: str) -> str:
        """Rewrites a prompt based on its type."""
        if prompt_type == "system":
            rules = self.prompt_system_rules
        elif prompt_type == "user":
            rules = self.prompt_user_rules
        else:
            return prompt

        return self._apply_rules(prompt, rules)

    def rewrite_reply(self, reply: str) -> str:
        """Rewrites a reply from the LLM."""
        return self._apply_rules(reply, self.reply_rules)
