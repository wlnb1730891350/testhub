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
    # Look for TASK_B71FB793 generation start
    if 'TASK_B71FB793' in line and ('generate' in line.lower() or '生成' in line):
        results.append(f'{i}: {line}')
    # Look for review logs
    if 'TASK_B71FB793' in line and ('review' in line.lower() or '评审' in line):
        results.append(f'{i}: {line}')
    # Look for revise logs
    if 'TASK_B71FB793' in line and ('revise' in line.lower() or '改进' in line or 'revising' in line.lower()):
        results.append(f'{i}: {line}')
    # Look for any ERROR or WARNING
    if 'TASK_B71FB793' in line and ('ERROR' in line or 'WARNING' in line):
        results.append(f'{i}: {line}')

# Write to file to avoid encoding issues
with open('debug_task_log.txt', 'w', encoding='utf-8') as f:
    f.write(f'Found {len(results)} relevant log entries:\n\n')
    for line in results:
        f.write(line + '\n')

print(f'Found {len(results)} entries, written to debug_task_log.txt')
