# Fix views.py: add task.save() after merge
with open('C:\\Users\\a\\.qclaw\\workspace\\testhub_platform\\apps\\requirement_analysis\\views.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find both occurrences of the pattern
# Pattern 1: stream mode (around line 3204)
# Pattern 2: complete mode (around line 3400)

# We need to add task.save() after the logger.info line in BOTH places

# The pattern to find:
# logger.info(f"任务 {task.task_id} 测试用例改进完成...")
# else:
#     # 如果返回为空

# We'll use a unique context marker - the line before contains "renumbered_cases"

# Method: find by unique surrounding context
target_pattern = '''task.final_test_cases = renumbered_cases
                                            logger.info(
                                                f"任务 {task.task_id} 测试用例改进完成 (merged长度: {len(merged_cases)}, 最终保存长度: {len(task.final_test_cases)})")
                                        else:'''

replacement = '''task.final_test_cases = renumbered_cases
                                            logger.info(
                                                f"任务 {task.task_id} 测试用例改进完成 (merged长度: {len(merged_cases)}, 最终保存长度: {len(task.final_test_cases)})")
                                            # 保存合并后的最终用例到数据库
                                            task.save(update_fields=['final_test_cases'])
                                        else:'''

# Count occurrences
count = content.count(target_pattern)
print(f'Found {count} occurrences of the pattern')

if count == 2:
    # Replace both
    new_content = content.replace(target_pattern, replacement)
    with open('C:\\Users\\a\\.qclaw\\workspace\\testhub_platform\\apps\\requirement_analysis\\views.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Successfully added task.save() after merge in both places')
else:
    print(f'Unexpected count: {count}')
