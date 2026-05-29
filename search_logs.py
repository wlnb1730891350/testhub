import os

log_path = 'C:\\Users\\a\\.qclaw\\workspace\\testhub_platform\\logs\\app.log'

with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
    # Read last 500KB
    f.seek(0, 2)  # Go to end
    size = f.tell()
    start = max(0, size - 500000)
    f.seek(start)
    content = f.read()

# Find merge-related logs
lines = content.split('\n')
results = []

for i, line in enumerate(lines):
    # Look for TASK_B71FB793 or TASK_29851E44
    if 'TASK_B71FB793' in line or 'TASK_29851E44' in line:
        results.append(line)
    # Look for merge logs
    if '增量合并' in line or 'merged' in line.lower():
        results.append(line)
    # Look for "测试用例改进完成"
    if '测试用例改进完成' in line or '改进完成' in line:
        results.append(line)
    # Look for renumber/sort logs
    if '排序' in line or '编号' in line:
        results.append(line)

print(f'Found {len(results)} relevant log entries:')
for line in results[-50:]:  # Last 50
    print(line)
