"""
Git-based metadata extraction for landing pages.

Provides timestamps, authors, and versioning information by reading git history
without requiring a database. Designed for AI search optimization and SEO.

Key features:
- Last modified dates from git commits
- Author attribution from git history
- Content versioning via git SHA
- Build-time caching for performance
"""
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from functools import lru_cache
from django.conf import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=128)
def get_file_git_metadata(file_path):
    """
    Extract git metadata for a specific file.

    Args:
        file_path: Absolute or relative path to file

    Returns:
        dict with keys:
            - last_modified: datetime of last commit
            - last_modified_iso: ISO 8601 string
            - authors: list of contributor names
            - primary_author: most frequent contributor
            - version_hash: short git SHA
            - commit_count: number of commits touching this file
    """
    try:
        # Resolve to absolute path
        if not Path(file_path).is_absolute():
            file_path = Path(settings.BASE_DIR) / file_path

        # Check if file exists
        if not Path(file_path).exists():
            logger.debug(f"File not found for git metadata: {file_path}")
            return _get_default_metadata()

        # Make path relative to BASE_DIR for git commands
        try:
            relative_path = Path(file_path).relative_to(settings.BASE_DIR)
        except ValueError:
            # File is outside BASE_DIR
            logger.warning(f"File outside BASE_DIR: {file_path}")
            return _get_default_metadata()

        # Get last commit date (ISO 8601 format)
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%cI', '--', str(relative_path)],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0 or not result.stdout.strip():
            logger.debug(f"No git history for file: {relative_path}")
            return _get_default_metadata()

        last_modified_iso = result.stdout.strip()
        last_modified = datetime.fromisoformat(last_modified_iso.replace('Z', '+00:00'))

        # Get all authors who touched this file
        result = subprocess.run(
            ['git', 'log', '--format=%an', '--', str(relative_path)],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5
        )

        authors = []
        if result.returncode == 0:
            authors = [line.strip() for line in result.stdout.splitlines() if line.strip()]

        # Determine primary author (most commits)
        primary_author = None
        if authors:
            from collections import Counter
            author_counts = Counter(authors)
            primary_author = author_counts.most_common(1)[0][0]

        # Get short git SHA of last commit
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%h', '--', str(relative_path)],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5
        )

        version_hash = result.stdout.strip() if result.returncode == 0 else None

        # Get total commit count for this file
        result = subprocess.run(
            ['git', 'rev-list', '--count', 'HEAD', '--', str(relative_path)],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5
        )

        commit_count = int(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else 0

        return {
            'last_modified': last_modified,
            'last_modified_iso': last_modified_iso,
            'authors': list(set(authors)),  # unique authors
            'primary_author': primary_author,
            'version_hash': version_hash,
            'commit_count': commit_count,
        }

    except subprocess.TimeoutExpired:
        logger.warning(f"Git command timeout for file: {file_path}")
        return _get_default_metadata()
    except Exception as e:
        logger.exception(f"Error extracting git metadata for {file_path}: {e}")
        return _get_default_metadata()


@lru_cache(maxsize=32)
def get_template_metadata(template_name):
    """
    Get git metadata for a Django template by name.

    Args:
        template_name: Template name like 'landing/dreyfus_model.html'

    Returns:
        dict with git metadata (see get_file_git_metadata)
    """
    # Resolve template to file path
    template_path = Path(settings.BASE_DIR) / 'templates' / template_name
    return get_file_git_metadata(str(template_path))


@lru_cache(maxsize=32)
def get_view_metadata(view_module, view_name):
    """
    Get git metadata for a view function by module and name.

    Args:
        view_module: Module name like 'landing.views'
        view_name: Function name like 'dreyfus_model'

    Returns:
        dict with git metadata
    """
    # Convert module path to file path
    module_parts = view_module.split('.')
    view_file = Path(settings.BASE_DIR) / '/'.join(module_parts) + '.py'
    return get_file_git_metadata(str(view_file))


def _get_default_metadata():
    """
    Return default metadata when git info is unavailable.
    Uses current date and generic attribution.
    """
    now = datetime.now()
    return {
        'last_modified': now,
        'last_modified_iso': now.isoformat(),
        'authors': [],
        'primary_author': None,
        'version_hash': None,
        'commit_count': 0,
    }


@lru_cache(maxsize=1)
def get_repository_metadata():
    """
    Get metadata about the git repository itself.

    Returns:
        dict with keys:
            - total_commits: total commit count
            - first_commit_date: date of first commit
            - contributors: list of all unique contributors
            - last_updated: date of most recent commit
    """
    try:
        # Total commits
        result = subprocess.run(
            ['git', 'rev-list', '--count', 'HEAD'],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5
        )
        total_commits = int(result.stdout.strip()) if result.returncode == 0 else 0

        # First commit date
        result = subprocess.run(
            ['git', 'log', '--reverse', '--format=%cI', '--max-count=1'],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5
        )
        first_commit_date = None
        if result.returncode == 0 and result.stdout.strip():
            first_commit_date = datetime.fromisoformat(result.stdout.strip().replace('Z', '+00:00'))

        # All contributors
        result = subprocess.run(
            ['git', 'log', '--format=%an'],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=10
        )
        contributors = []
        if result.returncode == 0:
            contributors = list(set(line.strip() for line in result.stdout.splitlines() if line.strip()))

        # Most recent commit date
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%cI'],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5
        )
        last_updated = None
        if result.returncode == 0 and result.stdout.strip():
            last_updated = datetime.fromisoformat(result.stdout.strip().replace('Z', '+00:00'))

        return {
            'total_commits': total_commits,
            'first_commit_date': first_commit_date,
            'contributors': contributors,
            'last_updated': last_updated,
        }

    except Exception as e:
        logger.exception(f"Error extracting repository metadata: {e}")
        return {
            'total_commits': 0,
            'first_commit_date': None,
            'contributors': [],
            'last_updated': None,
        }


def clear_cache():
    """Clear all cached git metadata. Useful after git operations."""
    get_file_git_metadata.cache_clear()
    get_template_metadata.cache_clear()
    get_view_metadata.cache_clear()
    get_repository_metadata.cache_clear()
