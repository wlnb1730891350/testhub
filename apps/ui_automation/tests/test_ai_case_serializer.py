from types import SimpleNamespace

import pytest
from rest_framework import serializers

from apps.ui_automation.serializers import AICaseSerializer


def _legacy_case(template_id=2, project_id=1):
    return SimpleNamespace(
        execution_target='web',
        desktop_config={},
        desktop_app_profile=None,
        setup_template_id=template_id,
        project_id=project_id,
        setup_template=SimpleNamespace(pk=template_id, project_id=99),
        project=SimpleNamespace(id=project_id),
    )


def test_legacy_mismatched_template_does_not_block_unrelated_case_update():
    serializer = AICaseSerializer(instance=_legacy_case())
    attrs = {
        'execution_target': 'desktop',
        'desktop_config': {},
        'setup_template': SimpleNamespace(pk=2, project_id=99),
        'project': SimpleNamespace(id=1),
    }

    assert serializer.validate(attrs) == attrs


def test_legacy_mismatched_template_does_not_block_partial_update_when_omitted():
    serializer = AICaseSerializer(instance=_legacy_case())
    attrs = {'execution_target': 'desktop', 'desktop_config': {}}

    assert serializer.validate(attrs) == attrs


def test_new_mismatched_template_still_fails_validation():
    serializer = AICaseSerializer(instance=_legacy_case())
    attrs = {
        'setup_template': SimpleNamespace(pk=3, project_id=99),
        'project': SimpleNamespace(id=1),
    }

    with pytest.raises(serializers.ValidationError, match='前置模板必须属于该用例所属项目'):
        serializer.validate(attrs)
