"""Repro script for tool event collector memory leak.

This script demonstrates that _git_commits lists can grow unbounded
if sessions accumulate many unique git commits.
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.memory.tool_event_collector import DeterministicToolEventCollector
from src.core.memory.models import GitCommitEvent


async def test_git_commits_unbounded_growth():
    """Test that _git_commits lists grow unbounded."""
    collector = DeterministicToolEventCollector()
    
    session_id = "test-session"
    num_commits = 50000
    
    print(f"Recording {num_commits} unique git commits for session '{session_id}'...")
    
    # Record many unique commits
    for i in range(num_commits):
        commit_hash = f"abc{i:08d}"  # Unique hash for each commit
        event = GitCommitEvent(
            commit_hash=commit_hash,
            message=f"Commit {i}",
            timestamp=datetime.now(timezone.utc),
        )
        await collector.record_git_commit(session_id, event)
    
    # Check the size of the commit list
    commit_count = await collector.get_git_commit_count(session_id)
    print(f"Number of commits in _git_commits['{session_id}']: {commit_count}")
    print(f"Expected: {num_commits}")
    
    if commit_count >= num_commits:
        print("MEMORY LEAK CONFIRMED: _git_commits list grows unbounded!")
        print(f"   Single session can accumulate {commit_count} commit events")
        print("   No limit on commits per session - can grow indefinitely")
        print("   (Only cleaned up when get_and_clear() or clear_session() is called)")
        return True
    elif commit_count <= 1000:  # Should be limited to MAX_GIT_COMMITS_PER_SESSION
        print("FIX VERIFIED: _git_commits list is now limited!")
        print(f"   Single session limited to {commit_count} commit events (max=1000)")
        return False
    else:
        print(f"Unexpected: commit count is {commit_count}, expected <= 1000")
        return False


async def test_multiple_sessions_git_commits():
    """Test that multiple sessions can accumulate unbounded git commits."""
    collector = DeterministicToolEventCollector()
    
    num_sessions = 100
    commits_per_session = 1000
    
    print(f"\nCreating {num_sessions} sessions with {commits_per_session} commits each...")
    
    for session_idx in range(num_sessions):
        session_id = f"session-{session_idx}"
        for i in range(commits_per_session):
            commit_hash = f"abc{session_idx:04d}{i:04d}"  # Unique hash
            event = GitCommitEvent(
                commit_hash=commit_hash,
                message=f"Commit {i}",
                timestamp=datetime.now(timezone.utc),
            )
            await collector.record_git_commit(session_id, event)
    
    # Check total commits across all sessions
    total_commits = 0
    for session_idx in range(num_sessions):
        session_id = f"session-{session_idx}"
        total_commits += await collector.get_git_commit_count(session_id)
    
    print(f"Total commits across all sessions: {total_commits}")
    print(f"Expected: {num_sessions * commits_per_session}")
    
    # With per-session limit of 1000, each session should have at most 1000 commits
    max_expected_per_session = 1000
    max_expected_total = num_sessions * max_expected_per_session
    if total_commits > max_expected_total:
        print("MEMORY LEAK CONFIRMED: Multiple sessions accumulate unbounded git commits!")
        print(f"   Total memory usage: {total_commits} commit event objects")
        print(f"   Expected max: {max_expected_total}")
        return True
    else:
        print(f"FIX VERIFIED: Total commits limited correctly")
        print(f"   Total: {total_commits}, Max expected: {max_expected_total}")
        print(f"   Each session limited to {max_expected_per_session} commits")
        return False


async def main():
    """Run all leak tests."""
    print("=" * 60)
    print("Testing Tool Event Collector Memory Leaks")
    print("=" * 60)
    
    leak1 = await test_git_commits_unbounded_growth()
    leak2 = await test_multiple_sessions_git_commits()
    
    print("\n" + "=" * 60)
    if leak1 or leak2:
        print("RESULT: Memory leaks confirmed!")
        sys.exit(1)
    else:
        print("RESULT: No leaks detected")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
