import json
import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import pytz

logger = logging.getLogger(__name__)


class DailyRequestCounter:
    def __init__(self, persistence_path: Path, limit: int) -> None:
        self.persistence_path = persistence_path
        self.limit = limit
        self.count = 0
        self._thresholds = self._calculate_thresholds()
        self._logged_thresholds: set[int] = set()
        self.last_reset_date = self._get_current_pacific_date()
        self._load_state()
        self._reset_if_needed()

    @property
    def logged_thresholds(self) -> set[int]:
        """Return a copy of the thresholds that have already triggered warnings."""
        return set(self._logged_thresholds)

    def _calculate_thresholds(self) -> tuple[int, ...]:
        raw_thresholds: Iterable[int] = (
            int(self.limit * percentage) for percentage in (0.7, 0.8, 0.9)
        )
        filtered = {
            threshold for threshold in raw_thresholds if 0 < threshold <= self.limit
        }
        return tuple(sorted(filtered))

    def _get_current_pacific_date(self) -> str:
        pacific_tz = pytz.timezone("America/Los_Angeles")
        return datetime.now(pacific_tz).strftime("%Y-%m-%d")

    def _load_state(self) -> None:
        if not self.persistence_path.exists():
            return
        try:
            with open(self.persistence_path, encoding="utf-8") as f:
                data = json.load(f)
                self.count = data.get("count", 0)
                self.last_reset_date = data.get(
                    "last_reset_date", self._get_current_pacific_date()
                )
                logged_thresholds = data.get("logged_thresholds", [])
                self._logged_thresholds = {
                    int(threshold) for threshold in logged_thresholds
                } & set(self._thresholds)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load request counter state: {e}", exc_info=True)

    def _save_state(self) -> None:
        try:
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create persistence directory: {e}", exc_info=True)
            return

        try:
            with open(self.persistence_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "count": self.count,
                        "last_reset_date": self.last_reset_date,
                        "logged_thresholds": sorted(self._logged_thresholds),
                    },
                    f,
                    indent=2,
                )
        except OSError as e:
            logger.error(f"Failed to save request counter state: {e}", exc_info=True)

    def _reset_if_needed(self) -> None:
        current_date = self._get_current_pacific_date()
        if self.last_reset_date != current_date:
            self.count = 0
            self.last_reset_date = current_date
            self._logged_thresholds.clear()
            logger.info("Daily request counter has been reset.")
            self._save_state()

    def increment(self) -> None:
        self._reset_if_needed()
        self.count += 1
        self._check_thresholds()
        self._save_state()

    def _check_thresholds(self) -> None:
        for threshold in self._thresholds:
            if self.count == threshold and threshold not in self._logged_thresholds:
                self._logged_thresholds.add(threshold)
                logger.warning(
                    f"Gemini CLI OAuth personal daily usage reached {threshold}"
                    f" requests ({self.count}/{self.limit})."
                )
