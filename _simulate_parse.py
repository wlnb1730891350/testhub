import os, re, json

# Read the final_test_cases
with open('_final_cases_full.md', 'r', encoding='utf-8') as f:
    content = f.read()

# Simulate front-end parseTestCases logic
cleanContent = re.sub(r'\*\*([^*]+)\*\*', r'\1', content)

lines = [l for l in cleanContent.split('\n') if l.strip()]
testCases = []
isTableFormat = False
tableData = []

for line in lines:
    trimmedLine = line.strip()
    if '|' in trimmedLine and '--------' not in trimmedLine:
        cells = [c.strip() for c in trimmedLine.split('|')]
        cells = [c for c in cells if c]  # filter empty
        if len(cells) > 1:
            tableData.append(cells)
            isTableFormat = True

print(f"Table format: {isTableFormat}")
print(f"Total rows collected: {len(tableData)}")
print(f"First row (headers): {tableData[0] if tableData else 'NONE'}")
print(f"Second row: {tableData[1][:3] if len(tableData) > 1 else 'NONE'}...")

# Now parse like the front-end
headers = tableData[0]
for i in range(1, len(tableData)):
    row = tableData[i]
    testCase = {}
    
    # clean br tags
    def cleanBrTags(text):
        if not text:
            return ''
        return re.sub(r'<br\s*\/?>', '\n', text, flags=re.IGNORECASE)
    
    for j, header in enumerate(headers):
        value = cleanBrTags(row[j] if j < len(row) else '')
        cleanHeader = header.strip().lower()
        
        if cleanHeader in ['优先级', 'priority']:
            testCase['priority'] = value
        elif cleanHeader in ['用例id', '编号', 'id'] or '用例id' in cleanHeader:
            testCase['caseId'] = value
        elif cleanHeader in ['测试目标', '测试场景', '场景', '标题'] or '测试目标' in cleanHeader:
            testCase['scenario'] = value
        elif cleanHeader in ['前置条件', '前置', '前提条件']:
            testCase['precondition'] = value
        elif cleanHeader in ['测试步骤', '操作步骤', '步骤']:
            if '预期' not in cleanHeader and '结果' not in cleanHeader:
                testCase['steps'] = value
        elif cleanHeader in ['预期结果', '预期', '结果'] or '预期结果' in cleanHeader:
            testCase['expected'] = value
    
    if testCase.get('scenario') or testCase.get('caseId'):
        testCases.append(testCase)

print(f"\nTotal parsed test cases: {len(testCases)}")

# Count by caseId prefix
from collections import Counter
prefix_counts = Counter()
for tc in testCases:
    cid = tc.get('caseId', '')
    prefix = cid.split('-')[0] if '-' in cid else 'NO_PREFIX'
    prefix_counts[prefix] += 1

print("\nParsed cases by prefix:")
for prefix, count in sorted(prefix_counts.items()):
    print(f"  {prefix}: {count}")

# Check for duplicate header rows parsed as cases
header_rows = [tc for tc in testCases if tc.get('caseId', '').startswith('用例') or tc.get('scenario', '').startswith('测试目标')]
print(f"\nHeader rows incorrectly parsed as cases: {len(header_rows)}")

# Find LOT (lottery) cases
lot_cases = [tc for tc in testCases if tc.get('caseId', '').startswith('LOT')]
print(f"\nLottery (LOT) cases found: {len(lot_cases)}")
for tc in lot_cases[:3]:
    print(f"  {tc.get('caseId')}: {tc.get('scenario', '')[:50]}...")

# Save parsed results for inspection
with open('_parsed_cases.json', 'w', encoding='utf-8') as f:
    json.dump(testCases, f, ensure_ascii=False, indent=2)
print(f"\nFull parsed results saved to _parsed_cases.json")
