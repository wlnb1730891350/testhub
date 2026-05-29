#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
更新 prompt_config 表中的 writer prompt 为 V7 版本（增加禁止杜撰规则）
直接使用 pymysql 连接数据库，无需 Django 环境
"""
import os
import sys
import io

# 强制设置标准输出为 UTF-8 编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import pymysql

def update_prompt():
    """直接使用 pymysql 更新数据库"""
    # 读取 V7 prompt 文件
    prompt_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_prompt_writer_v7.txt')
    
    if not os.path.exists(prompt_file):
        print(f"错误：找不到 Prompt 文件 {prompt_file}")
        return False
    
    with open(prompt_file, 'r', encoding='utf-8') as f:
        prompt_content = f.read().strip()
    
    print(f"读取到 Prompt 长度: {len(prompt_content)} 字符")
    
    # 连接数据库
    try:
        conn = pymysql.connect(
            host='localhost',
            user='root',
            password='',
            database='testhub',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
    except Exception as e:
        print(f"数据库连接失败: {e}")
        return False
    
    try:
        with conn.cursor() as cursor:
            # 先查询现有的 prompt
            cursor.execute("SELECT id, prompt_type, LENGTH(content) as content_length FROM prompt_config WHERE prompt_type = 'writer'")
            existing = cursor.fetchone()
            
            if existing:
                print(f"找到现有记录: ID={existing['id']}, 类型={existing['prompt_type']}, 当前长度={existing['content_length']}字符")
                
                # 更新 prompt_config 表中 prompt_type='writer' 的记录
                sql = """
                UPDATE prompt_config 
                SET content = %s, updated_at = NOW() 
                WHERE prompt_type = 'writer'
                """
                cursor.execute(sql, (prompt_content,))
                conn.commit()
                
                # 验证更新
                cursor.execute("SELECT id, prompt_type, LENGTH(content) as content_length, updated_at FROM prompt_config WHERE prompt_type = 'writer'")
                result = cursor.fetchone()
                
                if result:
                    print("数据库更新成功！")
                    print(f"   ID: {result['id']}")
                    print(f"   Prompt类型: {result['prompt_type']}")
                    print(f"   内容长度: {result['content_length']} 字符")
                    print(f"   更新时间: {result['updated_at']}")
                    return True
            else:
                print("未找到 writer 类型的 prompt 记录，尝试创建新记录...")
                sql = """
                INSERT INTO prompt_config (name, prompt_type, content, is_active, created_at, updated_at) 
                VALUES ('Writer Prompt V7', 'writer', %s, 1, NOW(), NOW())
                """
                cursor.execute(sql, (prompt_content,))
                conn.commit()
                
                cursor.execute("SELECT id, prompt_type, LENGTH(content) as content_length FROM prompt_config WHERE prompt_type = 'writer'")
                result = cursor.fetchone()
                
                if result:
                    print("数据库创建成功！")
                    print(f"   ID: {result['id']}")
                    print(f"   Prompt类型: {result['prompt_type']}")
                    print(f"   内容长度: {result['content_length']} 字符")
                    return True
                
    except Exception as e:
        print(f"数据库操作失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
    
    return False

if __name__ == '__main__':
    success = update_prompt()
    sys.exit(0 if success else 1)
