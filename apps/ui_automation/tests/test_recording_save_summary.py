from django.test import TestCase

from apps.ui_automation.models import (
    Element,
    LocatorStrategy,
    RecordingSession,
    TestCase as UiTestCase,
    TestCaseStep as UiTestCaseStep,
    UiProject,
)
from apps.ui_automation.recording_engine import RecordingEngine
from apps.users.models import User


class RecordingSaveSummaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.order_by('id').first()
        if self.user is None:
            raise AssertionError('RecordingSaveSummaryTests requires at least one existing user in the database.')
        self.project = UiProject.objects.create(
            name='Recording Summary Project',
            description='',
            base_url='https://example.com',
            owner=self.user,
        )
        self.project.members.add(self.user)

        self.strategy, _ = LocatorStrategy.objects.get_or_create(
            id=1,
            defaults={'name': 'css', 'description': 'CSS selector'},
        )

        self.existing_case = UiTestCase.objects.create(
            name='Existing Test Case',
            description='',
            project=self.project,
            status='draft',
            priority='medium',
            created_by=self.user,
        )
        self.existing_element = Element.objects.create(
            project=self.project,
            name='existing button',
            description='',
            element_type='BUTTON',
            locator_strategy=self.strategy,
            locator_value='#existing',
            page='/demo',
            validation_status='UNKNOWN',
            created_by=self.user,
        )
        UiTestCaseStep.objects.create(
            test_case=self.existing_case,
            step_number=1,
            action_type='click',
            element=self.existing_element,
            description='existing step',
        )

        RecordingSession.objects.create(
            project=self.project,
            created_by=self.user,
            session_id='rec-summary',
            start_url='https://example.com',
            status='stopped',
            recorded_actions=[
                {
                    'action_type': 'click',
                    'locator_strategy': 'css',
                    'locator_value': '#new',
                    'locator_description': 'new button',
                    'element_tag': 'button',
                    'element_text': 'New',
                    'page_url': 'https://example.com/demo',
                }
            ],
        )

    def test_append_save_returns_total_steps_after_save(self):
        result = RecordingEngine.save_as_test_case(
            session_id='rec-summary',
            test_case_name=self.existing_case.name,
            project_id=self.project.id,
            user=self.user,
            target_test_case_id=self.existing_case.id,
            selected_action_indexes=[0],
        )

        self.existing_case.refresh_from_db()

        assert result['success'] is True
        assert result['save_mode'] == 'append'
        assert result['steps_before_save'] == 1
        assert result['steps_created'] == 1
        assert result['total_steps_after_save'] == 2
        assert self.existing_case.steps.count() == 2
