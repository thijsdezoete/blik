"""The test runner (TEST_RUNNER): Django's, with workers of a parallel run that start like a serial run."""
from importlib import import_module

import django
from django.conf import settings
from django.test.runner import DiscoverRunner, ParallelTestSuite


def import_urls():
    """
    Import the URL configuration, and with it the views and all they use, before a worker runs its first test.

    A serial run does this in its system check. A worker that starts as a new process (macOS, Windows) imports
    a module only when a test needs it. When that happens while a test has a function mocked, such as
    core.email.send_email, a module that imports the function by name keeps the mock, and tests that run later
    in that worker fail.
    """
    django.setup()
    import_module(settings.ROOT_URLCONF)


class ParallelSuite(ParallelTestSuite):
    process_setup = import_urls


class Runner(DiscoverRunner):
    parallel_test_suite = ParallelSuite
