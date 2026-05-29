# Find all task.save() calls in views.py
with open('C:\\Users\\a\\.qclaw\\workspace\\testhub_platform\\apps\\requirement_analysis\\views.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find lines with task.save()
save_lines = []
for i, line in enumerate(lines):
    if 'task.save()' in line:
        save_lines.append((i+1, line.strip()))

print(f'Found {len(save_lines)} task.save() calls:')
for line_num, content in save_lines:
    print(f'Line {line_num}: {content[:80]}')
