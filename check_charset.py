import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()
from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("SHOW VARIABLES LIKE 'character_set%'")
    print("=== MySQL Character Set Variables ===")
    for row in cursor.fetchall():
        print(f'{row[0]}: {row[1]}')
    
    # Check table charset
    cursor.execute("SHOW CREATE TABLE testcase_generation_task")
    result = cursor.fetchone()
    print("\n=== Table Create Statement ===")
    print(result[1][:500])
