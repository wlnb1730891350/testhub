#!/usr/bin/env python3
"""
更新 prompt_config 表中的 writer prompt 为 V8 版本（增加禁止杜撰规则）
直接使用 pymysql 连接数据库，无需 Django 环境
"""
import os
import pymysql

def update_prompt():
    """直接使用 pymysql 更新数据库"""
    # 读取 V7 prompt 文件
    prompt_file = os.path.join(os.path.dirname(__file__), '_prompt_writer_v7.txt')
    with open(prompt_file, 'r', encoding='utf-8') as f:
        prompt_content = f.read().strip()
    
    print(f"读取到 Prompt 长度: {len(prompt_content)} 字符")
    
    # 连接数据库
    conn = pymysql.connect(
        host='localhost',
        user='root',
        password='',
        database='testhub',
        charset='utf8mb4'
    )
    
    try:
        with conn.cursor() as cursor:
            # 更新 prompt_config 表中 prompt_type='writer' 的记录
            sql = """
            UPDATE prompt_config 
            SET content = %s, updated_at = NOW() 
            WHERE prompt_type = 'writer'
            """
            cursor.execute(sql, (prompt_content,))
            conn.commit()
            
            # 验证更新
            cursor.execute("SELECT id, prompt_type, LENGTH(content) as content_length FROM prompt_config WHERE prompt_type = 'writer'")
            result = cursor.fetchone()
            
            if result:
                print(f"✅ 数据库更新成功！")
                print(f"   ID: {result[0]}")
                print(f"   Prompt类型: {result[1]}")
                print(f"   内容长度: {result[2]} 字符")
            else:
                print("❌ 未找到 writer 类型的 prompt 记录")
                
    except Exception as e:
        print(f"❌ 数据库更新失败: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    update_prompt()
