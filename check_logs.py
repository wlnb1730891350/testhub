import os
import re

# Check Django log for merge stats
log_path = 'C:\\Users\\a\\.qclaw\\workspace\\testhub_platform\\django_log.txt'
if os.path.exists(log_path):
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # Find merge-related log entries
    lines = content.split('\n')
    merge_lines = []
    for i, line in enumerate(lines):
        if '增量合并完成' in line or 'merge' in line.lower() or 'revised' in line.lower():
            merge_lines.append(f'{i}: {line}')
        if 'TASK_B71FB793' in line or 'TASK_29851E44' in line:
            if '合并' in line or 'merge' in line.lower() or '改进' in line:
                merge_lines.append(f'{i}: {line}')
    
    print(f'Found {len(merge_lines)} merge-related log entries:')
    for line in merge_lines[-30:]:  # Last 30
        print(line)
else:
    print(f'Log file not found: {log_path}')
