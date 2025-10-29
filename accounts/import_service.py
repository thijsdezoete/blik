"""
Import Service for Blik Organization Data

This module provides functionality to import previously exported organization data,
enabling backup restoration, data migration, and organization cloning.
"""

import json
import secrets
import string
from datetime import datetime
from django.db import transaction
from django.contrib.auth.models import User, Permission
from django.core.exceptions import ValidationError
from django.utils import timezone


def validate_import_data(data):
    """
    Validate the structure and content of import data.

    Args:
        data: Parsed JSON data from import file

    Returns:
        dict: {
            'valid': bool,
            'errors': list of error messages,
            'warnings': list of warning messages
        }
    """
    errors = []
    warnings = []

    # Check top-level structure
    if not isinstance(data, dict):
        errors.append("Import data must be a JSON object")
        return {'valid': False, 'errors': errors, 'warnings': warnings}

    # Required top-level keys
    required_keys = ['organization']
    for key in required_keys:
        if key not in data:
            errors.append(f"Missing required top-level key: '{key}'")

    # Validate organization structure
    if 'organization' in data:
        org_data = data['organization']
        if not isinstance(org_data, dict):
            errors.append("'organization' must be an object")
        else:
            if 'name' not in org_data:
                errors.append("Organization missing required field: 'name'")
            if 'email' not in org_data:
                warnings.append("Organization missing 'email' field")

    # Validate users structure
    if 'users' in data:
        if not isinstance(data['users'], list):
            errors.append("'users' must be an array")
        else:
            for idx, user in enumerate(data['users']):
                if not isinstance(user, dict):
                    errors.append(f"User at index {idx} must be an object")
                    continue

                required_user_fields = ['username', 'email']
                for field in required_user_fields:
                    if field not in user:
                        errors.append(f"User at index {idx} missing required field: '{field}'")

    # Validate reviewees structure
    if 'reviewees' in data:
        if not isinstance(data['reviewees'], list):
            errors.append("'reviewees' must be an array")
        else:
            for idx, reviewee in enumerate(data['reviewees']):
                if not isinstance(reviewee, dict):
                    errors.append(f"Reviewee at index {idx} must be an object")
                    continue

                required_fields = ['name', 'email']
                for field in required_fields:
                    if field not in reviewee:
                        errors.append(f"Reviewee at index {idx} missing required field: '{field}'")

    # Validate questionnaires structure
    if 'questionnaires' in data:
        if not isinstance(data['questionnaires'], list):
            errors.append("'questionnaires' must be an array")
        else:
            for idx, questionnaire in enumerate(data['questionnaires']):
                if not isinstance(questionnaire, dict):
                    errors.append(f"Questionnaire at index {idx} must be an object")
                    continue

                if 'name' not in questionnaire:
                    errors.append(f"Questionnaire at index {idx} missing 'name'")

                if 'sections' not in questionnaire:
                    warnings.append(f"Questionnaire at index {idx} missing 'sections' (empty questionnaire)")
                elif not isinstance(questionnaire['sections'], list):
                    errors.append(f"Questionnaire at index {idx} 'sections' must be an array")
                else:
                    # Validate sections
                    for s_idx, section in enumerate(questionnaire['sections']):
                        if 'title' not in section:
                            errors.append(f"Questionnaire {idx} section {s_idx} missing 'title'")
                        if 'questions' in section and not isinstance(section['questions'], list):
                            errors.append(f"Questionnaire {idx} section {s_idx} 'questions' must be an array")

    # Validate review_cycles structure
    if 'review_cycles' in data:
        if not isinstance(data['review_cycles'], list):
            errors.append("'review_cycles' must be an array")
        else:
            for idx, cycle in enumerate(data['review_cycles']):
                if not isinstance(cycle, dict):
                    errors.append(f"Review cycle at index {idx} must be an object")
                    continue

                required_fields = ['reviewee', 'questionnaire', 'status']
                for field in required_fields:
                    if field not in cycle:
                        errors.append(f"Review cycle at index {idx} missing '{field}'")

    # Validate reports structure
    if 'reports' in data:
        if not isinstance(data['reports'], list):
            errors.append("'reports' must be an array")
        else:
            for idx, report in enumerate(data['reports']):
                if not isinstance(report, dict):
                    errors.append(f"Report at index {idx} must be an object")
                    continue

                if 'reviewee' not in report:
                    errors.append(f"Report at index {idx} missing 'reviewee'")
                if 'report_data' not in report:
                    warnings.append(f"Report at index {idx} missing 'report_data' (empty report)")

    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings,
    }


def generate_import_preview(data):
    """
    Generate a preview summary of what will be imported.

    Args:
        data: Parsed JSON data from import file

    Returns:
        dict: Preview information for display to user
    """
    preview = {
        'organization_name': data.get('organization', {}).get('name', 'Unknown'),
        'organization_email': data.get('organization', {}).get('email', 'Not specified'),
        'counts': {
            'users': len(data.get('users', [])),
            'reviewees': len(data.get('reviewees', [])),
            'questionnaires': len(data.get('questionnaires', [])),
            'review_cycles': len(data.get('review_cycles', [])),
            'reports': len(data.get('reports', [])),
        },
        'questionnaire_details': [],
        'total_questions': 0,
    }

    # Add questionnaire details
    for q in data.get('questionnaires', []):
        sections_count = len(q.get('sections', []))
        questions_count = sum(
            len(s.get('questions', []))
            for s in q.get('sections', [])
        )

        preview['questionnaire_details'].append({
            'name': q.get('name', 'Unnamed'),
            'sections': sections_count,
            'questions': questions_count,
        })
        preview['total_questions'] += questions_count

    return preview


def import_reviewees(organization, reviewees_data, conflict_resolution='skip'):
    """
    Import reviewees into organization.

    Args:
        organization: Organization instance
        reviewees_data: List of reviewee dicts from export
        conflict_resolution: 'skip', 'overwrite', or 'duplicate'

    Returns:
        dict: Import result with counts and warnings
    """
    from accounts.models import Reviewee

    result = {
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'warnings': [],
        'errors': [],
    }

    for reviewee_data in reviewees_data:
        try:
            name = reviewee_data['name']
            email = reviewee_data['email']

            # Check if reviewee exists (match by email within organization)
            existing = Reviewee.objects.filter(
                organization=organization,
                email=email
            ).first()

            if existing:
                if conflict_resolution == 'skip':
                    result['skipped'] += 1
                    continue

                elif conflict_resolution == 'overwrite':
                    existing.name = name
                    existing.department = reviewee_data.get('department', '')
                    existing.is_active = reviewee_data.get('is_active', True)
                    existing.save()
                    result['updated'] += 1
                    continue

                elif conflict_resolution == 'duplicate':
                    # Create with modified email
                    original_email = email
                    email = f"imported_{email}"
                    result['warnings'].append(f"Created duplicate reviewee: {name} with email {email} (original: {original_email})")

            # Create new reviewee
            Reviewee.objects.create(
                organization=organization,
                name=name,
                email=email,
                department=reviewee_data.get('department', ''),
                is_active=reviewee_data.get('is_active', True),
            )
            result['created'] += 1

        except Exception as e:
            result['errors'].append(f"Failed to import reviewee {reviewee_data.get('email', 'unknown')}: {str(e)}")

    return result


def import_questionnaires(organization, questionnaires_data, conflict_resolution='skip'):
    """
    Import questionnaires with sections and questions.

    Args:
        organization: Organization instance
        questionnaires_data: List of questionnaire dicts from export
        conflict_resolution: 'skip', 'overwrite', or 'duplicate'

    Returns:
        dict: Import result with counts and warnings
    """
    from questionnaires.models import Questionnaire, QuestionSection, Question

    result = {
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'warnings': [],
        'errors': [],
        'questionnaire_map': {},  # name -> instance for later reference
    }

    for q_data in questionnaires_data:
        try:
            name = q_data['name']

            # Check if questionnaire exists
            existing = Questionnaire.objects.filter(
                organization=organization,
                name=name
            ).first()

            questionnaire_to_update = None

            if existing:
                if conflict_resolution == 'skip':
                    result['skipped'] += 1
                    result['questionnaire_map'][name] = existing
                    continue

                elif conflict_resolution == 'overwrite':
                    # Delete existing sections/questions and recreate
                    existing.sections.all().delete()
                    questionnaire_to_update = existing

                elif conflict_resolution == 'duplicate':
                    # Create with modified name
                    original_name = name
                    name = f"{name} (imported)"
                    result['warnings'].append(f"Created duplicate questionnaire: {name} (original: {original_name})")

            # Create or update questionnaire
            if questionnaire_to_update:
                questionnaire = questionnaire_to_update
                questionnaire.description = q_data.get('description', '')
                questionnaire.is_active = q_data.get('is_active', True)
                questionnaire.save()
                result['updated'] += 1
            else:
                questionnaire = Questionnaire.objects.create(
                    organization=organization,
                    name=name,
                    description=q_data.get('description', ''),
                    is_active=q_data.get('is_active', True),
                )
                result['created'] += 1

            # Store mapping
            result['questionnaire_map'][q_data['name']] = questionnaire

            # Import sections and questions
            for section_data in q_data.get('sections', []):
                section = QuestionSection.objects.create(
                    questionnaire=questionnaire,
                    title=section_data['title'],
                    description=section_data.get('description', ''),
                    order=section_data.get('order', 0),
                )

                # Import questions
                for question_data in section_data.get('questions', []):
                    Question.objects.create(
                        section=section,
                        question_text=question_data['question_text'],
                        question_type=question_data.get('question_type', 'text'),
                        config=question_data.get('config', {}),
                        required=question_data.get('required', False),
                        order=question_data.get('order', 0),
                    )

        except Exception as e:
            result['errors'].append(f"Failed to import questionnaire {q_data.get('name', 'unknown')}: {str(e)}")

    return result


def import_review_cycles(organization, cycles_data, questionnaire_map, conflict_resolution='skip'):
    """
    Import review cycles with tokens and responses.

    Args:
        organization: Organization instance
        cycles_data: List of cycle dicts from export
        questionnaire_map: Dict mapping questionnaire names to instances
        conflict_resolution: 'skip', 'overwrite', or 'duplicate'

    Returns:
        dict: Import result with counts and warnings
    """
    from reviews.models import ReviewCycle, ReviewerToken, Response
    from accounts.models import Reviewee
    from questionnaires.models import Questionnaire

    result = {
        'created': 0,
        'skipped': 0,
        'warnings': [],
        'errors': [],
        'imported_cycles': [],  # Track imported cycles for report attachment
    }

    for cycle_data in cycles_data:
        try:
            # Find referenced reviewee
            reviewee_name = cycle_data['reviewee']
            reviewee = Reviewee.objects.filter(
                organization=organization,
                name=reviewee_name
            ).first()

            if not reviewee:
                result['warnings'].append(f"Reviewee '{reviewee_name}' not found - skipping cycle")
                result['skipped'] += 1
                continue

            # Find referenced questionnaire
            questionnaire_name = cycle_data['questionnaire']
            questionnaire = questionnaire_map.get(questionnaire_name)

            if not questionnaire:
                # Try to find in database
                questionnaire = Questionnaire.objects.filter(
                    organization=organization,
                    name=questionnaire_name
                ).first()

            if not questionnaire:
                result['warnings'].append(f"Questionnaire '{questionnaire_name}' not found - skipping cycle")
                result['skipped'] += 1
                continue

            # Create cycle (always create new - don't try to match existing)
            cycle = ReviewCycle.objects.create(
                reviewee=reviewee,
                questionnaire=questionnaire,
                status=cycle_data.get('status', 'active'),
            )

            # Import tokens
            for token_data in cycle_data.get('tokens', []):
                invitation_sent_at = token_data.get('invitation_sent_at')
                completed_at = token_data.get('completed_at')

                # Parse timestamps if they're strings
                if invitation_sent_at and isinstance(invitation_sent_at, str):
                    invitation_sent_at = timezone.datetime.fromisoformat(invitation_sent_at.replace('Z', '+00:00'))
                if completed_at and isinstance(completed_at, str):
                    completed_at = timezone.datetime.fromisoformat(completed_at.replace('Z', '+00:00'))

                ReviewerToken.objects.create(
                    cycle=cycle,
                    category=token_data['category'],
                    invitation_sent_at=invitation_sent_at,
                    completed_at=completed_at,
                )

            # Note: Response import is intentionally skipped in this version
            # Responses reference question IDs which change on import
            # To properly import responses, implement UUID-based question matching
            if cycle_data.get('responses'):
                result['warnings'].append(
                    f"Skipped {len(cycle_data['responses'])} responses for cycle - "
                    "response import requires UUID-based question matching"
                )

            result['created'] += 1
            result['imported_cycles'].append(cycle)  # Track for report attachment

        except Exception as e:
            result['errors'].append(f"Failed to import review cycle: {str(e)}")

    return result


def import_users(organization, users_data, conflict_resolution='skip', send_welcome_email=False):
    """
    Import users and create profiles.

    Args:
        organization: Organization instance
        users_data: List of user dicts from export
        conflict_resolution: 'skip', 'overwrite', or 'duplicate'
        send_welcome_email: Whether to send password reset emails

    Returns:
        dict: Import result with counts and warnings
    """
    from accounts.models import UserProfile

    result = {
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'warnings': [],
        'errors': [],
    }

    for user_data in users_data:
        try:
            username = user_data['username']
            email = user_data['email']

            # Check if user exists
            existing_user = User.objects.filter(username=username).first()

            if existing_user:
                if conflict_resolution == 'skip':
                    result['skipped'] += 1
                    continue

                elif conflict_resolution == 'overwrite':
                    # Update email if changed
                    if existing_user.email != email:
                        existing_user.email = email
                        existing_user.save()
                    result['updated'] += 1

                    # Update profile if exists
                    try:
                        profile = existing_user.profile
                        profile.can_create_cycles_for_others = user_data.get('can_create_cycles_for_others', False)
                        profile.save()
                    except UserProfile.DoesNotExist:
                        pass

                    continue

                elif conflict_resolution == 'duplicate':
                    # Create with modified username
                    original_username = username
                    username = f"{username}_imported"
                    result['warnings'].append(f"Created user with modified username: {username} (original: {original_username})")

            # Create new user with random password (same method as subscription signup)
            alphabet = string.ascii_letters + string.digits
            password = ''.join(secrets.choice(alphabet) for _ in range(16))

            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
            )

            # Create profile
            profile = UserProfile.objects.create(
                user=user,
                organization=organization,
                can_create_cycles_for_others=user_data.get('can_create_cycles_for_others', False),
            )

            # Set permissions
            if user_data.get('is_org_admin', False):
                try:
                    perm = Permission.objects.get(codename='can_manage_organization')
                    user.user_permissions.add(perm)
                except Permission.DoesNotExist:
                    result['warnings'].append(f"Permission 'can_manage_organization' not found for user {username}")

            result['created'] += 1
            result['warnings'].append(
                f"User '{username}' created with random password. "
                "They will need to use password reset to access their account."
            )

        except Exception as e:
            result['errors'].append(f"Failed to import user {user_data.get('username', 'unknown')}: {str(e)}")

    return result


def import_reports(organization, reports_data, questionnaire_map, conflict_resolution='skip', imported_cycles=None):
    """
    Import generated reports.

    If cycles were imported in the same operation, attaches reports to those cycles.
    Otherwise, creates new cycles for each report to maintain data separation.

    Args:
        organization: Organization instance
        reports_data: List of report dicts from export
        questionnaire_map: Dict mapping questionnaire names to instances
        conflict_resolution: 'skip', 'overwrite', or 'duplicate'
        imported_cycles: List of cycles created in this import operation (optional)

    Returns:
        dict: Import result with counts and warnings
    """
    from reports.models import Report
    from reviews.models import ReviewCycle
    from accounts.models import Reviewee
    from questionnaires.models import Questionnaire

    result = {
        'created': 0,
        'skipped': 0,
        'warnings': [],
        'errors': [],
    }

    # Build map of imported cycles for quick lookup
    cycle_map = {}  # (reviewee_name, questionnaire_name) -> cycle
    if imported_cycles:
        for cycle in imported_cycles:
            key = (cycle.reviewee.name, cycle.questionnaire.name)
            cycle_map[key] = cycle

    for report_data in reports_data:
        try:
            # Find reviewee
            reviewee_name = report_data['reviewee']
            reviewee = Reviewee.objects.filter(
                organization=organization,
                name=reviewee_name
            ).first()

            if not reviewee:
                result['warnings'].append(f"Reviewee '{reviewee_name}' not found for report - skipping")
                result['skipped'] += 1
                continue

            # Try to find a questionnaire for this cycle
            questionnaire = None
            questionnaire_name = report_data.get('questionnaire_name')

            if questionnaire_name:
                # Try from map first (if imported in same operation)
                questionnaire = questionnaire_map.get(questionnaire_name)

                # Try from database
                if not questionnaire:
                    questionnaire = Questionnaire.objects.filter(
                        organization=organization,
                        name=questionnaire_name
                    ).first()

            # If no questionnaire specified, use organization's default or first active
            if not questionnaire:
                questionnaire = Questionnaire.objects.filter(
                    organization=organization,
                    is_active=True
                ).order_by('-is_default', 'created_at').first()

            if not questionnaire:
                result['warnings'].append(f"No questionnaire found for report (reviewee: {reviewee_name}) - skipping")
                result['skipped'] += 1
                continue

            # Try to find a matching imported cycle first
            cycle = None
            if questionnaire_name:
                cycle_key = (reviewee_name, questionnaire_name)
                cycle = cycle_map.get(cycle_key)

            # If no matching imported cycle, create a new one
            if not cycle:
                # Parse generated_at timestamp
                generated_at = report_data.get('generated_at')
                if generated_at and isinstance(generated_at, str):
                    generated_at = timezone.datetime.fromisoformat(generated_at.replace('Z', '+00:00'))

                cycle = ReviewCycle.objects.create(
                    reviewee=reviewee,
                    questionnaire=questionnaire,
                    status='completed',  # Reports are for completed cycles
                )

            # Check if report already exists for this cycle
            if hasattr(cycle, 'report'):
                if conflict_resolution == 'skip':
                    result['skipped'] += 1
                    continue
                elif conflict_resolution == 'overwrite':
                    cycle.report.delete()

            # Parse generated_at timestamp
            generated_at = report_data.get('generated_at')
            if generated_at and isinstance(generated_at, str):
                generated_at = timezone.datetime.fromisoformat(generated_at.replace('Z', '+00:00'))

            # Create report attached to the cycle
            Report.objects.create(
                cycle=cycle,
                report_data=report_data.get('report_data', {}),
                available=True,
                generated_at=generated_at or timezone.now(),
            )
            result['created'] += 1

        except Exception as e:
            result['errors'].append(f"Failed to import report: {str(e)}")

    return result


def import_organization_data(
    organization,
    data,
    mode='merge',
    conflict_resolution='skip',
    import_options=None,
    importing_user=None
):
    """
    Main function to import organization data from exported JSON.

    Args:
        organization: Target Organization instance
        data: Parsed JSON data from export file
        mode: 'merge' (validate mode handled separately)
        conflict_resolution: 'skip', 'overwrite', or 'duplicate'
        import_options: Dict specifying what to import
        importing_user: User performing the import (for audit logging)

    Returns:
        dict: {
            'success': bool,
            'summary': str,
            'details': dict,
            'errors': list,
            'warnings': list,
        }
    """

    result = {
        'success': False,
        'summary': '',
        'details': {},
        'errors': [],
        'warnings': [],
    }

    # Default import options
    import_options = import_options or {
        'users': False,  # Don't import users by default
        'reviewees': True,
        'questionnaires': True,
        'cycles': True,
        'reports': False,  # Don't import reports by default
    }

    try:
        # Use database transaction for atomicity
        with transaction.atomic():

            # Step 1: Validate data
            validation = validate_import_data(data)
            if not validation['valid']:
                result['errors'] = validation['errors']
                result['warnings'] = validation.get('warnings', [])
                return result

            # Add any validation warnings
            result['warnings'].extend(validation.get('warnings', []))

            # Step 2: Import in dependency order

            # Track imported entities for relationship building
            questionnaire_map = {}

            # 2.1 Import Reviewees
            if import_options.get('reviewees'):
                reviewee_result = import_reviewees(
                    organization,
                    data.get('reviewees', []),
                    conflict_resolution
                )
                result['details']['reviewees'] = reviewee_result
                result['warnings'].extend(reviewee_result.get('warnings', []))
                result['errors'].extend(reviewee_result.get('errors', []))

            # 2.2 Import Questionnaires
            if import_options.get('questionnaires'):
                questionnaire_result = import_questionnaires(
                    organization,
                    data.get('questionnaires', []),
                    conflict_resolution
                )
                result['details']['questionnaires'] = questionnaire_result
                result['warnings'].extend(questionnaire_result.get('warnings', []))
                result['errors'].extend(questionnaire_result.get('errors', []))
                questionnaire_map = questionnaire_result.get('questionnaire_map', {})

            # 2.3 Import Users (optional)
            if import_options.get('users'):
                user_result = import_users(
                    organization,
                    data.get('users', []),
                    conflict_resolution
                )
                result['details']['users'] = user_result
                result['warnings'].extend(user_result.get('warnings', []))
                result['errors'].extend(user_result.get('errors', []))

            # 2.4 Import Review Cycles (if dependencies met)
            imported_cycles = []
            if import_options.get('cycles'):
                if import_options.get('reviewees') and import_options.get('questionnaires'):
                    cycle_result = import_review_cycles(
                        organization,
                        data.get('review_cycles', []),
                        questionnaire_map,
                        conflict_resolution
                    )
                    result['details']['cycles'] = cycle_result
                    result['warnings'].extend(cycle_result.get('warnings', []))
                    result['errors'].extend(cycle_result.get('errors', []))
                    imported_cycles = cycle_result.get('imported_cycles', [])
                else:
                    result['warnings'].append(
                        "Skipped cycle import: requires both reviewees and questionnaires to be imported"
                    )

            # 2.5 Import Reports (if enabled)
            if import_options.get('reports'):
                # If cycles were imported, attach reports to those cycles
                # Otherwise, create new cycles for reports to keep data separate
                report_result = import_reports(
                    organization,
                    data.get('reports', []),
                    questionnaire_map,
                    conflict_resolution,
                    imported_cycles=imported_cycles if imported_cycles else None
                )
                result['details']['reports'] = report_result
                result['warnings'].extend(report_result.get('warnings', []))
                result['errors'].extend(report_result.get('errors', []))

            # Step 3: Generate summary
            summary_parts = []
            for data_type, type_result in result['details'].items():
                created = type_result.get('created', 0)
                updated = type_result.get('updated', 0)
                skipped = type_result.get('skipped', 0)

                parts = []
                if created > 0:
                    parts.append(f"{created} created")
                if updated > 0:
                    parts.append(f"{updated} updated")
                if skipped > 0:
                    parts.append(f"{skipped} skipped")

                if parts:
                    summary_parts.append(f"{data_type.title()}: {', '.join(parts)}")

            result['summary'] = "; ".join(summary_parts) if summary_parts else "No data imported"
            result['success'] = True

            # If there were critical errors, raise exception to rollback
            if result['errors']:
                raise Exception(f"Import failed with errors: {'; '.join(result['errors'][:3])}")

    except Exception as e:
        result['success'] = False
        if str(e) not in [err for err in result['errors']]:
            result['errors'].append(str(e))
        # Transaction will automatically rollback

    return result
