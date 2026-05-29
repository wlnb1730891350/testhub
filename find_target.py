# Fix views.py: add task.save() after merge in stream mode
with open('C:\\Users\\a\\.qclaw\\workspace\\testhub_platform\\apps\\requirement_analysis\\views.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# The target is around line 3204 (0-indexed: 3203)
# Find the exact line with "测试用例改进完成"
target_line = None
for i in range(3190, 3210):
    if i < len(lines) and '测试用例改进完成' in lines[i]:
        target_line = i
        break

if target_line:
    print(f'Found target at line {target_line + 1}: {lines[target_line].strip()[:60]}')
    
    # Check the next few lines
    for j in range(5):
        if target_line + j < len(lines):
            print(f'{target_line + j + 1}: {lines[target_line + j].rstrip()[:80]}')
else:
    print('Target line not found')
