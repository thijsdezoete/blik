from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Fix PostgreSQL sequences after loading fixtures'

    def handle(self, *args, **options):
        """
        Reset all PostgreSQL sequences to the correct values.
        This is needed after loading fixtures with hardcoded primary keys.
        """
        tables_to_fix = [
            'organizations',
            'questionnaires',
            'question_sections',
            'questions',
            'subscriptions_plan',
            'subscriptions_subscription',
            'accounts_userprofile',
            'accounts_organizationinvitation',
            'accounts_reviewee',
            'reviews_reviewcycle',
            'reviews_reviewertoken',
            'reviews_response',
            'reports_report',
        ]

        fixed_count = 0
        with connection.cursor() as cursor:
            for table in tables_to_fix:
                try:
                    # PostgreSQL sequence naming convention: {table}_id_seq
                    sequence_name = f"{table}_id_seq"

                    # Set sequence to MAX(id) + 1, or 1 if table is empty
                    sql = f"""
                        SELECT setval(
                            '{sequence_name}',
                            COALESCE((SELECT MAX(id) FROM {table}), 0) + 1,
                            false
                        );
                    """
                    cursor.execute(sql)
                    result = cursor.fetchone()[0]

                    self.stdout.write(
                        self.style.SUCCESS(f'✓ Fixed {table} sequence -> next ID: {result}')
                    )
                    fixed_count += 1

                except Exception as e:
                    # Skip tables that don't exist or don't have sequences
                    self.stdout.write(
                        self.style.WARNING(f'⊘ Skipped {table}: {str(e)}')
                    )

        self.stdout.write(
            self.style.SUCCESS(f'\n✓ Successfully fixed {fixed_count} sequences!')
        )
