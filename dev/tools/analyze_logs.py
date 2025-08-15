#!/usr/bin/env python
"""
Analyze proxy logs to extract useful metrics and information.

This script provides tools for analyzing logs from the LLM Interactive Proxy.
It can extract metrics such as request counts, response times, error rates, etc.
"""

import argparse
import datetime
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def setup_logging() -> logging.Logger:
    """Set up logging.
    
    Returns:
        A configured logger
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("log_analyzer")


class LogAnalyzer:
    """Analyzer for proxy logs."""
    
    def __init__(self):
        """Initialize the analyzer."""
        self.logger = setup_logging()
        self.requests = []
        self.errors = []
        self.response_times = []
        self.usage_metrics = []
        self.sessions = set()
        self.backends = Counter()
        self.models = Counter()
        self.errors_by_type = Counter()
        self.request_timeline = defaultdict(int)
    
    def process_line(self, line: str) -> None:
        """Process a log line.
        
        Args:
            line: The log line to process
        """
        line = line.strip()
        
        try:
            # Try to parse as JSON
            if line.startswith("{") and line.endswith("}"):
                try:
                    log_entry = json.loads(line)
                    self._process_json_log(log_entry)
                    return
                except json.JSONDecodeError:
                    pass
            
            # Try to parse plain text log
            self._process_text_log(line)
            
        except Exception as e:
            self.logger.debug(f"Error processing line: {str(e)}")
    
    def _process_json_log(self, log_entry: Dict[str, Any]) -> None:
        """Process a JSON log entry.
        
        Args:
            log_entry: The JSON log entry
        """
        # Extract event information
        event = log_entry.get("event", "")
        level = log_entry.get("level", "").lower()
        timestamp = log_entry.get("timestamp")
        
        # Handle different events
        if "request received" in event.lower():
            self.requests.append(log_entry)
            if timestamp:
                # Convert timestamp to date
                date_str = timestamp.split("T")[0]
                self.request_timeline[date_str] += 1
            
            # Extract session information
            session_id = log_entry.get("session_id")
            if session_id:
                self.sessions.add(session_id)
                
        elif "response sent" in event.lower():
            # Extract response time
            duration_ms = log_entry.get("duration_ms")
            if duration_ms is not None:
                self.response_times.append(duration_ms)
                
        elif "usage" in log_entry:
            # Extract usage metrics
            usage = log_entry.get("usage")
            if usage and isinstance(usage, dict):
                self.usage_metrics.append(usage)
                
        elif level in ["error", "warning"]:
            self.errors.append(log_entry)
            error_type = log_entry.get("error_type", "unknown")
            self.errors_by_type[error_type] += 1
            
        # Extract backend and model information
        backend = log_entry.get("backend")
        if backend:
            self.backends[backend] += 1
            
        model = log_entry.get("model")
        if model:
            self.models[model] += 1
    
    def _process_text_log(self, line: str) -> None:
        """Process a text log line.
        
        Args:
            line: The log line
        """
        # Extract common patterns
        
        # Request pattern
        request_match = re.search(r"Request received.*url=([^\s,]+)", line)
        if request_match:
            self.requests.append({"url": request_match.group(1)})
            
            # Extract timestamp
            timestamp_match = re.search(r"(\d{4}-\d{2}-\d{2})", line)
            if timestamp_match:
                date_str = timestamp_match.group(1)
                self.request_timeline[date_str] += 1
                
            # Extract session information
            session_match = re.search(r"session[_-]id[=:]\s*([a-zA-Z0-9-]+)", line, re.IGNORECASE)
            if session_match:
                session_id = session_match.group(1)
                self.sessions.add(session_id)
            
            return
            
        # Response time pattern
        response_time_match = re.search(r"Response .*?(\d+(?:\.\d+)?)ms", line)
        if response_time_match:
            try:
                duration = float(response_time_match.group(1))
                self.response_times.append(duration)
            except ValueError:
                pass
            return
            
        # Error pattern
        error_match = re.search(r"ERROR.*?(?:Exception|Error):\s*(.*?)(?:\s*at|\s*$)", line)
        if error_match:
            error_msg = error_match.group(1)
            self.errors.append({"message": error_msg})
            
            # Extract error type
            error_type_match = re.search(r"([A-Za-z]+(?:Exception|Error))", error_msg)
            if error_type_match:
                error_type = error_type_match.group(1)
                self.errors_by_type[error_type] += 1
            else:
                self.errors_by_type["Unknown"] += 1
            return
            
        # Backend/model pattern
        backend_match = re.search(r"backend[=:]\s*([a-zA-Z0-9_-]+)", line, re.IGNORECASE)
        if backend_match:
            backend = backend_match.group(1)
            self.backends[backend] += 1
            
        model_match = re.search(r"model[=:]\s*([a-zA-Z0-9_-]+)", line, re.IGNORECASE)
        if model_match:
            model = model_match.group(1)
            self.models[model] += 1
    
    def process_file(self, file_path: Path) -> None:
        """Process a log file.
        
        Args:
            file_path: Path to the log file
        """
        self.logger.info(f"Processing log file: {file_path}")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    self.process_line(line)
        except Exception as e:
            self.logger.error(f"Error processing file {file_path}: {str(e)}")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the analyzed logs.
        
        Returns:
            A dictionary with analysis results
        """
        # Calculate metrics
        total_requests = len(self.requests)
        total_errors = len(self.errors)
        error_rate = (total_errors / total_requests) * 100 if total_requests > 0 else 0
        
        # Calculate response time statistics
        if self.response_times:
            avg_response_time = sum(self.response_times) / len(self.response_times)
            min_response_time = min(self.response_times)
            max_response_time = max(self.response_times)
            # Calculate p95 response time
            sorted_times = sorted(self.response_times)
            p95_idx = int(len(sorted_times) * 0.95)
            p95_response_time = sorted_times[p95_idx]
        else:
            avg_response_time = 0
            min_response_time = 0
            max_response_time = 0
            p95_response_time = 0
        
        # Calculate token usage
        total_tokens = 0
        prompt_tokens = 0
        completion_tokens = 0
        for usage in self.usage_metrics:
            total_tokens += usage.get("total_tokens", 0)
            prompt_tokens += usage.get("prompt_tokens", 0)
            completion_tokens += usage.get("completion_tokens", 0)
        
        return {
            "total_requests": total_requests,
            "unique_sessions": len(self.sessions),
            "total_errors": total_errors,
            "error_rate": f"{error_rate:.2f}%",
            "response_time": {
                "average": f"{avg_response_time:.2f}ms",
                "min": f"{min_response_time:.2f}ms",
                "max": f"{max_response_time:.2f}ms",
                "p95": f"{p95_response_time:.2f}ms",
            },
            "token_usage": {
                "total": total_tokens,
                "prompt": prompt_tokens,
                "completion": completion_tokens,
            },
            "backends": dict(self.backends),
            "models": dict(self.models),
            "errors_by_type": dict(self.errors_by_type),
            "request_timeline": dict(sorted(self.request_timeline.items())),
        }
        
    def print_summary(self) -> None:
        """Print a summary of the analyzed logs."""
        summary = self.get_summary()
        
        print("\n===== LOG ANALYSIS SUMMARY =====\n")
        print(f"Total Requests: {summary['total_requests']}")
        print(f"Unique Sessions: {summary['unique_sessions']}")
        print(f"Total Errors: {summary['total_errors']}")
        print(f"Error Rate: {summary['error_rate']}")
        
        print("\nResponse Time:")
        print(f"  Average: {summary['response_time']['average']}")
        print(f"  Min: {summary['response_time']['min']}")
        print(f"  Max: {summary['response_time']['max']}")
        print(f"  P95: {summary['response_time']['p95']}")
        
        print("\nToken Usage:")
        print(f"  Total: {summary['token_usage']['total']}")
        print(f"  Prompt: {summary['token_usage']['prompt']}")
        print(f"  Completion: {summary['token_usage']['completion']}")
        
        print("\nBackends:")
        for backend, count in summary["backends"].items():
            print(f"  {backend}: {count}")
            
        print("\nModels:")
        for model, count in summary["models"].items():
            print(f"  {model}: {count}")
            
        print("\nErrors by Type:")
        for error_type, count in summary["errors_by_type"].items():
            print(f"  {error_type}: {count}")
            
        print("\nRequest Timeline:")
        for date, count in summary["request_timeline"].items():
            print(f"  {date}: {count}")
            
        print("\n================================\n")
    
    def export_summary(self, output_file: Path) -> None:
        """Export the summary to a JSON file.
        
        Args:
            output_file: Path to the output file
        """
        summary = self.get_summary()
        
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
                
            self.logger.info(f"Summary exported to {output_file}")
        except Exception as e:
            self.logger.error(f"Error exporting summary: {str(e)}")


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point.
    
    Args:
        args: Command line arguments
        
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    logger = setup_logging()
    
    parser = argparse.ArgumentParser(description="Analyze proxy logs")
    
    parser.add_argument(
        "log_files",
        nargs="+",
        help="Log files to analyze",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file for summary (JSON format)",
    )
    
    # Parse arguments
    parsed_args = parser.parse_args(args)
    
    # Create analyzer
    analyzer = LogAnalyzer()
    
    # Process each file
    for file_path in parsed_args.log_files:
        path = Path(file_path)
        if not path.exists():
            logger.error(f"File not found: {file_path}")
            continue
            
        analyzer.process_file(path)
    
    # Print summary
    analyzer.print_summary()
    
    # Export summary if requested
    if parsed_args.output:
        analyzer.export_summary(Path(parsed_args.output))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
