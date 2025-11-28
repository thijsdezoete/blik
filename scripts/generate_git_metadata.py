#!/usr/bin/env python3
"""
Generate git metadata JSON for landing pages.

This script extracts git history metadata for all landing templates and saves
it to a JSON file. The file is generated during Docker build (where git is
available) and read at runtime (where git may not be available).

Usage:
    python scripts/generate_git_metadata.py

Output:
    Creates landing/git_metadata_cache.json with structure:
    {
        "generated_at": "2025-01-15T10:30:00+00:00",
        "templates": {
            "landing/index.html": {
                "last_modified_iso": "2025-01-10T14:30:00+01:00",
                "primary_author": "Thijs de Zoete",
                "authors": ["Thijs de Zoete", "Claude"],
                "version_hash": "abc1234",
                "commit_count": 42
            },
            ...
        },
        "repository": {
            "total_commits": 500,
            "first_commit_date": "2024-06-01T00:00:00+00:00",
            "contributors": ["Thijs de Zoete", "Claude"],
            "last_updated": "2025-01-15T10:30:00+00:00"
        }
    }
"""
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def get_file_git_metadata(file_path, base_dir):
    """Extract git metadata for a specific file."""
    try:
        relative_path = file_path.relative_to(base_dir)
    except ValueError:
        return None

    if not file_path.exists():
        return None

    try:
        # Get last commit date
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%cI', '--', str(relative_path)],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0 or not result.stdout.strip():
            return None

        last_modified_iso = result.stdout.strip()

        # Get all authors
        result = subprocess.run(
            ['git', 'log', '--format=%an', '--', str(relative_path)],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5
        )

        authors = []
        primary_author = None
        if result.returncode == 0:
            authors = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if authors:
                author_counts = Counter(authors)
                primary_author = author_counts.most_common(1)[0][0]
                authors = list(set(authors))

        # Get short git SHA
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%h', '--', str(relative_path)],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        version_hash = result.stdout.strip() if result.returncode == 0 else None

        # Get commit count
        result = subprocess.run(
            ['git', 'rev-list', '--count', 'HEAD', '--', str(relative_path)],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        commit_count = int(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else 0

        return {
            'last_modified_iso': last_modified_iso,
            'primary_author': primary_author,
            'authors': authors,
            'version_hash': version_hash,
            'commit_count': commit_count,
        }

    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        print(f"  Warning: Could not get metadata for {relative_path}: {e}", file=sys.stderr)
        return None


def get_repository_metadata(base_dir):
    """Get metadata about the git repository itself."""
    try:
        # Total commits
        result = subprocess.run(
            ['git', 'rev-list', '--count', 'HEAD'],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        total_commits = int(result.stdout.strip()) if result.returncode == 0 else 0

        # First commit date
        result = subprocess.run(
            ['git', 'log', '--reverse', '--format=%cI', '--max-count=1'],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        first_commit_date = result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None

        # All contributors
        result = subprocess.run(
            ['git', 'log', '--format=%an'],
            cwd=base_dir,
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
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        last_updated = result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None

        return {
            'total_commits': total_commits,
            'first_commit_date': first_commit_date,
            'contributors': contributors,
            'last_updated': last_updated,
        }

    except Exception as e:
        print(f"Warning: Could not get repository metadata: {e}", file=sys.stderr)
        return {
            'total_commits': 0,
            'first_commit_date': None,
            'contributors': [],
            'last_updated': None,
        }


def main():
    # Determine base directory (project root)
    script_dir = Path(__file__).parent
    base_dir = script_dir.parent

    # Find all landing templates
    templates_dir = base_dir / 'templates' / 'landing'
    if not templates_dir.exists():
        print(f"Error: Templates directory not found: {templates_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Generating git metadata from: {base_dir}")
    print(f"Scanning templates in: {templates_dir}")

    # Collect metadata for all templates
    templates_metadata = {}

    # Find all HTML templates in landing directory (including subdirectories)
    template_files = list(templates_dir.rglob('*.html'))
    print(f"Found {len(template_files)} template files")

    for template_path in sorted(template_files):
        # Create template name relative to templates directory
        template_name = str(template_path.relative_to(base_dir / 'templates'))

        metadata = get_file_git_metadata(template_path, base_dir)
        if metadata:
            templates_metadata[template_name] = metadata
            print(f"  {template_name}: {metadata['last_modified_iso'][:10]}")
        else:
            print(f"  {template_name}: (no git history)")

    # Get repository metadata
    print("\nExtracting repository metadata...")
    repo_metadata = get_repository_metadata(base_dir)
    print(f"  Total commits: {repo_metadata['total_commits']}")
    print(f"  Contributors: {len(repo_metadata['contributors'])}")

    # Build output structure
    output = {
        'generated_at': datetime.now().astimezone().isoformat(),
        'templates': templates_metadata,
        'repository': repo_metadata,
    }

    # Write to JSON file
    output_path = base_dir / 'landing' / 'git_metadata_cache.json'
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nGenerated: {output_path}")
    print(f"Templates with metadata: {len(templates_metadata)}")


if __name__ == '__main__':
    main()
