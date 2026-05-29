#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Update prompt_config writer to V7 via Django ORM"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
import django
django.setup()

from apps.requirement_analysis.models import PromptConfig

# Read V7 prompt file
v7_path = os.path.join(os.path.dirname(__file__), "_prompt_writer_v7.txt")
with open(v7_path, "r", encoding="utf-8") as f:
    v7_content = f.read()

# Remove the final "instruction" line that the code handles
# (the line "现在基于以下需求生成测试用例，严格遵守所有规则：" is appended by code)
# Actually, the V7 file IS the system prompt. Let's use it as-is.
# The code appends the requirement text separately anyway.

# Update DB
p = PromptConfig.objects.filter(prompt_type='writer').first()
if p:
    p.content = v7_content
    p.save()
    print(f"OK: Updated prompt_config id={p.id}, new length={len(v7_content)} chars")
else:
    print("ERROR: No writer prompt_config found!")